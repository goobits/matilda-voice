"""Azure Cognitive Services TTS provider implementation."""

import logging
import os
import re
import tempfile
from typing import Any, List, Optional
from xml.sax.saxutils import escape as xml_escape

import httpx

from ..base import TTSProvider
from ..exceptions import AuthenticationError, ConfigurationError, NetworkError, ProviderError, map_http_error
from ..internal.audio_utils import (
    StreamingPlayer,
    check_audio_environment,
    convert_audio,
    parse_bool_param,
    stream_via_tempfile,
)
from ..internal.config import get_config_value, get_setting
from ..speech_synthesis.ssml.utils import is_ssml
from ..internal.http_retry import request_with_retry
from ..internal.types import ProviderInfo
from .microsoft_voices import DEFAULT_VOICE, get_sample_voices, get_voice_descriptions, normalize_voice_name


class AzureTTSProvider(TTSProvider):
    """Azure Cognitive Services TTS provider with full SSML support."""

    OUTPUT_FORMATS = {
        "mp3": "audio-16khz-32kbitrate-mono-mp3",
        "wav": "riff-16khz-16bit-mono-pcm",
    }

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._voices_cache: Optional[List[str]] = None

    def _get_api_key_optional(self) -> Optional[str]:
        key = get_setting("azure_api_key")
        if key:
            return str(key)
        env_keys = ["AZURE_API_KEY", "AZURE_SPEECH_KEY", "AZURE_TTS_KEY"]
        for env_key in env_keys:
            value = os.environ.get(env_key)
            if value:
                return value
        return None

    def _get_api_key(self) -> str:
        api_key = self._get_api_key_optional()
        if not api_key:
            raise AuthenticationError("Azure API key not found. Set with: voice config set azure_api_key YOUR_KEY")
        return api_key

    def _get_region_optional(self) -> Optional[str]:
        region = get_setting("azure_region")
        if region:
            return str(region)
        env_keys = ["AZURE_REGION", "AZURE_SPEECH_REGION", "AZURE_TTS_REGION"]
        for env_key in env_keys:
            value = os.environ.get(env_key)
            if value:
                return value
        return None

    def _get_endpoint_optional(self) -> Optional[str]:
        endpoint = get_setting("azure_endpoint")
        if endpoint:
            return str(endpoint).rstrip("/")
        env_keys = ["AZURE_ENDPOINT", "AZURE_SPEECH_ENDPOINT", "AZURE_TTS_ENDPOINT"]
        for env_key in env_keys:
            value = os.environ.get(env_key)
            if value:
                return value.rstrip("/")
        region = self._get_region_optional()
        if region:
            return f"https://{region}.tts.speech.microsoft.com"
        return None

    def _get_endpoint(self) -> str:
        endpoint = self._get_endpoint_optional()
        if not endpoint:
            raise ConfigurationError("Azure region/endpoint not set. Use azure_region or azure_endpoint.")
        return endpoint

    def _build_url(self, endpoint: str, path: str) -> str:
        return f"{endpoint}/{path.lstrip('/')}"

    def _normalize_voice(self, voice: Optional[str]) -> str:
        if voice:
            return normalize_voice_name(voice)
        return get_config_value("default_voice", DEFAULT_VOICE)

    def _extract_language_code(self, voice_name: str) -> str:
        parts = voice_name.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
        return "en-US"

    def _format_rate(self, rate: Optional[str]) -> Optional[str]:
        if not rate:
            return None
        if rate in ("0%", "+0%", "-0%"):
            return None
        if re.match(r"^[+-]?\d+%$", rate):
            return rate
        if rate in {"x-slow", "slow", "medium", "fast", "x-fast", "default"}:
            return rate
        self.logger.warning(f"Unsupported Azure rate value '{rate}', ignoring")
        return None

    def _format_pitch(self, pitch: Optional[str]) -> Optional[str]:
        if not pitch:
            return None
        if pitch in ("0%", "+0%", "-0%"):
            return None
        if re.match(r"^[+-]?\d+%$", pitch):
            return pitch
        if pitch in {"x-low", "low", "medium", "high", "x-high", "default"}:
            return pitch
        self.logger.warning(f"Unsupported Azure pitch value '{pitch}', ignoring")
        return None

    def _wrap_prosody(self, content: str, rate: Optional[str], pitch: Optional[str]) -> str:
        attrs = []
        if rate:
            attrs.append(f'rate="{rate}"')
        if pitch:
            attrs.append(f'pitch="{pitch}"')
        if not attrs:
            return content
        return f"<prosody {' '.join(attrs)}>{content}</prosody>"

    def _ensure_voice_tag(self, ssml: str, voice_name: str) -> str:
        if "<voice" in ssml:
            return ssml
        match = re.search(r"<speak[^>]*>", ssml)
        if not match or "</speak>" not in ssml:
            lang = self._extract_language_code(voice_name)
            return (
                f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
                f'<voice name="{voice_name}">{ssml}</voice></speak>'
            )
        start = match.group(0)
        inner = ssml[match.end() :]
        inner_content = inner.rsplit("</speak>", 1)[0]
        return f'{start}<voice name="{voice_name}">{inner_content}</voice></speak>'

    def _apply_prosody(self, ssml: str, rate: Optional[str], pitch: Optional[str]) -> str:
        attrs = []
        if rate:
            attrs.append(f'rate="{rate}"')
        if pitch:
            attrs.append(f'pitch="{pitch}"')
        if not attrs:
            return ssml
        open_tag = f"<prosody {' '.join(attrs)}>"
        ssml = re.sub(r"(<voice[^>]*>)", r"\1" + open_tag, ssml, count=1)
        ssml = re.sub(r"(</voice>)", r"</prosody>\1", ssml, count=1)
        return ssml

    def _prepare_ssml(self, text: str, voice_name: str, rate: Optional[str], pitch: Optional[str]) -> str:
        valid_rate = self._format_rate(rate)
        valid_pitch = self._format_pitch(pitch)

        if is_ssml(text):
            ssml = self._ensure_voice_tag(text, voice_name)
            return self._apply_prosody(ssml, valid_rate, valid_pitch)

        lang = self._extract_language_code(voice_name)
        safe_text = xml_escape(text)
        safe_text = self._wrap_prosody(safe_text, valid_rate, valid_pitch)
        return (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
            f'<voice name="{voice_name}">{safe_text}</voice></speak>'
        )

    def _request_audio(self, ssml: str, output_format: str) -> httpx.Response:
        api_key = self._get_api_key()
        endpoint = self._get_endpoint()
        url = self._build_url(endpoint, "/cognitiveservices/v1")

        headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": self.OUTPUT_FORMATS.get(output_format, self.OUTPUT_FORMATS["mp3"]),
        }

        return request_with_retry(
            "POST",
            url,
            headers=headers,
            content=ssml.encode("utf-8"),
            idempotent=False,
            provider_name="Azure TTS",
        )

    def _synthesize_to_file(self, text: str, output_path: str, **kwargs: Any) -> None:
        voice_name = self._normalize_voice(kwargs.get("voice"))
        rate = kwargs.get("rate")
        pitch = kwargs.get("pitch")
        output_format = kwargs.get("output_format", get_config_value("default_output_format")).lower()
        ssml = self._prepare_ssml(text, voice_name, rate, pitch)

        response = self._request_audio(ssml, output_format)
        if response.status_code != 200:
            raise map_http_error(response.status_code, response.text, "Azure TTS")

        if output_format in self.OUTPUT_FORMATS:
            with open(output_path, "wb") as output_file:
                output_file.write(response.content)
            return

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(response.content)
        convert_audio(tmp_path, output_path, output_format)
        os.unlink(tmp_path)

    def _stream_realtime(self, text: str, voice: Optional[str], rate: Optional[str], pitch: Optional[str]) -> None:
        audio_env = check_audio_environment()
        if not audio_env["available"]:
            return self._stream_via_tempfile(text, voice, rate, pitch)

        voice_name = self._normalize_voice(voice)
        ssml = self._prepare_ssml(text, voice_name, rate, pitch)
        response = self._request_audio(ssml, "mp3")
        if response.status_code != 200:
            raise map_http_error(response.status_code, response.text, "Azure TTS")

        player = StreamingPlayer(provider_name="Azure TTS", format_args=["-f", "mp3"])
        player.play_chunks(response.iter_bytes(chunk_size=get_config_value("http_streaming_chunk_size")))

    def _stream_via_tempfile(self, text: str, voice: Optional[str], rate: Optional[str], pitch: Optional[str]) -> None:
        stream_via_tempfile(
            synthesize_func=self._synthesize_to_file,
            text=text,
            logger=self.logger,
            file_suffix=".mp3",
            voice=voice,
            rate=rate,
            pitch=pitch,
            output_format="mp3",
        )

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        voice = kwargs.get("voice")
        rate = kwargs.get("rate", get_config_value("default_rate"))
        pitch = kwargs.get("pitch", get_config_value("default_pitch"))
        stream = parse_bool_param(kwargs.get("stream"), False)
        output_format = kwargs.get("output_format", get_config_value("default_output_format")).lower()

        try:
            if stream:
                self._stream_realtime(text, voice, rate, pitch)
            else:
                if output_path is None:
                    raise ValueError("output_path is required when not streaming")
                self._synthesize_to_file(
                    text, output_path, voice=voice, rate=rate, pitch=pitch, output_format=output_format
                )
        except (NetworkError, AuthenticationError, ProviderError, ConfigurationError):
            raise
        except (httpx.RequestError, OSError, ValueError, RuntimeError) as e:
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["network", "connection", "timeout", "dns"]):
                raise NetworkError(f"Azure TTS request failed: {e}") from e
            raise ProviderError(f"Azure TTS synthesis failed: {e}") from e

    def _get_all_voices(self) -> List[str]:
        if self._voices_cache is not None:
            return self._voices_cache

        api_key = self._get_api_key_optional()
        endpoint = self._get_endpoint_optional()
        if not api_key or not endpoint:
            self._voices_cache = get_sample_voices()
            return self._voices_cache

        url = self._build_url(endpoint, "/cognitiveservices/voices/list")
        headers = {"Ocp-Apim-Subscription-Key": api_key}

        try:
            response = request_with_retry("GET", url, headers=headers, provider_name="Azure TTS")
            if response.status_code != 200:
                self.logger.warning(f"Azure voice list request failed: HTTP {response.status_code}")
                self._voices_cache = get_sample_voices()
                return self._voices_cache
            data = response.json()
            self._voices_cache = [voice["ShortName"] for voice in data if "ShortName" in voice]
            return self._voices_cache
        except (ValueError, KeyError, httpx.RequestError) as e:
            self.logger.warning(f"Failed to fetch Azure voices: {e}")
            self._voices_cache = get_sample_voices()
            return self._voices_cache

    def get_info(self) -> ProviderInfo:
        api_key = self._get_api_key_optional()
        endpoint = self._get_endpoint_optional()

        if api_key and endpoint:
            api_status = "✅ Configured"
        elif not api_key:
            api_status = "❌ API key not set"
        else:
            api_status = "❌ Region/endpoint not set"

        all_voices = self._get_all_voices()
        voice_count = len(all_voices) if all_voices else len(get_sample_voices())

        return {
            "name": "Azure Cognitive Services",
            "description": f"Microsoft Azure TTS with {voice_count}+ neural voices and full SSML support",
            "api_status": api_status,
            "sample_voices": get_sample_voices(),
            "all_voices": all_voices,
            "voice_descriptions": get_voice_descriptions(),
            "options": {
                "voice": f"Voice to use (default: {get_config_value('default_voice')})",
                "rate": "Speech rate adjustment (e.g., +20%, slow)",
                "pitch": "Pitch adjustment (e.g., +10%, high)",
                "stream": "Stream directly to speakers instead of saving to file (true/false)",
            },
            "features": {
                "ssml_support": True,
                "voice_cloning": False,
                "languages": "Multiple languages",
                "quality": "Neural voices",
            },
            "pricing": "Azure Cognitive Services pricing",
            "output_format": "MP3 or WAV (converted to other formats via ffmpeg)",
        }
