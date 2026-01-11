SAMPLE_VOICES = {
    "ar-EG-SalmaNeural": "Arabic (Egypt) - Salma",
    "de-DE-KatjaNeural": "German (Germany) - Katja",
    "en-AU-NatashaNeural": "English (Australia) - Natasha",
    "en-GB-LibbyNeural": "English (UK) - Libby",
    "en-IN-NeerjaNeural": "English (India) - Neerja",
    "en-US-AriaNeural": "English (US) - Aria",
    "en-US-EmmaMultilingualNeural": "English (US) - Emma Multilingual",
    "en-US-GuyNeural": "English (US) - Guy",
    "es-ES-ElviraNeural": "Spanish (Spain) - Elvira",
    "es-MX-DaliaNeural": "Spanish (Mexico) - Dalia",
    "fr-FR-DeniseNeural": "French (France) - Denise",
    "hi-IN-SwaraNeural": "Hindi (India) - Swara",
    "it-IT-ElsaNeural": "Italian (Italy) - Elsa",
    "ja-JP-NanamiNeural": "Japanese (Japan) - Nanami",
    "ko-KR-SunHiNeural": "Korean (Korea) - SunHi",
    "pt-BR-FranciscaNeural": "Portuguese (Brazil) - Francisca",
    "pt-PT-RaquelNeural": "Portuguese (Portugal) - Raquel",
    "ru-RU-SvetlanaNeural": "Russian (Russia) - Svetlana",
    "sv-SE-SofieNeural": "Swedish (Sweden) - Sofie",
    "tr-TR-EmelNeural": "Turkish (Turkey) - Emel",
    "zh-CN-XiaoxiaoNeural": "Chinese (Mandarin) - Xiaoxiao",
    "zh-HK-HiuMaanNeural": "Chinese (Cantonese) - HiuMaan",
}

DEFAULT_VOICE = "en-US-EmmaMultilingualNeural"


def get_sample_voices() -> list[str]:
    return list(SAMPLE_VOICES.keys())


def get_voice_descriptions() -> dict[str, str]:
    return SAMPLE_VOICES.copy()


def normalize_voice_name(voice: str) -> str:
    if ":" in voice:
        _, voice_name = voice.split(":", 1)
        return voice_name
    return voice


def is_known_voice(voice: str) -> bool:
    return normalize_voice_name(voice) in SAMPLE_VOICES
