"""Voice analysis utilities for the Voice browser.

This module provides functions for analyzing voice names to extract
quality, region, and gender information.
"""

import re
from typing import List, Set, Tuple

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


def _build_indicator_regex(indicators: List[str], problematic_words: Set[str]) -> re.Pattern:
    """Build a combined regex pattern for indicators.

    Handles simple substrings and problematic words with boundaries.
    """
    parts = []
    for indicator in indicators:
        if indicator == "eric":
            # Allow "eric" at start of word, but don't require end boundary to match "ericneural"
            # However, we must ensure it doesn't match inside words like "generic" or "american"
            # \b ensures start boundary.
            parts.append(r"\b" + re.escape(indicator))
        elif indicator in problematic_words:
            # Use word boundaries for problematic words
            parts.append(r"\b" + re.escape(indicator) + r"\b")
        else:
            # Simple substring match
            parts.append(re.escape(indicator))

    return re.compile("|".join(parts))


# Pre-compiled combined patterns for performance
_FEMALE_PATTERN = _build_indicator_regex(_FEMALE_INDICATORS, _PROBLEMATIC_WORDS)
_MALE_PATTERN = _build_indicator_regex(_MALE_INDICATORS, _PROBLEMATIC_WORDS)


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

    # Check for gender indicators using optimized regex patterns
    if _FEMALE_PATTERN.search(voice_lower):
        gender = "F"
    elif _MALE_PATTERN.search(voice_lower):
        gender = "M"

    return quality, region, gender


__all__ = ["analyze_voice"]
