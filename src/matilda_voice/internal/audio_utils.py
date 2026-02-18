"""Shared audio utilities for TTS providers to avoid code duplication."""

import asyncio
import contextlib
import logging
import os
import subprocess
import tempfile
import threading
import time
import wave
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Tuple

from ..exceptions import AudioPlaybackError, DependencyError
from .config import get_config_value

# Module logger
logger = logging.getLogger(__name__)

# Cache for audio environment check
_AUDIO_ENV_CACHE: Optional[Dict[str, Any]] = None

# Cache for audio duration: path -> (mtime, size, duration)
_AUDIO_DURATION_CACHE: Dict[str, Tuple[float, int, float]] = {}
_MAX_CACHE_SIZE = 1000


# =============================================================================
# Helper utilities for parameter parsing
# =============================================================================


def parse_bool_param(value: Any, default: bool = False) -> bool:
    """Parse a boolean parameter that may be bool or string.

    This utility handles the common case where a parameter can be passed
    as either a Python bool or a string representation.

    Args:
        value: The value to parse (bool, str, or None)
        default: Default value if value is None

    Returns:
        The parsed boolean value

    Examples:
        >>> parse_bool_param(True)
        True
        >>> parse_bool_param("true")
        True
        >>> parse_bool_param("1")
        True
        >>> parse_bool_param("yes")
        True
        >>> parse_bool_param(None, default=False)
        False
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in ("true", "1", "yes")


# =============================================================================
# StreamingPlayer - Unified audio chunk streaming
# =============================================================================


class StreamingPlayer:
    """Handles real-time audio streaming with progress tracking.

    This class provides a unified interface for streaming audio chunks to
    ffplay, consolidating the duplicate streaming logic from multiple providers.

    Features:
    - Chunk counting and byte tracking
    - First-chunk latency measurement
    - Progress logging at configurable intervals
    - Broken pipe handling
    - Proper process cleanup
    - Keyboard interrupt handling

    Usage:
        player = StreamingPlayer("OpenAI")

        # Synchronous streaming
        response = client.audio.speech.create(...)
        player.play_chunks(response.iter_bytes())

        # Asynchronous streaming
        async for chunk in async_response:
            await player.play_chunks_async(async_iter)

        # Edge TTS style (dict with 'type' and 'data' keys)
        await player.play_edge_tts_stream(communicate.stream())
    """

    def __init__(
        self,
        provider_name: str,
        format_args: Optional[List[str]] = None,
        progress_interval: Optional[int] = None,
        pulse_available: bool = False,
    ):
        """Initialize the streaming player.

        Args:
            provider_name: Name of the provider (for logging)
            format_args: FFplay format arguments (e.g., ["-f", "mp3"])
            progress_interval: Log progress every N chunks (default from config)
            pulse_available: Whether PulseAudio is available (for format selection)
        """
        self.provider_name = provider_name
        self.format_args = format_args or []
        self.pulse_available = pulse_available
        self.logger = logging.getLogger(__name__)
        self.chunk_count = 0
        self.bytes_written = 0
        self.first_chunk_time: Optional[float] = None
        self.start_time: Optional[float] = None
        self.progress_interval = progress_interval or get_config_value("streaming_progress_interval", 100)
        self._ffplay_process: Optional[subprocess.Popen] = None

    def _create_process(self) -> subprocess.Popen:
        """Create the ffplay process with appropriate format args."""
        format_args = list(self.format_args)
        if self.pulse_available and "-f" not in format_args:
            format_args.extend(["-f", "pulse"])
        return create_ffplay_process(logger=self.logger, format_args=format_args)

    def play_chunks(self, chunks: Iterator[bytes]) -> None:
        """Stream audio chunks to ffplay synchronously.

        Args:
            chunks: Iterator of audio byte chunks

        Raises:
            DependencyError: If ffplay is not available
            AudioPlaybackError: If streaming fails
        """
        self.start_time = time.time()
        self._ffplay_process = self._create_process()

        try:
            for chunk in chunks:
                if not self._process_chunk(chunk, self._ffplay_process):
                    break
        except KeyboardInterrupt:
            self._terminate_process()
            raise
        except BrokenPipeError:
            self._handle_broken_pipe(self._ffplay_process)
        finally:
            self._cleanup(self._ffplay_process)

    async def play_chunks_async(self, chunks: AsyncIterator[bytes]) -> None:
        """Stream audio chunks to ffplay asynchronously.

        Args:
            chunks: Async iterator of audio byte chunks

        Raises:
            DependencyError: If ffplay is not available
            AudioPlaybackError: If streaming fails
        """
        self.start_time = time.time()
        self._ffplay_process = self._create_process()

        try:
            async for chunk in chunks:
                if not self._process_chunk(chunk, self._ffplay_process):
                    break
        except KeyboardInterrupt:
            self._terminate_process()
            raise
        except BrokenPipeError:
            self._handle_broken_pipe(self._ffplay_process)
        finally:
            self._cleanup(self._ffplay_process)

    async def play_async(
        self,
        chunks: AsyncIterator[Any],
        transform: Optional[Callable[[Any], Optional[bytes]]] = None,
    ) -> None:
        """Stream audio chunks with optional transformation.

        Args:
            chunks: Async iterator of source chunks.
            transform: Optional transformer to extract bytes from each chunk.
        """
        self.start_time = time.time()
        self._ffplay_process = self._create_process()

        try:
            async for chunk in chunks:
                data = transform(chunk) if transform else chunk
                if not data:
                    continue
                if not self._process_chunk(data, self._ffplay_process):
                    break
        except KeyboardInterrupt:
            self._terminate_process()
            raise
        except BrokenPipeError:
            self._handle_broken_pipe(self._ffplay_process)
        finally:
            self._cleanup(self._ffplay_process)

    async def play_edge_tts_stream(self, stream: AsyncIterator[Dict[str, Any]]) -> None:
        """Stream Edge TTS audio chunks (dict format with 'type' and 'data' keys).

        Edge TTS yields dicts like {'type': 'audio', 'data': bytes} instead of
        raw bytes. This method handles that format.

        Args:
            stream: Async iterator of Edge TTS chunk dicts

        Raises:
            DependencyError: If ffplay is not available
            AudioPlaybackError: If streaming fails
        """
        self.start_time = time.time()
        self._ffplay_process = self._create_process()

        try:
            async for chunk in stream:
                if chunk.get("type") == "audio":
                    if not self._process_chunk(chunk["data"], self._ffplay_process):
                        break
        except KeyboardInterrupt:
            self._terminate_process()
            raise
        except BrokenPipeError:
            self._handle_broken_pipe(self._ffplay_process)
        finally:
            self._cleanup(self._ffplay_process)

    def _terminate_process(self) -> None:
        """Terminate the ffplay process gracefully."""
        if self._ffplay_process and self._ffplay_process.poll() is None:
            self._ffplay_process.terminate()
            try:
                self._ffplay_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._ffplay_process.kill()

    def _process_chunk(self, chunk: bytes, process: subprocess.Popen) -> bool:
        """Process a single audio chunk.

        Args:
            chunk: Audio data bytes
            process: FFplay subprocess

        Returns:
            True to continue, False to stop
        """
        self.chunk_count += 1

        # Track first chunk latency
        if self.chunk_count == 1:
            self.first_chunk_time = time.time()
            self.logger.debug(f"[{self.provider_name}] First audio chunk received - starting playback")

        try:
            if process.stdin is not None:
                process.stdin.write(chunk)
                process.stdin.flush()
                self.bytes_written += len(chunk)

            # Log progress periodically
            if self.chunk_count % self.progress_interval == 0:
                self.logger.debug(
                    f"[{self.provider_name}] Streamed {self.chunk_count} chunks, " f"{self.bytes_written} bytes"
                )

            return True

        except BrokenPipeError:
            # Check if ffplay ended early
            if process.poll() is not None:
                self._handle_broken_pipe(process)
                return False
            raise

    def _handle_broken_pipe(self, process: subprocess.Popen) -> None:
        """Handle broken pipe error from ffplay.

        Args:
            process: FFplay subprocess
        """
        if process.poll() is not None:
            stderr = ""
            if process.stderr:
                try:
                    stderr = process.stderr.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
            self.logger.warning(
                f"[{self.provider_name}] FFplay ended early " f"(exit code: {process.returncode}): {stderr}"
            )

    def _cleanup(self, process: subprocess.Popen) -> None:
        """Clean up ffplay process and log metrics.

        Args:
            process: FFplay subprocess
        """
        # Close stdin
        if process.stdin:
            try:
                process.stdin.close()
            except Exception:
                pass

        # Wait for process with timeout
        try:
            exit_code = process.wait(timeout=get_config_value("ffplay_timeout", 30))
        except subprocess.TimeoutExpired:
            self.logger.warning(f"[{self.provider_name}] FFplay timeout, terminating")
            process.terminate()
            try:
                process.wait(timeout=get_config_value("ffplay_termination_timeout", 5))
            except subprocess.TimeoutExpired:
                process.kill()
            exit_code = -1

        # Log timing metrics
        if self.first_chunk_time and self.start_time:
            latency = self.first_chunk_time - self.start_time
            total_time = time.time() - self.start_time
            self.logger.info(
                f"[{self.provider_name}] Streaming complete: "
                f"first chunk in {latency:.2f}s, total {total_time:.2f}s, "
                f"{self.chunk_count} chunks, {self.bytes_written} bytes"
            )
        else:
            self.logger.debug(
                f"[{self.provider_name}] Streaming ended: "
                f"{self.chunk_count} chunks, {self.bytes_written} bytes, "
                f"exit code: {exit_code}"
            )


class AudioPlaybackManager:
    """Centralized audio playback management with subprocess lifecycle tracking."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize the AudioPlaybackManager.

        Args:
            logger: Optional logger instance for debugging
        """
        self.logger = logger or logging.getLogger(__name__)
        self._current_process: Optional[subprocess.Popen] = None
        self._process_lock = threading.Lock()

    def play_with_tracking(self, audio_path: str, timeout: Optional[int] = None) -> subprocess.Popen:
        """Play audio with process tracking for background management.

        This method is intended for use cases like the voice browser where
        the calling code needs to track and potentially terminate playback.

        Note: This method does not handle cleanup automatically. The caller
        is responsible for cleaning up temporary files as needed.

        Args:
            audio_path: Path to the audio file to play
            timeout: Optional timeout for ffplay process

        Returns:
            The subprocess.Popen instance for the ffplay process

        Raises:
            DependencyError: If ffplay is not available
            AudioPlaybackError: If playback fails to start
        """
        # Check if audio playback is disabled (for testing)
        if os.environ.get("TTS_DISABLE_PLAYBACK", "").lower() in ("true", "1", "yes"):
            self.logger.debug(f"Audio playback disabled by TTS_DISABLE_PLAYBACK, creating mock process: {audio_path}")
            # Return a mock process that immediately exits successfully
            from unittest.mock import MagicMock

            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.poll.return_value = 0
            mock_process.wait.return_value = 0
            mock_process.terminate.return_value = None
            return mock_process

        if timeout is None:
            timeout = get_config_value("ffmpeg_conversion_timeout")

        try:
            with self._process_lock:
                # Terminate any existing process
                self._terminate_current_process()

                # Start new process
                process = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path],
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                )

                self._current_process = process
                self.logger.debug(f"Started audio playback with tracking: {audio_path}")

                return process

        except FileNotFoundError as e:
            self.logger.warning(f"FFplay not available, audio saved to: {audio_path}")
            raise DependencyError(f"Audio generated but cannot play automatically. File saved to: {audio_path}") from e
        except Exception as e:
            self.logger.exception(f"Failed to start audio playback for {audio_path}")
            raise AudioPlaybackError(f"Audio playback failed to start: {e}") from e

    def play_and_forget(self, audio_path: str, timeout: Optional[int] = None, cleanup: bool = False) -> None:
        """Play audio without tracking (fire-and-forget).

        This method is intended for regular TTS playback where the caller
        doesn't need to manage the subprocess lifecycle.

        Args:
            audio_path: Path to the audio file to play
            timeout: Optional timeout for ffplay process
            cleanup: Whether to delete the file after playing

        Raises:
            DependencyError: If ffplay is not available
            AudioPlaybackError: If playback fails
        """
        # Check if audio playback is disabled (for testing)
        if os.environ.get("TTS_DISABLE_PLAYBACK", "").lower() in ("true", "1", "yes"):
            self.logger.debug(f"Audio playback disabled by TTS_DISABLE_PLAYBACK, skipping: {audio_path}")
            return

        if timeout is None:
            timeout = get_config_value("ffmpeg_conversion_timeout")

        try:
            # Run and wait for completion
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path], check=True, timeout=timeout
            )

            self.logger.debug(f"Audio playback completed: {audio_path}")

        except FileNotFoundError as e:
            self.logger.warning(f"FFplay not available, audio saved to: {audio_path}")
            raise DependencyError(f"Audio generated but cannot play automatically. File saved to: {audio_path}") from e
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"FFplay failed to play audio file: {e}")
            raise AudioPlaybackError(f"Audio generated but playback failed. File saved to: {audio_path}") from e
        except subprocess.TimeoutExpired as e:
            self.logger.warning(f"FFplay playback timed out after {timeout} seconds")
            raise AudioPlaybackError(f"Audio playback timed out. File saved to: {audio_path}") from e
        finally:
            if cleanup:
                cleanup_file(audio_path, self.logger)

    def stop_playback(self) -> bool:
        """Stop any currently playing audio.

        Returns:
            True if a process was stopped, False if no process was running
        """
        with self._process_lock:
            return self._terminate_current_process()

    def is_playing(self) -> bool:
        """Check if audio is currently playing.

        Returns:
            True if audio is playing, False otherwise
        """
        with self._process_lock:
            if self._current_process is None:
                return False

            poll_result = self._current_process.poll()
            if poll_result is not None:
                # Process has ended
                self._current_process = None
                return False

            return True

    def get_current_process(self) -> Optional[subprocess.Popen]:
        """Get the current playback process.

        Returns:
            The current subprocess.Popen instance or None if not playing
        """
        with self._process_lock:
            return self._current_process

    def _terminate_current_process(self) -> bool:
        """Terminate the current playback process if it exists.

        Returns:
            True if a process was terminated, False if no process was running
        """
        if self._current_process is None:
            return False

        try:
            if self._current_process.poll() is None:  # Still running
                self._current_process.terminate()
                try:
                    self._current_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't terminate gracefully
                    self._current_process.kill()
                    self._current_process.wait()

                self.logger.debug("Terminated current audio playback process")
                return True
        except Exception:
            self.logger.exception("Error terminating audio process")
        finally:
            self._current_process = None

        return False


# Global manager instance
_global_manager: Optional[AudioPlaybackManager] = None


def get_audio_manager() -> AudioPlaybackManager:
    """Get the global AudioPlaybackManager instance.

    Returns:
        The global AudioPlaybackManager instance
    """
    global _global_manager
    if _global_manager is None:
        _global_manager = AudioPlaybackManager()
    return _global_manager


def play_audio_with_ffplay(
    audio_path: str, logger: Optional[logging.Logger] = None, cleanup: bool = False, timeout: Optional[int] = None
) -> None:
    """
    Play an audio file using ffplay (legacy function, use AudioPlaybackManager instead).

    Args:
        audio_path: Path to the audio file to play
        logger: Optional logger instance for debugging
        cleanup: Whether to delete the file after playing
        timeout: Optional timeout for ffplay process

    Raises:
        DependencyError: If ffplay is not available
        AudioPlaybackError: If playback fails
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # Use AudioPlaybackManager for consistency
    manager = AudioPlaybackManager(logger=logger)
    manager.play_and_forget(audio_path, timeout=timeout, cleanup=cleanup)


def cleanup_file(file_path: str, logger: Optional[logging.Logger] = None) -> None:
    """
    Safely clean up a temporary file.

    Args:
        file_path: Path to the file to delete
        logger: Optional logger instance for debugging
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
            logger.debug(f"Cleaned up temporary file: {file_path}")
        else:
            logger.debug(f"Temporary file does not exist, no cleanup needed: {file_path}")
    except OSError as e:
        # Log but don't fail if we can't clean up temp file
        logger.debug(f"Could not clean up temporary file {file_path}: {e}")
    except Exception:
        # Unexpected error during cleanup
        logger.exception(f"Unexpected error cleaning up temporary file {file_path}")


def stream_via_tempfile(
    synthesize_func: Callable, text: str, logger: logging.Logger, file_suffix: str = ".mp3", **synthesis_kwargs: Any
) -> None:
    """
    Fallback streaming method using temporary file when direct streaming fails.

    This is a generic implementation that providers can use to avoid duplication.

    Args:
        synthesize_func: Function to call for synthesis
            (should accept text, output_path, and kwargs)
        text: Text to synthesize
        logger: Logger instance for debugging
        file_suffix: File extension for the temporary file
        **synthesis_kwargs: Additional arguments to pass to the synthesis function
    """
    logger.info("Using temporary file fallback for audio streaming")

    with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as tmp:
        temp_file = tmp.name

    try:
        # Generate audio to temporary file
        synthesize_func(text, temp_file, **synthesis_kwargs)

        # Play the temporary file using AudioPlaybackManager
        manager = AudioPlaybackManager(logger=logger)
        manager.play_and_forget(temp_file, cleanup=False)

    finally:
        # Always clean up temporary file
        cleanup_file(temp_file, logger)


def create_ffplay_process(
    logger: logging.Logger, format_args: Optional[List[str]] = None, additional_args: Optional[List[str]] = None
) -> subprocess.Popen:
    """
    Create an ffplay process for streaming audio.

    Args:
        logger: Logger instance for debugging
        format_args: Format-specific arguments (e.g., ['-f', 'mp3'])
        additional_args: Additional ffplay arguments

    Returns:
        subprocess.Popen instance ready to receive audio data

    Raises:
        DependencyError: If ffplay is not available
    """
    # Check if audio playback is disabled (for testing)
    if os.environ.get("TTS_DISABLE_PLAYBACK", "").lower() in ("true", "1", "yes"):
        logger.debug("Audio playback disabled by TTS_DISABLE_PLAYBACK, creating mock process")
        # Return a mock process that accepts input but doesn't play audio
        from unittest.mock import MagicMock

        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.close = MagicMock()
        mock_process.stdin.flush = MagicMock()
        mock_process.returncode = 0
        mock_process.poll.return_value = 0
        mock_process.wait.return_value = 0
        mock_process.terminate.return_value = None
        return mock_process
    ffplay_cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"]

    if format_args:
        ffplay_cmd.extend(format_args)

    # Add format from stdin
    ffplay_cmd.extend(["-i", "pipe:0"])

    if additional_args:
        ffplay_cmd.extend(additional_args)

    logger.debug(f"Starting ffplay process: {' '.join(ffplay_cmd)}")

    try:
        process = subprocess.Popen(ffplay_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        return process
    except FileNotFoundError as e:
        raise DependencyError(
            "ffplay not found. Please install ffmpeg:\n"
            "  Ubuntu/Debian: sudo apt-get install ffmpeg\n"
            "  macOS: brew install ffmpeg\n"
            "  Windows: Download from https://ffmpeg.org/download.html"
        ) from e


def handle_ffplay_process_error(process: subprocess.Popen, logger: logging.Logger, context: str = "streaming") -> None:
    """
    Handle errors from an ffplay process.

    Args:
        process: The ffplay subprocess
        logger: Logger instance
        context: Context string for error messages
    """
    if process.poll() is not None:
        stderr_output = ""
        if process.stderr:
            stderr_output = process.stderr.read().decode("utf-8", errors="ignore")
        exit_code = process.returncode

        if exit_code != 0:
            logger.error(f"FFplay {context} failed (exit code: {exit_code}): {stderr_output}")
            raise AudioPlaybackError(f"Audio {context} failed: {stderr_output}")
        else:
            logger.debug(f"FFplay {context} completed successfully")


def check_audio_environment(force_refresh: bool = False) -> Dict[str, Any]:
    """Check if audio streaming is available in current environment.

    Args:
        force_refresh: Whether to force a re-check ignoring cache

    Returns:
        Dict with 'available' (bool), 'reason' (str), and device availability flags
    """
    global _AUDIO_ENV_CACHE
    if _AUDIO_ENV_CACHE is not None and not force_refresh:
        return _AUDIO_ENV_CACHE.copy()

    result = {"available": False, "reason": "Unknown", "pulse_available": False, "alsa_available": False}

    # Check for PulseAudio
    if "PULSE_SERVER" in os.environ:
        result["pulse_available"] = True
        result["available"] = True
        result["reason"] = "PulseAudio available"
        _AUDIO_ENV_CACHE = result
        return result

    # Check for ALSA devices
    try:
        if os.path.exists("/proc/asound/cards") and os.path.getsize("/proc/asound/cards") > 0:
            result["alsa_available"] = True
            result["available"] = True
            result["reason"] = "ALSA devices available"
            _AUDIO_ENV_CACHE = result
            return result
    except (ImportError, OSError, subprocess.SubprocessError) as e:
        logger.debug(f"ALSA check failed: {e}")

    # Check if we can reach audio system
    try:
        subprocess.run(["aplay", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        result["available"] = True
        result["reason"] = "Audio system responsive"
        _AUDIO_ENV_CACHE = result
        return result
    except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
        logger.debug(f"Audio system check failed: {e}")

    result["reason"] = "No audio devices or audio system unavailable"
    _AUDIO_ENV_CACHE = result
    return result


async def check_audio_environment_async() -> Dict[str, Any]:
    """Check if audio streaming is available in current environment (async).

    Uses native asyncio subprocess to avoid thread blocking.
    """
    global _AUDIO_ENV_CACHE
    if _AUDIO_ENV_CACHE is not None:
        return _AUDIO_ENV_CACHE.copy()

    result = {"available": False, "reason": "Unknown", "pulse_available": False, "alsa_available": False}

    # Check for PulseAudio
    if "PULSE_SERVER" in os.environ:
        result["pulse_available"] = True
        result["available"] = True
        result["reason"] = "PulseAudio available"
        _AUDIO_ENV_CACHE = result
        return result

    # Check for ALSA devices
    try:
        if os.path.exists("/proc/asound/cards") and os.path.getsize("/proc/asound/cards") > 0:
            result["alsa_available"] = True
            result["available"] = True
            result["reason"] = "ALSA devices available"
            _AUDIO_ENV_CACHE = result
            return result
    except (ImportError, OSError):
        logger.debug("ALSA check failed in async check")

    # Check if we can reach audio system
    try:
        process = await asyncio.create_subprocess_exec(
            "aplay",
            "--version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
            result["available"] = True
            result["reason"] = "Audio system responsive"
            _AUDIO_ENV_CACHE = result
            return result
        except asyncio.TimeoutError:
            try:
                process.terminate()
                await process.wait()
            except ProcessLookupError:
                pass
            logger.debug("Audio system check timed out")
    except (FileNotFoundError, OSError) as e:
        logger.debug(f"Audio system check failed: {e}")

    result["reason"] = "No audio devices or audio system unavailable"
    _AUDIO_ENV_CACHE = result
    return result


def stream_audio_file(audio_path: str) -> None:
    """Stream audio file to speakers using ffplay.

    Args:
        audio_path: Path to the audio file to play

    Raises:
        DependencyError: If ffplay is not found
        AudioPlaybackError: If playback fails
    """
    manager = get_audio_manager()
    manager.play_and_forget(audio_path)


def convert_audio(input_path: str, output_path: str, output_format: str) -> None:
    """Convert audio file to different format using ffmpeg.

    Args:
        input_path: Path to input audio file
        output_path: Path for output audio file
        output_format: Target audio format (extension will be added if needed)

    Raises:
        DependencyError: If ffmpeg is not found
        ProviderError: If conversion fails
    """
    try:
        subprocess.run(["ffmpeg", "-i", input_path, "-y", output_path], stderr=subprocess.DEVNULL, check=True)
    except FileNotFoundError as e:
        raise DependencyError("ffmpeg not found. Please install ffmpeg for format conversion.") from e
    except subprocess.CalledProcessError as e:
        from ..exceptions import ProviderError

        raise ProviderError(f"Audio conversion failed: {e}") from e


def convert_with_cleanup(input_path: str, output_path: str, output_format: str) -> None:
    """Convert audio file with automatic cleanup of input file.

    This is a convenience function that converts audio and cleans up the temporary
    input file afterwards, even if conversion fails.

    Args:
        input_path: Path to temporary input audio file (will be deleted)
        output_path: Path for output audio file
        output_format: Target audio format

    Raises:
        DependencyError: If ffmpeg is not found
        ProviderError: If conversion fails
    """
    try:
        convert_audio(input_path, output_path, output_format)
    finally:
        # Always cleanup temporary input file
        cleanup_file(input_path, logger)


def create_ffplay_process_simple(args: Optional[List[str]] = None, **kwargs: Any) -> subprocess.Popen[Any]:
    """Create and start an ffplay process with common settings (simple version).

    This is the simpler version from utils/audio.py with a different signature.
    Use create_ffplay_process for the standard version with logging support.

    Args:
        args: Additional command line arguments for ffplay
        **kwargs: Additional arguments passed to subprocess.Popen

    Returns:
        Running ffplay subprocess

    Raises:
        DependencyError: If ffplay is not found
    """
    cmd = ["ffplay"]
    if args:
        cmd.extend(args)

    # Set common defaults
    default_kwargs = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "bufsize": 0,
    }
    default_kwargs.update(kwargs)

    try:
        process: subprocess.Popen[Any] = subprocess.Popen(cmd, **default_kwargs)  # type: ignore
        return process
    except FileNotFoundError as e:
        raise DependencyError("ffplay not found. Please install ffmpeg for audio streaming.") from e


def stream_audio_data(audio_data: bytes, format_args: Optional[List[str]] = None) -> None:
    """Stream raw audio data through ffplay.

    Args:
        audio_data: Raw audio bytes to stream
        format_args: Additional format arguments for ffplay

    Raises:
        DependencyError: If ffplay is not found
        AudioPlaybackError: If streaming fails
    """
    cmd = ["ffplay", "-nodisp", "-autoexit", "-"]
    if format_args:
        cmd.extend(format_args)

    try:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        process.communicate(input=audio_data)

        if process.returncode != 0:
            raise AudioPlaybackError(f"Audio streaming failed with code {process.returncode}")

    except FileNotFoundError as e:
        raise DependencyError("ffplay not found. Please install ffmpeg for audio streaming.") from e
    except (subprocess.SubprocessError, OSError) as e:
        raise AudioPlaybackError(f"Audio streaming failed: {e}") from e


def normalize_audio_path(path: str, default_format: str = "wav") -> str:
    """Normalize audio file path and ensure it has proper extension.

    Args:
        path: Input file path
        default_format: Default format extension to add if missing

    Returns:
        Normalized path with proper extension
    """
    if not path.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac")):
        if not path.endswith("."):
            path += "."
        path += default_format
    return path


def _get_wav_duration(audio_path: str) -> Optional[float]:
    """Get duration of WAV file using standard library.

    Returns:
        Duration in seconds, or None if failed/not a wav.
    """
    try:
        with contextlib.closing(wave.open(audio_path, "rb")) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            if rate > 0:
                return frames / float(rate)
    except Exception:
        pass
    return None


async def get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds using ffprobe asynchronously.

    Args:
        audio_path: Path to audio file

    Returns:
        Duration in seconds, or 0.0 if cannot be determined
    """
    abs_path = None
    mtime = 0.0
    size = 0

    try:
        abs_path = os.path.abspath(audio_path)
        loop = asyncio.get_running_loop()
        stat_result = await loop.run_in_executor(None, os.stat, abs_path)
        mtime = stat_result.st_mtime
        size = stat_result.st_size

        if abs_path in _AUDIO_DURATION_CACHE:
            c_mtime, c_size, c_dur = _AUDIO_DURATION_CACHE[abs_path]
            if c_mtime == mtime and c_size == size:
                return c_dur
    except (OSError, RuntimeError):
        pass

    # Try fast path for WAV
    if audio_path.lower().endswith(".wav"):
        duration = _get_wav_duration(audio_path)
        if duration is not None:
            if abs_path:
                if len(_AUDIO_DURATION_CACHE) >= _MAX_CACHE_SIZE:
                    _AUDIO_DURATION_CACHE.clear()
                _AUDIO_DURATION_CACHE[abs_path] = (mtime, size, duration)
            return duration

    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            audio_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError):
        logger.debug(f"Could not get duration for {audio_path}: ffprobe not found or error starting")
        return 0.0

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)

        if process.returncode == 0 and stdout:
            duration = float(stdout.decode().strip())
            if abs_path:
                if len(_AUDIO_DURATION_CACHE) >= _MAX_CACHE_SIZE:
                    _AUDIO_DURATION_CACHE.clear()
                _AUDIO_DURATION_CACHE[abs_path] = (mtime, size, duration)
            return duration
    except asyncio.TimeoutError:
        try:
            process.terminate()
            await process.wait()
        except ProcessLookupError:
            pass
        logger.debug(f"Timeout getting duration for {audio_path}")
    except asyncio.CancelledError:
        try:
            process.terminate()
            await process.wait()
        except ProcessLookupError:
            pass
        raise
    except (ValueError, OSError) as e:
        logger.debug(f"Could not get duration for {audio_path}: {e}")

    return 0.0


# Backward compatibility alias
get_audio_duration_async = get_audio_duration


def validate_audio_file(audio_path: str) -> bool:
    """Validate that a file is a readable audio file.

    Args:
        audio_path: Path to audio file to validate

    Returns:
        True if file appears to be valid audio, False otherwise
    """
    if not os.path.exists(audio_path):
        return False

    try:
        # Use ffprobe to validate the file
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=format_name", audio_path],
            capture_output=True,
            timeout=5,
        )

        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return False
