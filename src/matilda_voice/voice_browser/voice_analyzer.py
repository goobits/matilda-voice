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

_MALE_INDICATORS = ["guy", "tony", "brandon", "christopher", "eric", "male", "man", "boy"]

# Words that commonly appear in other words and need boundary checks
_PROBLEMATIC_WORDS = {"man", "eric"}


# Region constants
_REGION_MAP = {
    "en-IE": "Irish",
    "Irish": "Irish",
    "en-GB": "British",
    "en-UK": "British",
    "British": "British",
    "en-US": "American",
    "American": "American",
    "en-AU": "Australian",
    "Australian": "Australian",
    "en-CA": "Canadian",
    "Canadian": "Canadian",
    "en-IN": "Indian",
    "Indian": "Indian",
}

# Sort keys by length descending to ensure longer matches take precedence
# (e.g. if we had "en-US-East" and "en-US", we'd want to match "en-US-East" first if it maps to something specific)
_REGION_KEYS = sorted(_REGION_MAP.keys(), key=len, reverse=True)
_REGION_PATTERN = re.compile("|".join(re.escape(k) for k in _REGION_KEYS))


def _build_indicator_regex(indicators: list[str], problematic_words: set[str]) -> re.Pattern:
    """Build a combined regex pattern for indicators.

    Handles simple substrings and problematic words with boundaries.
    """
    # Sort by length descending to ensure longer matches take precedence
    sorted_indicators = sorted(indicators, key=len, reverse=True)

    parts = []
    for indicator in sorted_indicators:
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
# Note: Benchmarks show that keeping female/male patterns separate is faster (approx 30%)
# than combining them into a single regex with named groups.
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
    match = _REGION_PATTERN.search(voice)
    if match:
        region = _REGION_MAP[match.group(0)]
    elif provider == "chatterbox":
        region = "Chatterbox"

    # Gender detection
    gender = "U"  # Unknown

    # Check for gender indicators using optimized regex patterns
    # Using explicit checks against pre-compiled patterns to ensure performance
    if _FEMALE_PATTERN.search(voice_lower) is not None:
        gender = "F"
    elif _MALE_PATTERN.search(voice_lower) is not None:
        gender = "M"

    return quality, region, gender


__all__ = ["analyze_voice"]
