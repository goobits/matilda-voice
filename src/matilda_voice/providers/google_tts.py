"""Google Cloud TTS provider implementation."""

import base64
import logging
import tempfile
from typing import Any, List, Optional

import httpx

from ..base import TTSProvider
from ..exceptions import (
    AuthenticationError,
    DependencyError,
    NetworkError,
    ProviderError,
    QuotaError,
    map_http_error,
)
from ..internal.audio_utils import convert_audio, stream_audio_file
from ..internal.config import get_api_key, get_config_value
from ..internal.http_retry import request_with_retry
from ..internal.types import ProviderInfo
from ..speech_synthesis.ssml.utils import is_ssml


class GoogleTTSProvider(TTSProvider):
    """Google Cloud TTS provider with 380+ voices and full SSML support."""

    # Sample voices (a subset of available voices)
    SAMPLE_VOICES = {
        "en-US-Neural2-A": "US English, Neural2, Female",
        "en-US-Neural2-C": "US English, Neural2, Female",
        "en-US-Neural2-D": "US English, Neural2, Male",
        "en-US-Neural2-F": "US English, Neural2, Female",
        "en-US-Neural2-G": "US English, Neural2, Female",
        "en-US-Neural2-H": "US English, Neural2, Female",
        "en-US-Neural2-I": "US English, Neural2, Male",
        "en-US-Neural2-J": "US English, Neural2, Male",
        "en-GB-Neural2-A": "UK English, Neural2, Female",
        "en-GB-Neural2-B": "UK English, Neural2, Male",
        "en-GB-Neural2-C": "UK English, Neural2, Female",
        "en-AU-Neural2-A": "Australian English, Neural2, Female",
        "en-AU-Neural2-B": "Australian English, Neural2, Male",
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._voices_cache: Optional[List[str]] = None
        self.base_url = "https://texttospeech.googleapis.com/v1"
        self._client: Optional[Any] = None
        self._auth_method: Optional[str] = None

    def _get_client(self) -> Any:
        """Get Google Cloud TTS client, supporting both API key and service account auth."""
        if self._client is None:
            api_key = get_api_key("google")
            if not api_key:
                raise AuthenticationError(
                    "Google Cloud API key not found. Set with: voice config google_api_key YOUR_KEY"
                )

            # Determine authentication method
            if api_key.startswith("AIza"):
                # API key authentication - use REST API
                self._auth_method = "api_key"
                self._client = None  # Will use requests directly
            elif api_key.startswith("{"):
                # Service account JSON string
                try:
                    import json

                    from google.cloud import texttospeech

                    credentials_info = json.loads(api_key)
                    self._client = texttospeech.TextToSpeechClient.from_service_account_info(credentials_info)
                    self._auth_method = "service_account"
                except ImportError:
                    raise DependencyError(
                        "Google Cloud TTS library not installed. Install with: pip install goobits-matilda-voice[google]"
                    ) from None
                except json.JSONDecodeError as e:
                    raise ProviderError(f"Invalid service account JSON: {e}") from e
            elif len(api_key) > get_config_value("google_service_account_json_min_length", 100):
                # Assume it's a service account JSON string without braces
                try:
                    import json

                    from google.cloud import texttospeech

                    credentials_info = json.loads("{" + api_key + "}")
                    self._client = texttospeech.TextToSpeechClient.from_service_account_info(credentials_info)
                    self._auth_method = "service_account"
                except ImportError:
                    raise DependencyError(
                        "Google Cloud TTS library not installed. Install with: pip install goobits-matilda-voice[google]"
                    ) from None
                except json.JSONDecodeError as e:
                    raise ProviderError(f"Invalid service account JSON: {e}") from e
            else:
                # Unknown format, assume API key
                self._auth_method = "api_key"
                self._client = None

        return self._client

    def _make_request(
        self,
        method: str,
        endpoint: str,
        idempotent: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make authenticated request to Google Cloud TTS REST API with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/text:synthesize")
            idempotent: If False, only retry on connection errors to avoid duplicate charges.
                       Set to False for synthesis endpoints.
            **kwargs: Additional arguments passed to httpx.request

        Returns:
            httpx.Response object
        """
        api_key = get_api_key("google")
        if not api_key:
            raise AuthenticationError("Google Cloud API key not found. Set with: voice config google_api_key YOUR_KEY")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        params = {"key": api_key}

        # Merge params if provided in kwargs
        if "params" in kwargs:
            params.update(kwargs.pop("params"))

        return request_with_retry(
            method,
            url,
            params=params,
            idempotent=idempotent,
            provider_name="Google Cloud TTS",
            **kwargs,
        )

    def get_info(self) -> ProviderInfo:
        """Get provider information and capabilities."""
        api_key = get_api_key("google")

        if not api_key:
            api_status = "❌ No API key"
            auth_method = "None"
        elif api_key.startswith("AIza"):
            api_status = "✅ Configured (API Key)"
            auth_method = "API Key"
        elif api_key.startswith("{") or len(api_key) > get_config_value("google_service_account_json_min_length", 100):
            api_status = "✅ Configured (Service Account)"
            auth_method = "Service Account"
        else:
            api_status = "✅ Configured (API Key)"
            auth_method = "API Key"

        if not api_key:
            all_voices = list(self.SAMPLE_VOICES.keys())
            voice_count = len(all_voices)
        else:
            all_voices = self._get_all_voices()
            voice_count = len(all_voices) if all_voices else 380
            if not all_voices:
                all_voices = list(self.SAMPLE_VOICES.keys())

        return {
            "name": "Google Cloud TTS",
            "description": f"Enterprise-grade TTS with {voice_count}+ voices and full SSML support",
            "api_status": api_status,
            "auth_method": auth_method,
            "sample_voices": list(self.SAMPLE_VOICES.keys()),
            "all_voices": all_voices,
            "voice_descriptions": self.SAMPLE_VOICES,
            "options": {
                "voice": "Voice to use (e.g., en-US-Neural2-A)",
                "speaking_rate": "Speaking rate (0.25-4.0, default: 1.0)",
                "pitch": "Pitch adjustment (-20.0 to 20.0, default: 0.0)",
                "stream": "Stream directly to speakers instead of saving to file (true/false)",
            },
            "features": {
                "ssml_support": True,
                "voice_cloning": False,
                "languages": "40+ languages",
                "quality": "Highest (Neural2, WaveNet, Standard voices)",
            },
            "pricing": "$4 per 1M characters (WaveNet/Neural2), $0.4/1M (Standard)",
            "output_format": "WAV 16kHz (converted to other formats via ffmpeg)",
        }

    def _get_all_voices(self) -> List[str]:
        """Fetch all available voices from Google Cloud TTS API."""
        if self._voices_cache is not None:
            return self._voices_cache

        try:
            client = self._get_client()

            if self._auth_method == "service_account" and client:
                # Use Google Cloud client library
                response = client.list_voices()
                voices = []
                for voice in response.voices:
                    voices.append(voice.name)
                self._voices_cache = voices
                self.logger.info(f"Fetched {len(voices)} Google voices via service account")
            else:
                # Use REST API with API key
                response = self._make_request("GET", "/voices")

                if response.status_code == 200:
                    data = response.json()
                    voices = []
                    for voice in data.get("voices", []):
                        voices.append(voice["name"])
                    self._voices_cache = voices
                    self.logger.info(f"Fetched {len(voices)} Google voices via API key")
                else:
                    self.logger.warning(f"Failed to fetch voices: HTTP {response.status_code}")
                    self._voices_cache = []
        except (httpx.RequestError, ValueError, KeyError) as e:
            self.logger.warning(f"Failed to fetch Google voices: {e}")
            self._voices_cache = []

        return self._voices_cache

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        """Synthesize speech using Google Cloud TTS API with both auth methods."""
        # Extract options
        voice = kwargs.get("voice", "en-US-Neural2-A")  # Default voice
        stream = kwargs.get("stream", "false").lower() in ("true", "1", "yes")
        output_format = kwargs.get("output_format", "wav")
        speaking_rate = float(kwargs.get("speaking_rate", "1.0"))
        pitch = float(kwargs.get("pitch", "0.0"))

        # Auto-detect SSML
        use_ssml = is_ssml(text)

        # Parse voice name
        if ":" in voice:
            # Format like "google:en-US-Neural2-A"
            _, voice_name = voice.split(":", 1)
        else:
            voice_name = voice

        # Extract language code from voice name (e.g., "en-US-Neural2-A" -> "en-US")
        parts = voice_name.split("-")
        if len(parts) >= 2:
            language_code = f"{parts[0]}-{parts[1]}"
        else:
            language_code = "en-US"
            self.logger.warning(f"Could not parse language from voice '{voice_name}', using en-US")

        self.logger.info(f"Generating speech with Google voice '{voice_name}'")
        if use_ssml:
            self.logger.info("Using SSML input")

        try:
            client = self._get_client()

            if self._auth_method == "service_account" and client:
                # Use Google Cloud client library for service account
                from google.cloud import texttospeech

                # Prepare synthesis input
                if use_ssml:
                    synthesis_input = texttospeech.SynthesisInput(ssml=text)
                else:
                    synthesis_input = texttospeech.SynthesisInput(text=text)

                voice_selection = texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name)

                audio_config = texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV format
                    speaking_rate=speaking_rate,
                    pitch=pitch,
                )

                # Perform synthesis
                response = client.synthesize_speech(
                    input=synthesis_input, voice=voice_selection, audio_config=audio_config
                )

                audio_content = response.audio_content
                self.logger.info("Synthesis completed via service account")

            else:
                # Use REST API with API key
                payload = {
                    "input": {"ssml" if use_ssml else "text": text},
                    "voice": {"languageCode": language_code, "name": voice_name},
                    "audioConfig": {
                        "audioEncoding": "LINEAR16",  # WAV format
                        "speakingRate": speaking_rate,
                        "pitch": pitch,
                    },
                }

                response = self._make_request(
                    "POST",
                    "/text:synthesize",
                    idempotent=False,  # Synthesis creates new audio, don't retry on HTTP errors
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code != 200:
                    # Use standardized HTTP error mapping
                    try:
                        error_detail = response.json()
                        if "error" in error_detail:
                            detail_text = error_detail["error"].get("message", "Unknown error")
                        else:
                            detail_text = "Unknown error"
                    except (ValueError, KeyError, AttributeError):
                        # JSON parsing failed or missing expected keys
                        detail_text = response.text

                    raise map_http_error(response.status_code, detail_text, "Google Cloud TTS")

                # Get audio content from response
                response_data = response.json()
                audio_content = base64.b64decode(response_data["audioContent"])
                self.logger.info("Synthesis completed via API key")

            # Save audio content to temporary file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_path = tmp_file.name
                tmp_file.write(audio_content)

            if stream:
                # Stream the audio
                stream_audio_file(tmp_path)
                # Clean up temp file
                import os

                os.unlink(tmp_path)
            else:
                # Convert and save to final output path
                if output_path is not None:
                    if output_format.lower() != "wav":
                        convert_audio(tmp_path, output_path, output_format)
                        # Clean up temp file
                        import os

                        os.unlink(tmp_path)
                    else:
                        # For WAV, just move the file
                        import shutil

                        shutil.move(tmp_path, output_path)

        except httpx.RequestError as e:
            error_str = str(e).lower()
            if "authentication" in error_str or "api_key" in error_str or "credentials" in error_str:
                raise AuthenticationError(f"Google Cloud authentication failed: {e}") from e
            elif "quota" in error_str or "billing" in error_str:
                raise QuotaError(f"Google Cloud quota/billing issue: {e}") from e
            else:
                raise NetworkError(f"Google Cloud TTS request failed: {e}") from e
        except (ImportError, IOError, OSError, ValueError, RuntimeError) as e:
            error_str = str(e).lower()
            if "authentication" in error_str or "api_key" in error_str or "credentials" in error_str:
                raise AuthenticationError(f"Google Cloud authentication failed: {e}") from e
            elif "quota" in error_str or "billing" in error_str:
                raise QuotaError(f"Google Cloud quota/billing issue: {e}") from e
            else:
                raise ProviderError(f"Google TTS synthesis failed: {e}") from e
