import logging
import os
import subprocess
import tempfile
from typing import Any, Optional

from ..base import TTSProvider
from ..exceptions import ProviderError
from ..internal.audio_utils import convert_audio, parse_bool_param
from ..internal.types import ProviderInfo


class SystemTTSProvider(TTSProvider):
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.available_engines = self._detect_available_engines()

    def _detect_available_engines(self) -> list[str]:
        engines = []

        try:
            subprocess.run(["espeak", "--version"], capture_output=True, check=True)
            engines.append("espeak")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        try:
            subprocess.run(["festival", "--version"], capture_output=True, check=True)
            engines.append("festival")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        try:
            subprocess.run(["say", "-v", "?"], capture_output=True, check=True)
            engines.append("say")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return engines

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        stream = parse_bool_param(kwargs.get("stream"), False)
        output_format = kwargs.get("output_format", "wav")
        voice = kwargs.get("voice")
        emotion = kwargs.get("emotion", "normal")

        if not self.available_engines:
            raise ProviderError("No system TTS engines available")

        engine = self._select_engine(stream)
        if not engine:
            raise ProviderError("No system TTS engines available for requested output")

        if stream:
            self._speak(engine, text, emotion, voice)
            return

        if output_path is None:
            raise ValueError("output_path is required when not streaming")

        self._speak_to_file(engine, text, emotion, voice, output_path, output_format)

    def get_info(self) -> Optional[ProviderInfo]:
        return {
            "name": "System TTS",
            "description": "Local system TTS engines (espeak, festival, say)",
            "sample_voices": [],
            "capabilities": ["local", "streaming", "file_output"],
            "options": {
                "voice": "Voice name (engine-specific)",
                "emotion": "Emotion hint (normal, excited, soft, monotone)",
                "stream": "Stream directly to speakers instead of saving to file (true/false)",
            },
        }

    def _select_engine(self, stream: bool) -> Optional[str]:
        if stream:
            return self.available_engines[0] if self.available_engines else None

        for engine in self.available_engines:
            if engine in ("espeak", "say"):
                return engine

        return None

    def _speak(self, engine: str, text: str, emotion: str, voice: Optional[str]) -> None:
        if engine == "espeak":
            self._run_espeak(text, emotion, voice, None)
            return
        if engine == "festival":
            self._run_festival(text)
            return
        if engine == "say":
            self._run_say(text, emotion, voice, None)
            return
        raise ProviderError(f"Unknown system TTS engine '{engine}'")

    def _speak_to_file(
        self,
        engine: str,
        text: str,
        emotion: str,
        voice: Optional[str],
        output_path: str,
        output_format: str,
    ) -> None:
        if engine == "espeak":
            if output_format == "wav":
                self._run_espeak(text, emotion, voice, output_path)
                return

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_path = tmp_file.name
            try:
                self._run_espeak(text, emotion, voice, tmp_path)
                convert_audio(tmp_path, output_path, output_format)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            return

        if engine == "say":
            self._run_say(text, emotion, voice, output_path)
            return

        raise ProviderError(f"System TTS engine '{engine}' does not support file output")

    def _run_espeak(
        self,
        text: str,
        emotion: str,
        voice: Optional[str],
        output_path: Optional[str],
    ) -> None:
        cmd = ["espeak"]

        if voice:
            cmd.extend(["-v", voice])

        if emotion == "excited":
            cmd.extend(["-p", "60", "-s", "180"])
        elif emotion == "soft":
            cmd.extend(["-p", "30", "-s", "120"])
        elif emotion == "monotone":
            cmd.extend(["-p", "40", "-s", "150"])
        else:
            cmd.extend(["-p", "50", "-s", "160"])

        if output_path:
            cmd.extend(["-w", output_path])

        cmd.append(text)

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise ProviderError("espeak synthesis failed")

    def _run_festival(self, text: str) -> None:
        result = subprocess.run(["festival", "--tts"], input=text, text=True, capture_output=True)
        if result.returncode != 0:
            raise ProviderError("festival synthesis failed")

    def _run_say(self, text: str, emotion: str, voice: Optional[str], output_path: Optional[str]) -> None:
        cmd = ["say"]

        if voice:
            cmd.extend(["-v", voice])
        elif emotion == "excited":
            cmd.extend(["-v", "Samantha"])
        elif emotion == "soft":
            cmd.extend(["-v", "Whisper"])
        elif emotion == "monotone":
            cmd.extend(["-v", "Ralph"])

        rate = "160"
        if emotion == "excited":
            rate = "200"
        elif emotion == "soft":
            rate = "120"
        elif emotion == "monotone":
            rate = "150"

        cmd.extend(["-r", rate])

        if output_path:
            cmd.extend(["-o", output_path])

        cmd.append(text)

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise ProviderError("say synthesis failed")
