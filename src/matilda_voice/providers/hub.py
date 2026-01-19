from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from matilda_transport import HubClient

from ..base import TTSProvider
from ..exceptions import ProviderError
from ..internal.audio_utils import parse_bool_param, stream_via_tempfile


class HubTTSProvider(TTSProvider):
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        stream = parse_bool_param(kwargs.get("stream"), False)
        output_format = kwargs.get("output_format", "wav")
        voice = kwargs.get("voice")

        if stream:
            stream_via_tempfile(
                self._synthesize_to_file,
                text,
                self.logger,
                file_suffix=f".{output_format}",
                voice=voice,
                output_format=output_format,
            )
            return

        if output_path is None:
            raise ProviderError("output_path is required when not streaming")
        self._synthesize_to_file(text, output_path, voice=voice, output_format=output_format)

    def _synthesize_to_file(self, text: str, output_path: str, **kwargs: Any) -> None:
        voice = kwargs.get("voice")
        output_format = kwargs.get("output_format", "wav")
        payload = {
            "text": text,
            "voice": voice,
            "format": output_format,
        }
        client = HubClient()
        response = client.post_capability("synthesize-speech", payload)
        error = response.get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise ProviderError(message or "hub request failed")
        result = response.get("result") or {}
        audio_b64 = result.get("audio")
        if not audio_b64:
            raise ProviderError("hub response missing audio payload")
        audio_bytes = base64.b64decode(audio_b64)
        with open(output_path, "wb") as audio_file:
            audio_file.write(audio_bytes)
