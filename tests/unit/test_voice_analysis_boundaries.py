"""Tests for voice analysis boundary conditions.

This module provides specific tests for the optimized voice analysis logic,
focusing on boundary detection for problematic words like "man" and "eric".
"""

from matilda_voice.voice_browser import analyze_voice

def test_problematic_word_boundaries():
    """Test that problematic words respect word boundaries."""

    # "man" should match standalone "man"
    _, _, gender = analyze_voice("provider", "spider-man-voice")
    assert gender == "M", "Should match 'man' with boundaries"

    # "man" should NOT match inside "superman" if it's not a boundary
    # Wait, 'superman' contains 'man' but not as a word.
    # The regex is \bman\b.
    # In "superman", "man" is preceded by "r", which is a word character. So \b matches there? No.
    # \b matches between \w and \W (non-word char), or start/end of string.
    # "superman": s-u-p-e-r-m-a-n. No boundary before m.
    # So "superman" should NOT match "man".

    _, _, gender = analyze_voice("provider", "superman-voice")
    # "superman" is not in male_indicators. "man" is in male_indicators but is problematic.
    # So it should NOT match.
    assert gender == "U", "'superman' should not match 'man'"

    # "eric" should match standalone "eric"
    _, _, gender = analyze_voice("provider", "voice-eric-neural")
    assert gender == "M", "Should match 'eric' with boundaries"

    # "eric" should NOT match inside "generic"
    _, _, gender = analyze_voice("provider", "generic-voice")
    # "generic" is not in indicators. "eric" is in indicators but problematic.
    assert gender == "U", "'generic' should not match 'eric'"

def test_problematic_word_start_end():
    """Test problematic words at start/end of string."""

    # Start of string
    _, _, gender = analyze_voice("provider", "man-voice")
    assert gender == "M", "Should match 'man' at start"

    # End of string
    _, _, gender = analyze_voice("provider", "voice-man")
    assert gender == "M", "Should match 'man' at end"

    # Exact match
    _, _, gender = analyze_voice("provider", "man")
    assert gender == "M", "Should match 'man' exact"

def test_non_problematic_matches():
    """Test that non-problematic words still match partially."""

    # "jenny" is NOT problematic.
    # "jenny" should match inside "jennyneural" (no boundary needed)
    _, _, gender = analyze_voice("provider", "en-US-JennyNeural")
    assert gender == "F", "Should match 'jenny' inside 'JennyNeural'"
