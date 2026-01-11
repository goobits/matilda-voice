from typing import Any, Optional

from .core import TTSEngine, get_tts_engine, initialize_tts_engine
from .registry import PROVIDERS_REGISTRY


def get_engine() -> TTSEngine:
    try:
        return get_tts_engine()
    except RuntimeError:
        return initialize_tts_engine(PROVIDERS_REGISTRY)


def speak(text: str, *, voice: Optional[str] = None, provider: Optional[str] = None, **kwargs: Any) -> None:
    engine = get_engine()
    engine.synthesize_text(text=text, voice=voice, provider_name=provider, stream=True, **kwargs)


def save_audio(
    text: str,
    output_path: str,
    *,
    voice: Optional[str] = None,
    provider: Optional[str] = None,
    output_format: str = "wav",
    **kwargs: Any,
) -> Optional[str]:
    engine = get_engine()
    return engine.synthesize_text(
        text=text,
        output_path=output_path,
        voice=voice,
        provider_name=provider,
        stream=False,
        output_format=output_format,
        **kwargs,
    )
