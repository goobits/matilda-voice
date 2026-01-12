"""
Comprehensive tests for TTS CLI configuration commands.

Tests all configuration-related CLI functionality including:
- config show/get/set operations
- Configuration validation and error handling
- Config file creation and persistence
- Real file I/O operations without external API dependencies
"""

import os
import tomllib
from unittest.mock import patch

from click.testing import CliRunner

from matilda_voice.cli import cli as cli


class TestConfigOperations:
    """Test config set/get operations."""

    def test_config_set_and_get_basic_key(self, unit_test_config):
        """Test setting and getting a basic configuration key."""
        runner = CliRunner()

        # Test setting a configuration value
        result = runner.invoke(cli, ["config", "set", "openai_api_key", "test_key_12345"])
        assert result.exit_code == 0
        assert "Set openai_api_key = test_key_12345" in result.output

        # Test getting the same configuration value
        result = runner.invoke(cli, ["config", "get", "openai_api_key", ""])
        assert result.exit_code == 0
        assert "test_key_12345" in result.output

    def test_config_set_and_get_voice(self, unit_test_config):
        """Test setting and getting voice configuration."""
        runner = CliRunner()

        # Test setting a voice
        result = runner.invoke(cli, ["config", "set", "voice", "edge_tts:en-US-AriaNeural"])
        assert result.exit_code == 0
        assert "Set voice = edge_tts:en-US-AriaNeural" in result.output

        # Test getting the voice
        result = runner.invoke(cli, ["config", "get", "voice", ""])
        assert result.exit_code == 0
        assert "edge_tts:en-US-AriaNeural" in result.output

    def test_config_set_multiple_keys(self, unit_test_config):
        """Test setting multiple configuration keys."""
        runner = CliRunner()

        # Set multiple keys (use -- for negative values to avoid Click option parsing)
        keys_values = [
            ("elevenlabs_api_key", "test_elevenlabs_key"),
            ("google_cloud_api_key", "test_google_key"),
            ("output_dir", "~/test_output"),
            ("rate", "+10%"),
        ]

        for key, value in keys_values:
            result = runner.invoke(cli, ["config", "set", key, value])
            assert result.exit_code == 0
            assert f"Set {key} = {value}" in result.output

        # Test negative pitch value with -- separator
        result = runner.invoke(cli, ["config", "set", "pitch", "--", "-5Hz"])
        assert result.exit_code == 0
        assert "Set pitch = -5Hz" in result.output

        # Verify all keys were set correctly
        for key, expected_value in keys_values:
            result = runner.invoke(cli, ["config", "get", key, ""])
            assert result.exit_code == 0
            assert expected_value in result.output

        # Verify pitch value was set correctly
        result = runner.invoke(cli, ["config", "get", "pitch", ""])
        assert result.exit_code == 0
        assert "-5Hz" in result.output

    def test_config_get_nonexistent_key(self, unit_test_config):
        """Test getting a key that doesn't exist."""
        runner = CliRunner()

        result = runner.invoke(cli, ["config", "get", "nonexistent_key", ""])
        assert result.exit_code == 0
        assert "Not set" in result.output

    def test_config_set_overwrites_existing_key(self, unit_test_config):
        """Test that setting an existing key overwrites the previous value."""
        runner = CliRunner()

        # Set initial value
        result = runner.invoke(cli, ["config", "set", "rate", "+5%"])
        assert result.exit_code == 0

        # Overwrite with new value
        result = runner.invoke(cli, ["config", "set", "rate", "+15%"])
        assert result.exit_code == 0
        assert "Set rate = +15%" in result.output

        # Verify new value
        result = runner.invoke(cli, ["config", "get", "rate", ""])
        assert result.exit_code == 0
        assert "+15%" in result.output
        assert "+5%" not in result.output


class TestConfigShow:
    """Test config show command."""

    def test_config_show_displays_current_config(self, unit_test_config):
        """Test that config show displays current configuration."""
        runner = CliRunner()

        # Set some config values first
        runner.invoke(cli, ["config", "set", "openai_api_key", "test_openai_key"])
        runner.invoke(cli, ["config", "set", "voice", "edge_tts:en-US-JennyNeural"])

        # Test config show
        result = runner.invoke(cli, ["config", "show", "", ""])
        assert result.exit_code == 0
        assert "🔧 Voice Configuration" in result.output
        assert "===================" in result.output

        # Should show our set values
        assert "test_openai_key" in result.output
        assert "edge_tts:en-US-JennyNeural" in result.output

    def test_config_show_without_action_argument(self, unit_test_config):
        """Test that config show action works.

        Note: The new CLI requires ACTION KEY VALUE arguments.
        """
        runner = CliRunner()

        # Set a test value
        runner.invoke(cli, ["config", "set", "rate", "+20%"])

        # Test config show with empty key and value
        result = runner.invoke(cli, ["config", "show", "", ""])
        assert result.exit_code == 0
        assert "🔧 Voice Configuration" in result.output
        assert "+20%" in result.output

    def test_config_show_with_empty_config(self, unit_test_config):
        """Test config show with minimal/default configuration."""
        runner = CliRunner()

        result = runner.invoke(cli, ["config", "show", "", ""])
        assert result.exit_code == 0
        assert "🔧 Voice Configuration" in result.output
        # Should show default values from the test config
        assert "en-US-AvaNeural" in result.output or "edge_tts" in result.output


class TestConfigValidation:
    """Test configuration validation and error handling.

    Note: The new CLI architecture uses positional arguments (ACTION KEY VALUE),
    so missing arguments result in Click's standard exit code 2.
    """

    def test_config_set_missing_key(self, unit_test_config):
        """Test config set with missing key argument."""
        runner = CliRunner()

        result = runner.invoke(cli, ["config", "set"])
        # Click returns exit code 2 for missing arguments
        assert result.exit_code == 2
        # Should show usage information
        assert "Usage" in result.output

    def test_config_set_missing_value(self, unit_test_config):
        """Test config set with missing value argument."""
        runner = CliRunner()

        result = runner.invoke(cli, ["config", "set", "openai_api_key"])
        # Click returns exit code 2 for missing arguments
        assert result.exit_code == 2
        # Should show usage information
        assert "Usage" in result.output

    def test_config_get_missing_key(self, unit_test_config):
        """Test config get with missing key argument."""
        runner = CliRunner()

        result = runner.invoke(cli, ["config", "get"])
        # Click returns exit code 2 for missing arguments
        assert result.exit_code == 2
        # Should show usage information
        assert "Usage" in result.output

    def test_config_invalid_action(self, unit_test_config):
        """Test config with invalid action."""
        runner = CliRunner()

        # The CLI definition limits actions to specific choices, so invalid actions
        # should be caught by Click before reaching our handler
        result = runner.invoke(cli, ["config", "invalid_action"])
        assert result.exit_code != 0  # Click should error on invalid choice


class TestConfigFilePersistence:
    """Test configuration file creation and persistence."""

    def test_config_creates_file_if_not_exists(self, unit_test_config):
        """Test that config operations create config file if it doesn't exist."""
        config_file = unit_test_config["config_file"]

        # Remove the config file to simulate first-time use
        if config_file.exists():
            config_file.unlink()

        runner = CliRunner()

        # Set a config value (should create the file)
        result = runner.invoke(cli, ["config", "set", "test_key", "test_value"])
        assert result.exit_code == 0

        # Verify file was created and contains our value
        assert config_file.exists()
        with open(config_file, "rb") as f:
            config_data = tomllib.load(f)
        assert config_data["voice"]["test_key"] == "test_value"

    def test_config_persists_across_commands(self, unit_test_config):
        """Test that configuration persists across different CLI invocations."""
        runner = CliRunner()

        # Set a value in first invocation
        result = runner.invoke(cli, ["config", "set", "persistent_key", "persistent_value"])
        assert result.exit_code == 0

        # Get the value in second invocation (simulates separate CLI run)
        result = runner.invoke(cli, ["config", "get", "persistent_key", ""])
        assert result.exit_code == 0
        assert "persistent_value" in result.output

    def test_config_preserves_existing_values(self, unit_test_config):
        """Test that setting new keys preserves existing configuration."""
        runner = CliRunner()

        # Set initial values
        runner.invoke(cli, ["config", "set", "key1", "value1"])
        runner.invoke(cli, ["config", "set", "key2", "value2"])

        # Set a third value
        runner.invoke(cli, ["config", "set", "key3", "value3"])

        # Verify all values are still present
        for key, expected_value in [("key1", "value1"), ("key2", "value2"), ("key3", "value3")]:
            result = runner.invoke(cli, ["config", "get", key, ""])
            assert result.exit_code == 0
            assert expected_value in result.output


class TestConfigSpecialKeys:
    """Test configuration with special keys and values."""

    def test_config_with_paths(self, unit_test_config):
        """Test configuration with file paths."""
        runner = CliRunner()

        test_paths = [
            "~/Downloads",
            "/tmp/tts_output",
            "./relative/path",
            "C:\\Windows\\path" if os.name == "nt" else "/usr/local/bin",
        ]

        for path in test_paths:
            result = runner.invoke(cli, ["config", "set", "output_dir", path])
            assert result.exit_code == 0

            result = runner.invoke(cli, ["config", "get", "output_dir", ""])
            assert result.exit_code == 0
            assert path in result.output

    def test_config_with_special_characters(self, unit_test_config):
        """Test configuration with special characters."""
        runner = CliRunner()

        special_values = [
            "key_with_spaces and symbols!@#$%",
            "unicode_test_ñáéíóú",
            'json_like_{"key": "value"}',
            "url_like_https://api.example.com/v1",
        ]

        for value in special_values:
            result = runner.invoke(cli, ["config", "set", "special_test", value])
            assert result.exit_code == 0

            result = runner.invoke(cli, ["config", "get", "special_test", ""])
            assert result.exit_code == 0
            assert value in result.output

    def test_config_with_voice_strings(self, unit_test_config):
        """Test configuration with various voice string formats."""
        runner = CliRunner()

        voice_strings = [
            "edge_tts:en-US-AriaNeural",
            "openai:alloy",
            "elevenlabs:Rachel",
            "google:en-US-Wavenet-D",
            "chatterbox:custom_voice.wav",
        ]

        for voice in voice_strings:
            result = runner.invoke(cli, ["config", "set", "voice", voice])
            assert result.exit_code == 0

            result = runner.invoke(cli, ["config", "get", "voice", ""])
            assert result.exit_code == 0
            assert voice in result.output


class TestConfigErrorHandling:
    """Test error handling in configuration operations."""

    def test_config_with_file_permission_error(self, unit_test_config):
        """Test handling of file permission errors."""
        # This test is complex to implement portably, so we'll mock the save operation
        runner = CliRunner()

        with patch("matilda_voice.internal.config.save_config") as mock_save:
            # Simulate a permission error
            mock_save.side_effect = PermissionError("Permission denied")

            result = runner.invoke(cli, ["config", "set", "test_key", "test_value"])
            # The command handles the error gracefully and prints error message
            assert result.exit_code == 1
            assert "Error in config command" in result.output
            assert "Permission denied" in result.output

    def test_config_with_corrupted_file(self, unit_test_config):
        """Test handling of corrupted configuration file."""
        config_file = unit_test_config["config_file"]

        # Write invalid TOML to the config file
        with open(config_file, "w") as f:
            f.write('voice = {"invalid":')

        runner = CliRunner()

        # Config operations should still work (fall back to defaults)
        result = runner.invoke(cli, ["config", "show", "", ""])
        assert result.exit_code == 0
        # Should show default values despite corrupted file

    def test_config_show_with_io_error(self, unit_test_config):
        """Test config show with I/O error during load."""
        runner = CliRunner()

        with patch("matilda_voice.internal.config.load_config") as mock_load:
            # Simulate an I/O error
            mock_load.side_effect = IOError("Disk error")

            result = runner.invoke(cli, ["config", "show", "", ""])
            assert result.exit_code == 1
            assert "Error in config command" in result.output
            assert "Disk error" in result.output


class TestConfigIntegration:
    """Integration tests for configuration functionality."""

    def test_config_roundtrip_all_actions(self, unit_test_config):
        """Test complete roundtrip of all config actions."""
        runner = CliRunner()

        # Start with show
        result = runner.invoke(cli, ["config", "show", "", ""])
        assert result.exit_code == 0

        # Set multiple values
        test_config = {
            "openai_api_key": "sk-test1234567890",
            "elevenlabs_api_key": "test_elevenlabs",
            "voice": "edge_tts:en-GB-LibbyNeural",
            "rate": "+25%",
            "output_dir": "~/test_downloads",
        }

        for key, value in test_config.items():
            result = runner.invoke(cli, ["config", "set", key, value])
            assert result.exit_code == 0
            assert f"Set {key} = {value}" in result.output

        # Set pitch with negative value using -- separator
        result = runner.invoke(cli, ["config", "set", "pitch", "--", "-10Hz"])
        assert result.exit_code == 0
        assert "Set pitch = -10Hz" in result.output
        test_config["pitch"] = "-10Hz"

        # Get all values
        for key, expected_value in test_config.items():
            result = runner.invoke(cli, ["config", "get", key, ""])
            assert result.exit_code == 0
            assert expected_value in result.output

        # Final show to verify everything
        result = runner.invoke(cli, ["config", "show", "", ""])
        assert result.exit_code == 0
        for value in test_config.values():
            assert value in result.output

    def test_config_interacts_with_real_filesystem(self, unit_test_config):
        """Test that config operations actually write to the filesystem."""
        config_file = unit_test_config["config_file"]
        runner = CliRunner()

        # Set a unique value
        unique_value = f"test_value_{os.getpid()}_{id(runner)}"
        result = runner.invoke(cli, ["config", "set", "filesystem_test", unique_value])
        assert result.exit_code == 0

        # Verify the value was written to the actual file
        with open(config_file, "r") as f:
            file_content = f.read()
        assert unique_value in file_content

        # Parse TOML to verify structure
        config_data = tomllib.loads(file_content)
        assert config_data["voice"]["filesystem_test"] == unique_value
