import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from ..base import TTSProvider
from ..exceptions import DependencyError, NetworkError, ProviderError
from ..internal.audio_utils import (
    StreamPlayer,
    check_audio_environment,
    convert_with_cleanup,
    parse_bool_param,
    stream_via_tempfile,
)
from ..internal.config import get_config_value
from ..internal.types import ProviderInfo


class EdgeTTSProvider(TTSProvider):
    def __init__(self) -> None:
        self.edge_tts: Optional[Any] = None
        self.logger = logging.getLogger(__name__)
        self._executor = ThreadPoolExecutor(
            max_workers=get_config_value("thread_pool_max_workers"), thread_name_prefix="edge_tts"
        )

    def _lazy_load(self) -> None:
        if self.edge_tts is None:
            try:
                import edge_tts  # type: ignore

                self.edge_tts = edge_tts
            except ImportError:
                raise DependencyError("edge-tts not installed. Please install with: pip install edge-tts") from None

    def _run_async_safely(self, coro: Any) -> Any:
        """Safely run async coroutine, handling existing event loops."""
        try:
            # Try to get current event loop
            asyncio.get_running_loop()
            # If we're already in an event loop, run in thread pool
            return self._executor.submit(asyncio.run, coro).result()
        except RuntimeError:
            # No event loop running, safe to create new one
            try:
                return asyncio.run(coro)
            except KeyboardInterrupt:
                # Clean shutdown on Ctrl+C - propagate without logging
                raise
            except BrokenPipeError:
                # Silently ignore broken pipe when stdout/stdin is closed
                self.logger.debug("Broken pipe error - output stream was closed")
                return None
        except KeyboardInterrupt:
            # Clean shutdown on Ctrl+C - propagate without logging
            raise
        except BrokenPipeError:
            # Silently ignore broken pipe errors
            self.logger.debug("Broken pipe error in async handler")
            return None

    async def _synthesize_async(
        self, text: str, output_path: str, voice: str, rate: str, pitch: str, output_format: str = "mp3"
    ) -> None:
        try:
            self.logger.debug(f"Creating Edge TTS communication with voice: {voice}")
            if self.edge_tts is None:
                raise ProviderError("Edge TTS module not loaded")
            communicate = self.edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)

            if output_format == "mp3":
                self.logger.debug(f"Saving MP3 directly to {output_path}")
                await communicate.save(output_path)
            else:
                # For other formats, save as MP3 first then convert
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    mp3_path = tmp.name

                self.logger.debug(f"Saving MP3 to temporary file: {mp3_path}")
                await communicate.save(mp3_path)

                # Convert using utility function with cleanup
                convert_with_cleanup(mp3_path, output_path, output_format)
        except ConnectionError as e:
            self.logger.error(f"Network connection error during Edge TTS synthesis: {e}")
            raise NetworkError(f"Edge TTS connection failed: {e}. Check your internet connection and try again.") from e
        except OSError as e:
            self.logger.error(f"File system error during Edge TTS synthesis: {e}")
            raise ProviderError(f"Edge TTS file operation failed: {e}") from e
        except (RuntimeError, ValueError, AttributeError) as e:
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["internet", "network", "connection", "dns", "timeout"]):
                self.logger.error(f"Network-related error during Edge TTS synthesis: {e}")
                raise NetworkError(f"Edge TTS network error: {e}. Check your internet connection and try again.") from e
            else:
                self.logger.error(f"Edge TTS synthesis failed with unexpected error: {type(e).__name__}: {e}")
                raise ProviderError(f"Edge TTS synthesis failed: {type(e).__name__}: {e}") from e

    async def _stream_async(self, text: str, voice: str, rate: str, pitch: str) -> None:
        """Stream TTS audio directly to speakers without saving to file."""
        self.logger.debug(f"Starting Edge TTS streaming with voice: {voice}")
        if self.edge_tts is None:
            raise ProviderError("Edge TTS module not loaded")

        # Check for audio environment first
        audio_env = check_audio_environment()
        if not audio_env["available"]:
            self.logger.warning(f"Audio streaming not available: {audio_env['reason']}")
            return await self._stream_via_tempfile(text, voice, rate, pitch)

        try:
            communicate = self.edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)

            # Use StreamPlayer for unified streaming logic
            player = StreamPlayer(
                provider_name="Edge TTS",
                pulse_available=audio_env.get("pulse_available", False),
            )

            # Use transform to extract data from EdgeTTS chunk dicts
            # Chunk format: {'type': 'audio', 'data': bytes}
            await player.play_async(
                communicate.stream(), transform=lambda chunk: chunk["data"] if chunk.get("type") == "audio" else None
            )

        except KeyboardInterrupt:
            raise
        except (ConnectionError, OSError, RuntimeError, ValueError) as e:
            error_str = str(e).lower()
            if "internet" in error_str or "network" in error_str or "connection" in error_str:
                self.logger.error(f"Network error during Edge TTS streaming: {e}")
                raise NetworkError("Edge TTS requires internet connection. Check your network and try again.") from e
            else:
                self.logger.error(f"Edge TTS streaming failed: {e}")
                raise ProviderError(f"Edge TTS streaming failed: {e}") from e

    async def _stream_via_tempfile(self, text: str, voice: str, rate: str, pitch: str) -> None:
        """Fallback streaming method using temporary file when direct streaming fails"""

        # Use the shared utility with async wrapper
        def sync_synthesize(text: str, output_path: str, **kwargs: Any) -> None:
            # Run async synthesis in sync context using proper event loop handling
            self._run_async_safely(
                self._synthesize_async(text, output_path, kwargs["voice"], kwargs["rate"], kwargs["pitch"], "mp3")
            )

        stream_via_tempfile(
            synthesize_func=sync_synthesize,
            text=text,
            logger=self.logger,
            file_suffix=".mp3",
            voice=voice,
            rate=rate,
            pitch=pitch,
        )

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        self._lazy_load()

        # Extract provider-specific options
        voice = kwargs.get("voice", get_config_value("default_voice"))
        rate = kwargs.get("rate", get_config_value("default_rate"))
        pitch = kwargs.get("pitch", get_config_value("default_pitch"))
        stream = parse_bool_param(kwargs.get("stream"), False)
        output_format = kwargs.get("output_format", get_config_value("default_output_format"))

        # Format rate and pitch
        if not rate.endswith("%"):
            rate = f"+{rate}%" if not rate.startswith(("+", "-")) else f"{rate}%"
        if not pitch.endswith("Hz"):
            pitch = f"+{pitch}Hz" if not pitch.startswith(("+", "-")) else f"{pitch}Hz"

        # Stream or save based on option
        if stream:
            self._run_async_safely(self._stream_async(text, voice, rate, pitch))
        else:
            if output_path is None:
                raise ValueError("output_path is required when not streaming")
            self._run_async_safely(self._synthesize_async(text, output_path, voice, rate, pitch, output_format))

    def get_info(self) -> Optional[ProviderInfo]:
        self._lazy_load()

        # Get available voices
        voices = []
        try:

            async def get_voices() -> Any:
                if self.edge_tts is None:
                    raise ProviderError("Edge TTS module not loaded")
                return await self.edge_tts.list_voices()

            voice_list = self._run_async_safely(get_voices())
            voices = [v["ShortName"] for v in voice_list]
        except (ImportError, RuntimeError, OSError) as e:
            # Network issues, asyncio problems, or edge-tts import failures
            self.logger.warning(f"Could not fetch voice list from Edge TTS: {e}")
            voices = ["en-US-JennyNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"]
        except (AttributeError, TypeError, ValueError) as e:
            # Unexpected errors
            self.logger.error(f"Unexpected error fetching Edge TTS voices: {e}")
            voices = ["en-US-JennyNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"]

        result: ProviderInfo = {
            "name": "Edge TTS",
            "description": "Free Microsoft Edge text-to-speech",
            "options": {
                "voice": f"Voice name (default: {get_config_value('default_voice')})",
                "rate": "Speech rate adjustment (e.g., +20%, -10%)",
                "pitch": "Pitch adjustment (e.g., +5Hz, -10Hz)",
                "stream": "Stream directly to speakers instead of saving to file (true/false)",
            },
            "output_formats": ["MP3"],
            "sample_voices": voices if voices else [],
        }
        return result
