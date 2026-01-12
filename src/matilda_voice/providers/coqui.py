"""Coqui TTS provider for high-quality local text-to-speech synthesis.

Coqui TTS (https://github.com/coqui-ai/TTS) provides:
- Multiple pre-trained models (XTTS, VITS, Tacotron2, etc.)
- Voice cloning from audio samples
- Multi-language support
- GPU acceleration with CUDA

This provider is recommended over chatterbox for better Python 3.11+ compatibility
and a more mature ecosystem with ongoing community maintenance.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

from ..base import TTSProvider
from ..exceptions import AudioPlaybackError, DependencyError, ProviderError
from ..internal.audio_utils import convert_with_cleanup, parse_bool_param
from ..internal.types import ProviderInfo


class CoquiProvider(TTSProvider):
    """Coqui TTS provider for local speech synthesis with voice cloning."""

    # Default model - XTTS v2 is the most capable for voice cloning
    DEFAULT_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

    def __init__(self) -> None:
        self.tts = None
        self.logger = logging.getLogger(__name__)
        self._model_name: str = self.DEFAULT_MODEL

    def _lazy_load(self, model_name: Optional[str] = None) -> None:
        """Lazily load the Coqui TTS model on first use."""
        target_model = model_name or self._model_name

        # Check if we need to reload with a different model
        if self.tts is not None and target_model == self._model_name:
            return

        try:
            from TTS.api import TTS  # type: ignore

            print(f"Loading Coqui TTS model: {target_model}...")

            # Use GPU if available
            device = "cuda" if self._has_cuda() else "cpu"
            print(f"Using device: {device}")

            self.tts = TTS(model_name=target_model).to(device)
            self._model_name = target_model

            print("Coqui TTS model loaded successfully.")

        except ImportError:
            raise DependencyError(
                "Coqui TTS dependencies not installed. Please install with: pip install goobits-matilda-voice[coqui]"
            ) from None
        except (RuntimeError, ValueError, MemoryError, OSError) as e:
            raise ProviderError(f"Failed to load Coqui TTS model: {e}") from e

    def _has_cuda(self) -> bool:
        """Check if CUDA is available for GPU acceleration."""
        try:
            import torch  # type: ignore

            return bool(torch.cuda.is_available())
        except ImportError:
            self.logger.debug("PyTorch not available, using CPU")
            return False
        except (RuntimeError, AttributeError) as e:
            self.logger.warning(f"Error checking CUDA availability: {e}")
            return False

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        """Synthesize speech from text using Coqui TTS.

        Args:
            text: Text to synthesize
            output_path: Path to save the audio file (optional if streaming)
            **kwargs: Additional options:
                - voice: Path to reference audio for voice cloning
                - model: Coqui TTS model name (default: xtts_v2)
                - language: Language code (default: en)
                - stream: Stream to speakers instead of saving
                - output_format: Output format (wav, mp3, etc.)
        """
        stream = parse_bool_param(kwargs.get("stream"), False)
        speaker_wav = kwargs.get("voice")  # Reference audio for cloning
        model = kwargs.get("model")
        language = kwargs.get("language", "en")
        output_format = kwargs.get("output_format", "wav")

        # Load model (lazy loading)
        self._lazy_load(model)

        if self.tts is None:
            raise ProviderError("Coqui TTS model not loaded")

        try:
            # Determine output path for synthesis
            if stream or output_path is None:
                # Use temp file for streaming
                tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                synthesis_path = tmp_file.name
                tmp_file.close()
            else:
                synthesis_path = output_path if output_format == "wav" else tempfile.mktemp(suffix=".wav")

            # Synthesize with appropriate method
            if speaker_wav and Path(speaker_wav).exists():
                # Voice cloning mode (XTTS supports this)
                if "xtts" in self._model_name.lower():
                    self.tts.tts_to_file(
                        text=text,
                        file_path=synthesis_path,
                        speaker_wav=speaker_wav,
                        language=language,
                    )
                else:
                    self.logger.warning("Voice cloning requires XTTS model; using default voice")
                    self.tts.tts_to_file(text=text, file_path=synthesis_path)
            else:
                # Standard synthesis
                if "xtts" in self._model_name.lower():
                    # XTTS requires language parameter
                    self.tts.tts_to_file(text=text, file_path=synthesis_path, language=language)
                else:
                    self.tts.tts_to_file(text=text, file_path=synthesis_path)

            if stream:
                # Stream to speakers
                self._stream_audio_file(synthesis_path)
                # Clean up temp file
                Path(synthesis_path).unlink(missing_ok=True)
            elif output_path and output_format != "wav":
                # Convert to requested format
                convert_with_cleanup(synthesis_path, output_path, output_format)

        except (IOError, OSError, RuntimeError) as e:
            self.logger.error(f"Synthesis failed: {e}")
            raise ProviderError(f"Coqui TTS synthesis failed: {e}") from e

    def _stream_audio_file(self, audio_path: str) -> None:
        """Stream an audio file to speakers using StreamingPlayer."""
        from ..internal.audio_utils import StreamingPlayer

        try:
            self.logger.debug(f"Streaming audio file: {audio_path}")

            with open(audio_path, "rb") as f:
                audio_data = f.read()

            player = StreamingPlayer(provider_name="Coqui")
            player.play(iter([audio_data]))

            self.logger.debug("Audio streaming completed")

        except (IOError, OSError, ValueError) as e:
            self.logger.error(f"Audio streaming error: {e}")
            raise AudioPlaybackError(f"Audio streaming failed: {e}") from e

    def get_info(self) -> Optional[ProviderInfo]:
        """Get provider information and capabilities."""
        # Scan for available voice files
        sample_voices: list[str] = []
        voices_dir = Path.cwd() / "voices"
        if voices_dir.exists():
            for voice_file in voices_dir.glob("*.wav"):
                sample_voices.append(str(voice_file))

        return {
            "name": "Coqui TTS",
            "description": "Open-source TTS with voice cloning, multi-language support, and GPU acceleration",
            "sample_voices": sample_voices,
            "options": {
                "voice": "Path to reference audio file for voice cloning (requires XTTS model)",
                "model": f"Coqui TTS model name (default: {self.DEFAULT_MODEL})",
                "language": "Language code for synthesis (default: en)",
                "stream": "Stream directly to speakers instead of saving to file (true/false)",
            },
            "output_format": "WAV 22kHz (convertible to other formats)",
            "model": self._model_name,
        }

    @staticmethod
    def list_available_models() -> list[str]:
        """List available Coqui TTS models."""
        try:
            from TTS.api import TTS  # type: ignore

            return TTS().list_models()
        except ImportError:
            return ["(Coqui TTS not installed)"]
        except (RuntimeError, AttributeError):
            return ["(Unable to list models)"]
