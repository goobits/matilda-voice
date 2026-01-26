"""Voice analysis utilities for the Voice browser.

This module provides functions for analyzing voice names to extract
quality, region, and gender information.
"""

import re
from typing import Tuple

# Gender detection constants
_FEMALE_INDICATORS = [
    "emily",
    "jenny",
    "aria",
    "davis",
    "jane",
    "sarah",
    "amy",
    "emma",
    "female",
    "woman",
    "libby",
    "clara",
    "natasha",
]

_MALE_INDICATORS = [
    "guy",
    "tony",
    "brandon",
    "christopher",
    "eric",
    "male",
    "man",
    "boy"
]

# Words that commonly appear in other words and need boundary checks
_PROBLEMATIC_WORDS = {"man", "eric"}

# Pre-compiled regexes for problematic words
_PROBLEMATIC_REGEXES = {
    word: re.compile(r"\b" + re.escape(word) + r"\b")
    for word in _PROBLEMATIC_WORDS
}


def analyze_voice(provider: str, voice: str) -> Tuple[int, str, str]:
    """Analyze a voice name to extract quality, region, and gender information.

    Args:
        provider: The Voice provider name (e.g., 'edge_tts', 'openai')
        voice: The voice name to analyze

    Returns:
        Tuple of (quality, region, gender) where:
        - quality: 1 (low), 2 (medium), or 3 (high)
        - region: Geographic region (e.g., 'American', 'British', 'Irish')
        - gender: 'F' (female), 'M' (male), or 'U' (unknown)
    """
    voice_lower = voice.lower()

    # Quality heuristics
    quality = 2  # Default medium
    if "neural" in voice_lower or "premium" in voice_lower or "standard" in voice_lower:
        quality = 3  # High quality
    elif "basic" in voice_lower or "low" in voice_lower:
        quality = 1  # Low quality

    # Region detection
    region = "General"
    if any(marker in voice for marker in ["en-IE", "Irish"]):
        region = "Irish"
    elif any(marker in voice for marker in ["en-GB", "en-UK", "British"]):
        region = "British"
    elif any(marker in voice for marker in ["en-US", "American"]):
        region = "American"
    elif any(marker in voice for marker in ["en-AU", "Australian"]):
        region = "Australian"
    elif any(marker in voice for marker in ["en-CA", "Canadian"]):
        region = "Canadian"
    elif any(marker in voice for marker in ["en-IN", "Indian"]):
        region = "Indian"
    elif provider == "chatterbox":
        region = "Chatterbox"

    # Gender detection
    gender = "U"  # Unknown

    # Check for gender indicators with smart boundary detection
    # Use word boundaries for problematic short words, partial matches for names

    for indicator in _FEMALE_INDICATORS:
        if indicator in _PROBLEMATIC_WORDS:
            # Use word boundaries for problematic words
            if _PROBLEMATIC_REGEXES[indicator].search(voice_lower):
                gender = "F"
                break
        else:
            # Allow partial matches for names (e.g., "jenny" in "jennyneural")
            if indicator in voice_lower:
                gender = "F"
                break

    if gender == "U":  # Only check male if not already female
        for indicator in _MALE_INDICATORS:
            if indicator in _PROBLEMATIC_WORDS:
                # Use word boundaries for problematic words
                if _PROBLEMATIC_REGEXES[indicator].search(voice_lower):
                    gender = "M"
                    break
            else:
                # Allow partial matches for names
                if indicator in voice_lower:
                    gender = "M"
                    break

    return quality, region, gender


__all__ = ["analyze_voice"]
