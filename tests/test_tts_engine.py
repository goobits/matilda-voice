"""Tests for the SystemTTSProvider class."""

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from matilda_voice.exceptions import ProviderError
from matilda_voice.providers.system import SystemTTSProvider


def make_provider(engines):
    with patch.object(SystemTTSProvider, "_detect_available_engines", return_value=engines):
        return SystemTTSProvider()


class TestSystemTTSProviderDetection:
    def test_init_detects_available_engines(self):
        with patch.object(SystemTTSProvider, "_detect_available_engines", return_value=["espeak", "festival"]):
            provider = SystemTTSProvider()

        assert provider.available_engines == ["espeak", "festival"]

    def test_detect_espeak_available(self):
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[0] == "espeak":
                    return MagicMock(returncode=0)
                raise subprocess.CalledProcessError(1, cmd)

            mock_run.side_effect = side_effect

            provider = SystemTTSProvider()
            assert provider.available_engines == ["espeak"]

    def test_detect_no_engines_available(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")

            provider = SystemTTSProvider()
            assert provider.available_engines == []

    def test_detect_handles_file_not_found(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("Command not found")

            provider = SystemTTSProvider()
            assert provider.available_engines == []

    def test_detect_multiple_engines_available(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            provider = SystemTTSProvider()
            assert set(provider.available_engines) == {"espeak", "festival", "say"}

            expected_calls = [
                call(["espeak", "--version"], capture_output=True, check=True),
                call(["festival", "--version"], capture_output=True, check=True),
                call(["say", "-v", "?"], capture_output=True, check=True),
            ]
            mock_run.assert_has_calls(expected_calls, any_order=True)


class TestSystemTTSProviderSynthesize:
    def test_synthesize_stream_no_engines_raises(self):
        provider = make_provider([])

        with pytest.raises(ProviderError, match="No system TTS engines available"):
            provider.synthesize("Hello", None, stream=True)

    def test_synthesize_stream_espeak_excited(self):
        provider = make_provider(["espeak"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            provider.synthesize("Test text", None, stream=True, emotion="excited")

            mock_run.assert_called_once_with(
                ["espeak", "-p", "60", "-s", "180", "Test text"], capture_output=True
            )

    def test_synthesize_stream_festival(self):
        provider = make_provider(["festival"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            provider.synthesize("Festival test", None, stream=True)

            mock_run.assert_called_once_with(
                ["festival", "--tts"], input="Festival test", text=True, capture_output=True
            )

    def test_synthesize_stream_say(self):
        provider = make_provider(["say"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            provider.synthesize("Normal speech", None, stream=True)

            mock_run.assert_called_once_with(["say", "-r", "160", "Normal speech"], capture_output=True)

    def test_synthesize_output_espeak_wav(self):
        provider = make_provider(["espeak"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            provider.synthesize("File output", "output.wav", stream=False, output_format="wav")

            mock_run.assert_called_once_with(
                ["espeak", "-p", "50", "-s", "160", "-w", "output.wav", "File output"], capture_output=True
            )

    def test_synthesize_output_say(self):
        provider = make_provider(["say"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            provider.synthesize("File output", "output.aiff", stream=False, output_format="aiff")

            mock_run.assert_called_once_with(
                ["say", "-r", "160", "-o", "output.aiff", "File output"], capture_output=True
            )

    def test_synthesize_output_prefers_supported_engine(self):
        provider = make_provider(["festival", "espeak"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            provider.synthesize("Output", "output.wav", stream=False, output_format="wav")

            assert mock_run.call_args[0][0][0] == "espeak"

    def test_synthesize_output_without_supported_engine_raises(self):
        provider = make_provider(["festival"])

        with pytest.raises(ProviderError, match="No system TTS engines available for requested output"):
            provider.synthesize("Output", "output.wav", stream=False, output_format="wav")

    def test_synthesize_subprocess_failure_raises(self):
        provider = make_provider(["espeak"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            with pytest.raises(ProviderError, match="espeak synthesis failed"):
                provider.synthesize("Failure", None, stream=True)
