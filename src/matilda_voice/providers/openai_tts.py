"""OpenAI TTS provider implementation."""

import logging
import tempfile
from typing import Any, Optional, cast

from ..base import TTSProvider
from ..exceptions import (
    AuthenticationError,
    DependencyError,
    classify_and_raise,
)
from ..internal.audio_utils import (
    StreamingPlayer,
    check_audio_environment,
    convert_audio,
    parse_bool_param,
    stream_via_tempfile,
)
from ..internal.config import get_api_key, get_config_value
from ..internal.http_retry import call_with_retry
from ..internal.types import ProviderInfo
from ..speech_synthesis.ssml.utils import is_ssml, strip_ssml_tags


class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS API provider with 6 high-quality voices."""

    # Available OpenAI TTS voices
    VOICES = {
        "alloy": "Balanced and versatile voice",
        "echo": "Clear and articulate voice",
        "fable": "Warm and expressive voice",
        "nova": "Crisp and professional voice",
        "onyx": "Deep and authoritative voice",
        "shimmer": "Bright and energetic voice",
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._client: Any | None = None

    def _get_retry_exceptions(self) -> tuple[type[BaseException], ...]:
        """Return OpenAI-specific retryable exceptions if available."""
        retry_exceptions: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)
        try:
            from openai import APIConnectionError, APITimeoutError, RateLimitError

            retry_exceptions = retry_exceptions + (APIConnectionError, APITimeoutError, RateLimitError)
        except ImportError:
            pass
        return retry_exceptions

    def _get_client(self) -> Any:
        """Get OpenAI client, initializing if needed."""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise DependencyError("OpenAI library not installed. Install with: pip install openai") from None

            api_key = get_api_key("openai")
            if not api_key:
                raise AuthenticationError("OpenAI API key not found. Set with: voice config openai_api_key YOUR_KEY")

            self._client = OpenAI(api_key=api_key)

        return self._client

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        """Synthesize speech using OpenAI TTS API."""
        # Extract options
        voice = kwargs.get("voice", "nova")  # Default to nova voice
        stream = parse_bool_param(kwargs.get("stream"), False)
        output_format = kwargs.get("output_format", "wav")

        # Handle SSML (OpenAI doesn't support SSML, so strip tags)
        if is_ssml(text):
            self.logger.warning("OpenAI TTS doesn't support SSML. Converting to plain text.")
            text = strip_ssml_tags(text)

        # Validate voice
        if voice not in self.VOICES:
            self.logger.warning(f"Unknown OpenAI voice '{voice}', using 'nova'")
            voice = "nova"

        try:
            if stream:
                # Use streaming method for real-time playback
                self._stream_realtime(text, voice)
            else:
                # Use regular synthesis for file output
                if output_path is None:
                    raise ValueError("output_path is required when not streaming")
                client = self._get_client()

                # Generate speech
                self.logger.info(f"Generating speech with OpenAI voice '{voice}'")

                # OpenAI TTS API call
                response = call_with_retry(
                    lambda: client.audio.speech.create(
                        model="tts-1",  # or "tts-1-hd" for higher quality
                        voice=voice,
                        input=text,
                        response_format="mp3",  # OpenAI outputs MP3
                    ),
                    idempotent=False,
                    provider_name="OpenAI",
                    retry_on=self._get_retry_exceptions(),
                )

                # Save to temporary MP3 file first
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                    tmp_path = tmp_file.name
                    response.stream_to_file(tmp_path)

                # Convert to desired format if needed
                if output_format == "mp3":
                    # Direct save
                    import shutil

                    shutil.move(tmp_path, output_path)
                else:
                    # Convert using ffmpeg
                    convert_audio(tmp_path, output_path, output_format)
                    # Clean up temp file
                    import os

                    os.unlink(tmp_path)

        except ImportError:
            raise DependencyError(
                "OpenAI library not installed. Install with: pip install goobits-matilda-voice[openai]"
            ) from None
        except (ValueError, RuntimeError, AttributeError, TypeError) as e:
            classify_and_raise(e, "OpenAI")

    def _stream_realtime(self, text: str, voice: str) -> None:
        """Stream TTS audio in real-time with minimal latency."""
        self.logger.debug(f"Starting OpenAI TTS streaming with voice: {voice}")

        # Check for audio environment first
        audio_env = check_audio_environment()
        if not audio_env["available"]:
            self.logger.warning(f"Audio streaming not available: {audio_env['reason']}")
            return self._stream_via_tempfile(text, voice)

        try:
            client = self._get_client()

            # Create streaming response
            response = call_with_retry(
                lambda: client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=text,
                    response_format="mp3",
                ),
                idempotent=False,
                provider_name="OpenAI",
                retry_on=self._get_retry_exceptions(),
            )

            # Use StreamingPlayer for unified streaming logic
            player = StreamingPlayer(
                provider_name="OpenAI",
                format_args=["-f", "mp3"],
            )
            player.play_chunks(response.iter_bytes(chunk_size=get_config_value("http_streaming_chunk_size")))

        except (ConnectionError, ValueError, RuntimeError, AttributeError) as e:
            self.logger.error(f"OpenAI TTS streaming failed: {e}")
            classify_and_raise(e, "OpenAI")

    def _stream_via_tempfile(self, text: str, voice: str) -> None:
        """Fallback streaming method using temporary file when direct streaming fails."""

        def synthesize_to_file(text: str, output_path: str, **kwargs: Any) -> None:
            client = self._get_client()
            response = client.audio.speech.create(
                model="tts-1", voice=kwargs["voice"], input=text, response_format="mp3"
            )
            response.stream_to_file(output_path)

        stream_via_tempfile(
            synthesize_func=synthesize_to_file, text=text, logger=self.logger, file_suffix=".mp3", voice=voice
        )

    def get_info(self) -> Optional[ProviderInfo]:
        """Get provider information including available voices."""
        # Check if API key is configured
        api_key = get_api_key("openai")
        api_status = "✅ Configured" if api_key else "❌ API key not set"

        return cast(
            ProviderInfo,
            {
                "name": "OpenAI TTS",
                "description": "High-quality neural text-to-speech with 6 voices",
                "api_status": api_status,
                "sample_voices": list(self.VOICES.keys()),
                "all_voices": list(self.VOICES.keys()),  # Add all_voices for browser compatibility
                "voice_descriptions": self.VOICES,
                "options": {
                    "voice": f"Voice to use ({', '.join(self.VOICES.keys())})",
                    "stream": "Stream directly to speakers instead of saving to file (true/false)",
                },
                "features": {
                    "ssml_support": False,
                    "voice_cloning": False,
                    "languages": "Multiple (auto-detected)",
                    "quality": "High (tts-1 model)",
                },
                "pricing": "$15 per 1M characters",
                "output_format": "MP3 (converted to other formats via ffmpeg)",
            },
        )
