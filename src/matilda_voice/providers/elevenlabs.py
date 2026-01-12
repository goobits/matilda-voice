"""ElevenLabs TTS provider implementation with voice cloning support."""

import logging
import tempfile
from typing import Any, Dict, List, Optional, cast

import httpx

from ..base import TTSProvider
from ..exceptions import (
    AuthenticationError,
    NetworkError,
    ProviderError,
    VoiceNotFoundError,
    classify_and_raise,
    map_http_error,
)
from ..internal.audio_utils import (
    StreamingPlayer,
    check_audio_environment,
    convert_audio,
    parse_bool_param,
    stream_via_tempfile,
)
from ..internal.config import get_api_key, get_config_value
from ..internal.http_retry import request_with_retry, stream_with_retry
from ..internal.types import ProviderInfo
from ..speech_synthesis.ssml.utils import is_ssml, strip_ssml_tags


class ElevenLabsProvider(TTSProvider):
    """ElevenLabs TTS provider with premium voice cloning and custom voices."""

    # Default ElevenLabs voices (these are always available)
    DEFAULT_VOICES = {
        "rachel": "Calm and soothing female voice",
        "domi": "Strong and confident female voice",
        "bella": "Warm and engaging female voice",
        "antoni": "Well-rounded male voice",
        "elli": "Emotional and dynamic female voice",
        "josh": "Deep and authoritative male voice",
        "arnold": "Crisp and commanding male voice",
        "adam": "Professional and clear male voice",
        "sam": "Natural and conversational male voice",
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._voices_cache: Optional[List[Dict[str, Any]]] = None
        self.base_url = "https://api.elevenlabs.io/v1"

    def _make_request(
        self,
        method: str,
        endpoint: str,
        idempotent: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make authenticated request to ElevenLabs API with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/voices")
            idempotent: If False, only retry on connection errors to avoid duplicate charges.
                       Set to False for synthesis endpoints.
            **kwargs: Additional arguments passed to httpx.request

        Returns:
            httpx.Response object
        """
        api_key = get_api_key("elevenlabs")
        if not api_key:
            raise AuthenticationError(
                "ElevenLabs API key not found. Set with: voice config elevenlabs_api_key YOUR_KEY"
            )

        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

        # Merge headers if provided in kwargs
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        return request_with_retry(
            method,
            url,
            headers=headers,
            idempotent=idempotent,
            provider_name="ElevenLabs",
            **kwargs,
        )

    def _get_available_voices(self) -> List[Dict[str, Any]]:
        """Get list of all available voices from ElevenLabs."""
        if self._voices_cache is None:
            try:
                response = self._make_request("GET", "/voices")

                if response.status_code == 200:
                    data = response.json()
                    voices = []

                    for voice in data.get("voices", []):
                        voice_info = {
                            "voice_id": voice["voice_id"],
                            "name": voice["name"],
                            "category": voice.get("category", "generated"),
                            "description": voice.get("description", "Custom voice"),
                            "gender": voice.get("labels", {}).get("gender", "unknown"),
                            "age": voice.get("labels", {}).get("age", "unknown"),
                        }
                        voices.append(voice_info)

                    self._voices_cache = voices
                else:
                    self.logger.warning(f"Failed to fetch ElevenLabs voices: {response.status_code}")
                    self._voices_cache = []

            except (httpx.RequestError, ValueError, KeyError) as e:
                self.logger.warning(f"Failed to fetch ElevenLabs voices: {e}")
                self._voices_cache = []

        return self._voices_cache

    def _get_voice_id(self, voice_name: str) -> Optional[str]:
        """Get voice ID from voice name."""
        # Check if it's already a voice ID (32 char hex string)
        voice_id_length = get_config_value("elevenlabs_voice_id_length")
        is_hex = all(c in "0123456789abcdef" for c in voice_name.lower())
        if len(voice_name) == voice_id_length and is_hex:
            return voice_name

        # Search in available voices
        voices = self._get_available_voices()
        for voice in voices:
            if voice["name"].lower() == voice_name.lower():
                return str(voice["voice_id"])

        # Fallback to default voices (these have well-known IDs)
        voice_id_map = {
            "rachel": "21m00Tcm4TlvDq8ikWAM",
            "domi": "AZnzlk1XvdvUeBnXmlld",
            "bella": "EXAVITQu4vr4xnSDxMaL",
            "antoni": "ErXwobaYiN019PkySvjV",
            "elli": "MF3mGyEYCl7XYWbV9V6O",
            "josh": "TxGEqnHWrfWFMLpVQ3VQ",
            "arnold": "VR6AewLTigWG4xSOukaG",
            "adam": "pNInz6obpgDQGcFmaJgB",
            "sam": "yoZ06aMxZJJ28mfd3POQ",
        }

        return voice_id_map.get(voice_name.lower())

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        """Synthesize speech using ElevenLabs API."""
        # Extract options
        voice = kwargs.get("voice", "rachel")  # Default voice
        stream = parse_bool_param(kwargs.get("stream"), False)
        output_format = kwargs.get("output_format", "wav")
        stability = float(kwargs.get("stability", str(get_config_value("elevenlabs_default_stability"))))
        similarity_boost = float(
            kwargs.get("similarity_boost", str(get_config_value("elevenlabs_default_similarity_boost")))
        )
        style = float(kwargs.get("style", str(get_config_value("elevenlabs_default_style"))))

        # Handle SSML (ElevenLabs doesn't support SSML, so strip tags)
        if is_ssml(text):
            self.logger.warning("ElevenLabs doesn't support SSML. Converting to plain text.")
            text = strip_ssml_tags(text)

        # Parse voice name
        if ":" in voice:
            # Format like "elevenlabs:rachel"
            _, voice_name = voice.split(":", 1)
        else:
            voice_name = voice

        # Get voice ID
        voice_id = self._get_voice_id(voice_name)
        if not voice_id:
            raise VoiceNotFoundError(
                f"Voice '{voice_name}' not found. Use voice voices elevenlabs to see available voices."
            )

        try:
            if stream:
                # Use streaming method for real-time playback
                self._stream_realtime(text, voice_id, voice_name, stability, similarity_boost, style)
            else:
                # Use regular synthesis for file output
                # Prepare request payload
                payload = {
                    "text": text,
                    "model_id": "eleven_monolingual_v1",  # or "eleven_multilingual_v2"
                    "voice_settings": {"stability": stability, "similarity_boost": similarity_boost, "style": style},
                }

                self.logger.info(f"Generating speech with ElevenLabs voice '{voice_name}' (ID: {voice_id})")

                # Make synthesis request (idempotent=False to avoid duplicate charges)
                response = self._make_request("POST", f"/text-to-speech/{voice_id}", json=payload, idempotent=False)

                if response.status_code != 200:
                    # Use standardized HTTP error mapping
                    try:
                        error_detail = response.json().get("detail", {})
                        if isinstance(error_detail, dict):
                            detail_text = error_detail.get("message", "Unknown error")
                        else:
                            detail_text = str(error_detail)
                    except (ValueError, KeyError, AttributeError):
                        # JSON parsing failed or missing expected keys
                        detail_text = response.text

                    raise map_http_error(response.status_code, detail_text, "ElevenLabs")

                # Save audio content to temporary file
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                    tmp_path = tmp_file.name
                    tmp_file.write(response.content)

                # Convert to desired format if needed
                if output_format == "mp3":
                    # Direct save
                    if output_path is not None:
                        import shutil

                        shutil.move(tmp_path, output_path)
                else:
                    # Convert using ffmpeg
                    if output_path is not None:
                        convert_audio(tmp_path, output_path, output_format)
                    # Clean up temp file
                    import os

                    os.unlink(tmp_path)

        except httpx.RequestError as e:
            if "response" in locals():
                # Use standardized HTTP error mapping for request exceptions too
                raise map_http_error(response.status_code, str(e), "ElevenLabs") from e
            else:
                raise NetworkError(f"ElevenLabs network error: {e}") from e
        except (IOError, OSError, ValueError, RuntimeError) as e:
            raise ProviderError(f"ElevenLabs TTS synthesis failed: {e}") from e

    def _stream_realtime(
        self, text: str, voice_id: str, voice_name: str, stability: float, similarity_boost: float, style: float
    ) -> None:
        """Stream TTS audio in real-time with minimal latency."""
        self.logger.debug(f"Starting ElevenLabs TTS streaming with voice: {voice_name}")

        # Check for audio environment first
        audio_env = check_audio_environment()
        if not audio_env["available"]:
            self.logger.warning(f"Audio streaming not available: {audio_env['reason']}")
            return self._stream_via_tempfile(text, voice_id, voice_name, stability, similarity_boost, style)

        try:
            # Prepare request for streaming
            api_key = get_api_key("elevenlabs")
            if not api_key:
                raise ProviderError("ElevenLabs API key not found. Set with: voice config elevenlabs_api_key YOUR_KEY")

            headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
            payload = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {"stability": stability, "similarity_boost": similarity_boost, "style": style},
            }
            url = f"{self.base_url}/text-to-speech/{voice_id}/stream"

            # Make streaming request with httpx
            with stream_with_retry(
                "POST", url, headers=headers, json=payload, idempotent=False, provider_name="ElevenLabs"
            ) as response:
                if response.status_code != 200:
                    error_msg = f"ElevenLabs API error {response.status_code}"
                    try:
                        error_detail = response.json().get("detail", {})
                        if isinstance(error_detail, dict):
                            error_msg += f": {error_detail.get('message', 'Unknown error')}"
                        else:
                            error_msg += f": {error_detail}"
                    except (ValueError, KeyError, AttributeError):
                        error_msg += f": {response.text[:200]}"
                    raise ProviderError(error_msg)

                # Use StreamingPlayer for unified streaming logic
                player = StreamingPlayer(
                    provider_name="ElevenLabs",
                    format_args=["-f", "mp3"],
                )
                player.play(response.iter_bytes(chunk_size=get_config_value("http_streaming_chunk_size")))

        except (httpx.RequestError, ConnectionError, ValueError, RuntimeError) as e:
            self.logger.error(f"ElevenLabs TTS streaming failed: {e}")
            classify_and_raise(e, "ElevenLabs")

    def _stream_via_tempfile(
        self, text: str, voice_id: str, voice_name: str, stability: float, similarity_boost: float, style: float
    ) -> None:
        """Fallback streaming method using temporary file when direct streaming fails."""

        def synthesize_to_file(text: str, output_path: str, **kwargs: Any) -> None:
            payload = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": kwargs["stability"],
                    "similarity_boost": kwargs["similarity_boost"],
                    "style": kwargs["style"],
                },
            }

            response = self._make_request(
                "POST", f"/text-to-speech/{kwargs['voice_id']}", json=payload, idempotent=False
            )

            if response.status_code != 200:
                error_msg = f"ElevenLabs API error {response.status_code}: {response.text[:200]}"
                raise ProviderError(error_msg)

            with open(output_path, "wb") as f:
                f.write(response.content)

        stream_via_tempfile(
            synthesize_func=synthesize_to_file,
            text=text,
            logger=self.logger,
            file_suffix=".mp3",
            voice_id=voice_id,
            voice_name=voice_name,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
        )

    def get_info(self) -> Optional[ProviderInfo]:
        """Get provider information including available voices."""
        # Check if API key is configured
        api_key = get_api_key("elevenlabs")
        api_status = "✅ Configured" if api_key else "❌ API key not set"

        # Get voice information
        try:
            all_voices = self._get_available_voices()
            custom_voices = [v for v in all_voices if v.get("category") != "premade"]
            premade_voices = [v for v in all_voices if v.get("category") == "premade"]

            voice_list = [f"{v['name']} ({v.get('category', 'unknown')})" for v in all_voices[:15]]
            if len(all_voices) > 15:
                voice_list.append(f"... and {len(all_voices) - 15} more voices")

            # Get actual voice names for the browser
            voice_names = [v["name"] for v in all_voices]

        except (httpx.RequestError, ValueError, KeyError, AttributeError):
            voice_list = [f"{name}: {desc}" for name, desc in self.DEFAULT_VOICES.items()]
            voice_names = list(self.DEFAULT_VOICES.keys())
            custom_voices = []
            premade_voices = []

        return cast(
            ProviderInfo,
            {
                "name": "ElevenLabs",
                "description": (
                    f"Premium voice cloning with {len(all_voices) if 'all_voices' in locals() else '10+'} voices"
                ),
                "api_status": api_status,
                "sample_voices": list(self.DEFAULT_VOICES.keys()),
                "all_voices": voice_names if "voice_names" in locals() else list(self.DEFAULT_VOICES.keys()),
                "all_voices_display": (
                    voice_list
                    if "voice_list" in locals()
                    else [f"{name}: {desc}" for name, desc in self.DEFAULT_VOICES.items()]
                ),
                "voice_descriptions": self.DEFAULT_VOICES,
                "custom_voices": len(custom_voices) if custom_voices else "Unknown",
                "options": {
                    "voice": f"Voice to use (e.g., {list(self.DEFAULT_VOICES.keys())[0]})",
                    "stability": "Voice stability (0.0-1.0, default: 0.5)",
                    "similarity_boost": "Voice similarity boost (0.0-1.0, default: 0.5)",
                    "style": "Style exaggeration (0.0-1.0, default: 0.0)",
                    "stream": "Stream directly to speakers instead of saving to file (true/false)",
                },
                "features": {
                    "ssml_support": False,
                    "voice_cloning": True,
                    "languages": "Multiple languages",
                    "quality": "Premium (voice cloning available)",
                },
                "pricing": "Starting at $5/month (subscription required)",
                "output_format": "MP3 (converted to other formats via ffmpeg)",
            },
        )
