import logging
import tempfile
from typing import Any, Optional

from ..base import TTSProvider
from ..exceptions import AudioPlaybackError, DependencyError, ProviderError
from ..internal.audio_utils import convert_with_cleanup, parse_bool_param
from ..internal.types import ProviderInfo
from ..voice_manager import VoiceManager


class ChatterboxProvider(TTSProvider):
    def __init__(self) -> None:
        self.tts = None
        self.logger = logging.getLogger(__name__)

    def _lazy_load(self) -> None:
        if self.tts is None:
            try:
                from chatterbox.tts import ChatterboxTTS

                print("Loading Chatterbox (Resemble AI) model...")
                # Use GPU if available for much faster generation
                device = "cuda" if self._has_cuda() else "cpu"
                print(f"Using device: {device}")
                self.tts = ChatterboxTTS.from_pretrained(device=device)
                print("Chatterbox model loaded successfully.")

            except ImportError:
                raise DependencyError(
                    "chatterbox dependencies not installed. Please install with: pip install goobits-matilda-voice[chatterbox]"
                ) from None
            except (RuntimeError, ValueError, MemoryError) as e:
                raise ProviderError(f"Failed to load Chatterbox model: {e}") from e

    def _has_cuda(self) -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except ImportError:
            # PyTorch not installed
            self.logger.debug("PyTorch not available, using CPU")
            return False
        except (RuntimeError, AttributeError) as e:
            # Unexpected error checking CUDA
            self.logger.warning(f"Error checking CUDA availability: {e}")
            return False

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        # Extract options
        stream = parse_bool_param(kwargs.get("stream"), False)
        audio_prompt_path = kwargs.get("voice")  # Optional voice cloning
        exaggeration = float(kwargs.get("exaggeration", "0.5"))
        cfg_weight = float(kwargs.get("cfg_weight", "0.5"))
        temperature = float(kwargs.get("temperature", "0.8"))
        min_p = float(kwargs.get("min_p", "0.05"))
        output_format = kwargs.get("output_format", "wav")

        # Check if we can use loaded voice via server
        if audio_prompt_path:
            voice_manager = VoiceManager()
            if voice_manager.is_voice_loaded(audio_prompt_path):
                try:
                    print("⚡ Using loaded voice")
                    # Use server for synthesis
                    audio_data = voice_manager.synthesize_with_loaded_voice(
                        text,
                        audio_prompt_path,
                        exaggeration=exaggeration,
                        cfg_weight=cfg_weight,
                        temperature=temperature,
                        min_p=min_p,
                    )

                    if stream:
                        # Stream the returned audio data
                        self._stream_audio_data(audio_data)
                    else:
                        # Save audio data to file
                        if output_path is not None:
                            self._save_audio_data(audio_data, output_path, output_format)
                    return

                except (ConnectionError, OSError, ValueError) as e:
                    self.logger.warning(f"Server synthesis failed, falling back to direct: {e}")
                    # Fall through to direct synthesis

        # Fallback to direct synthesis (legacy behavior)
        self._lazy_load()

        # Generate speech with optimized settings for speed
        if self.tts is None:
            raise ProviderError("Chatterbox TTS model not loaded")

        if audio_prompt_path:
            # Voice cloning mode
            wav = self.tts.generate(
                text,
                audio_prompt_path=audio_prompt_path,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
                temperature=temperature,
                min_p=min_p,
            )
        else:
            # Default voice with speed optimizations
            wav = self.tts.generate(
                text, exaggeration=exaggeration, cfg_weight=cfg_weight, temperature=temperature, min_p=min_p
            )

        if stream:
            # Stream to speakers
            self._stream_to_speakers(wav)
        else:
            # Save to file
            if output_format == "wav":
                import torchaudio as ta

                if self.tts is not None and output_path is not None:
                    ta.save(output_path, wav, self.tts.sr)
            else:
                # Convert to other formats using ffmpeg
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    wav_path = tmp.name

                import torchaudio as ta

                if self.tts is not None:
                    ta.save(wav_path, wav, self.tts.sr)

                # Convert using utility function with cleanup
                if output_path is not None:
                    convert_with_cleanup(wav_path, output_path, output_format)

    def _stream_to_speakers(self, wav_tensor: Any) -> None:
        """Stream audio tensor directly to speakers using ffplay"""
        import io
        import wave

        import numpy as np

        from ..internal.audio_utils import StreamingPlayer

        try:
            self.logger.debug("Converting audio tensor for streaming")
            # Convert tensor to numpy and ensure it's on CPU
            audio_data = wav_tensor.cpu().numpy().squeeze()

            # Create an in-memory WAV file
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.tts.sr if self.tts is not None else 22050)  # Use model's sample rate
                # Normalize and convert to 16-bit PCM
                audio_normalized = np.clip(audio_data, -1.0, 1.0)
                audio_16bit = (audio_normalized * 32767 * 0.95).astype(np.int16)
                wav_file.writeframes(audio_16bit.tobytes())

            # Stream to ffplay using StreamingPlayer
            buffer.seek(0)
            player = StreamingPlayer(provider_name="Chatterbox")
            # Create a generator that yields the buffer content as a single chunk
            player.play_chunks(iter([buffer.getvalue()]))

            self.logger.debug("Audio streaming completed")

        except (ValueError, RuntimeError, MemoryError) as e:
            self.logger.error(f"Unexpected audio streaming error: {type(e).__name__}: {e}")
            raise AudioPlaybackError(f"Audio streaming failed unexpectedly: {type(e).__name__}: {e}") from e

    def _stream_audio_data(self, audio_data: bytes) -> None:
        """Stream raw audio data to speakers using ffplay"""
        from ..internal.audio_utils import StreamingPlayer

        try:
            self.logger.debug("Streaming server audio data")

            # Stream using StreamingPlayer
            player = StreamingPlayer(provider_name="Chatterbox")
            player.play_chunks(iter([audio_data]))

            self.logger.debug("Audio streaming completed")

        except (ValueError, RuntimeError, MemoryError) as e:
            self.logger.error(f"Unexpected audio streaming error: {type(e).__name__}: {e}")
            raise AudioPlaybackError(f"Audio streaming failed unexpectedly: {type(e).__name__}: {e}") from e

    def _save_audio_data(self, audio_data: bytes, output_path: str, output_format: str) -> None:
        """Save raw audio data to file with optional format conversion"""
        try:
            if output_format == "wav":
                # Direct save for WAV
                with open(output_path, "wb") as f:
                    f.write(audio_data)
            else:
                # Convert to other formats using ffmpeg
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(audio_data)
                    wav_path = tmp.name

                # Convert using utility function with cleanup
                convert_with_cleanup(wav_path, output_path, output_format)

        except (IOError, OSError, ValueError) as e:
            self.logger.error(f"Failed to save audio data: {e}")
            raise ProviderError(f"Failed to save audio: {e}") from e

    def get_info(self) -> Optional[ProviderInfo]:
        # Scan for available voice files in the voices directory
        sample_voices = []
        from pathlib import Path

        voices_dir = Path.cwd() / "voices"
        if voices_dir.exists():
            for voice_file in voices_dir.glob("*.wav"):
                sample_voices.append(str(voice_file))

        return {
            "name": "Chatterbox (Resemble AI)",
            "description": "State-of-the-art zero-shot TTS with voice cloning and emotion control",
            "sample_voices": sample_voices,
            "options": {
                "voice": "Path to reference audio file for voice cloning (optional)",
                "exaggeration": "Emotion/intensity control (0.0-1.0, default: 0.5)",
                "cfg_weight": "Speech pacing control (0.1-1.0, default: 0.5)",
                "stream": "Stream directly to speakers instead of saving to file (true/false)",
            },
            "output_format": "WAV 22kHz",
            "model": "Resemble AI Chatterbox (0.5B parameters)",
        }
