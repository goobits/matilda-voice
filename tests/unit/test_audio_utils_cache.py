
import pytest
import asyncio
from unittest.mock import patch, MagicMock
from matilda_voice.internal import audio_utils

def setup_function():
    # Reset cache before each test
    audio_utils._AUDIO_ENV_CACHE = None

def test_check_audio_environment_caching():
    """Test that check_audio_environment uses cache."""
    # We mock os.path.exists to return False for ALSA check to force subprocess.run
    with patch("os.path.exists", return_value=False):
        with patch("subprocess.run") as mock_run:
            # Mock successful result
            mock_run.return_value.returncode = 0

            # First call
            result1 = audio_utils.check_audio_environment()
            assert result1["available"] is True
            assert mock_run.call_count == 1

            # Second call - should use cache
            result2 = audio_utils.check_audio_environment()
            assert result2["available"] is True
            assert mock_run.call_count == 1 # Still 1

            # Third call with force_refresh
            result3 = audio_utils.check_audio_environment(force_refresh=True)
            assert result3["available"] is True
            assert mock_run.call_count == 2 # Incremented

@pytest.mark.asyncio
async def test_check_audio_environment_async_caching():
    """Test that check_audio_environment_async uses cache directly."""
    # Pre-populate cache
    audio_utils._AUDIO_ENV_CACHE = {"available": True, "reason": "Cached", "pulse_available": False, "alsa_available": False}

    with patch("matilda_voice.internal.audio_utils.check_audio_environment") as mock_sync_check:
        # Should return cached result without calling sync check via executor
        result = await audio_utils.check_audio_environment_async()

        assert result["reason"] == "Cached"
        assert not mock_sync_check.called

@pytest.mark.asyncio
async def test_check_audio_environment_async_populates_cache():
    """Test that check_audio_environment_async populates cache via sync call."""
    # Clear cache
    audio_utils._AUDIO_ENV_CACHE = None

    with patch("os.path.exists", return_value=False):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            # First call - goes to executor
            result = await audio_utils.check_audio_environment_async()
            assert result["available"] is True

            # Verify cache is populated
            assert audio_utils._AUDIO_ENV_CACHE is not None
            assert audio_utils._AUDIO_ENV_CACHE["available"] is True

            # Verify subsequent sync call uses cache
            with patch("subprocess.run") as mock_run_2:
                audio_utils.check_audio_environment()
                assert not mock_run_2.called
