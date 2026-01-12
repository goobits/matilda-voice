"""
Test validation for the shared test utilities.

This file tests the test utilities themselves to ensure they work correctly.
"""

from tests.utils import (
    PROVIDER_SHORTCUTS_TEST_DATA,
    CLITestHelper,
    create_mock_audio_file,
    create_mock_provider,
    create_test_config,
    validate_audio_file,
)


class TestUtilitiesValidation:
    """Test the shared test utilities themselves."""

    def test_cli_helper_initialization(self):
        """Test that CLITestHelper can be initialized."""
        helper = CLITestHelper()
        assert helper is not None
        assert helper.runner is not None

    def test_mock_provider_creation(self):
        """Test mock provider creation utility."""
        provider = create_mock_provider("test_provider", voices=["voice1", "voice2"])

        assert provider.name == "test_provider"

        # Test get_info method
        info = provider.get_info.return_value
        assert info["name"] == "test_provider"
        assert info["sample_voices"] == ["voice1", "voice2"]

    def test_audio_file_creation(self, tmp_path):
        """Test mock audio file creation utility."""
        file_path = tmp_path / "test_audio"
        created_file = create_mock_audio_file(file_path, format="mp3", size_bytes=100)

        assert created_file.exists()
        assert created_file.suffix == ".mp3"
        assert created_file.stat().st_size > 0

    def test_audio_file_validation(self, tmp_path):
        """Test audio file validation utility."""
        # Create a test file
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"test audio data")

        # Validate it
        assert validate_audio_file(audio_file, expected_format="mp3")

        # Test with wrong format
        assert not validate_audio_file(audio_file, expected_format="wav")

        # Test with non-existent file
        assert not validate_audio_file(tmp_path / "nonexistent.mp3")

    def test_config_creation(self, tmp_path):
        """Test test configuration creation utility."""
        config_file = create_test_config(
            tmp_path / "config", default_provider="test_provider", default_voice="test_voice"
        )

        assert config_file.exists()

        # Check content
        import tomllib

        with open(config_file, "rb") as f:
            config = tomllib.load(f)

        assert config["voice"]["default_provider"] == "test_provider"
        assert config["voice"]["default_voice"] == "test_voice"
        assert "openai_api_key" in config["voice"]  # Should have default API keys

    def test_provider_shortcuts_data(self):
        """Test that provider shortcuts test data is valid."""
        assert len(PROVIDER_SHORTCUTS_TEST_DATA) > 0

        for shortcut, provider_name in PROVIDER_SHORTCUTS_TEST_DATA:
            assert shortcut.startswith("@")
            assert len(provider_name) > 0
            assert isinstance(shortcut, str)
            assert isinstance(provider_name, str)


class TestUtilitiesIntegration:
    """Test utilities integration with actual test scenarios."""

    def test_mock_provider_synthesize_behavior(self, tmp_path):
        """Test that mock provider synthesize method works as expected."""
        provider = create_mock_provider("test_provider")
        output_file = tmp_path / "output.mp3"

        # Call synthesize
        provider.synthesize("test text", str(output_file))

        # Verify it was called
        provider.synthesize.assert_called_once_with("test text", str(output_file))

        # Verify file was created (by the mock)
        assert output_file.exists()
        content = output_file.read_bytes()
        assert b"test_provider" in content

    def test_cli_helper_with_mock_runner(self):
        """Test CLI helper with a custom runner."""
        from click.testing import CliRunner

        custom_runner = CliRunner()
        helper = CLITestHelper(custom_runner)

        assert helper.runner is custom_runner

    def test_utilities_import_structure(self):
        """Test that utilities can be imported correctly."""
        # Test direct imports
        from tests.utils.test_helpers import CLITestHelper, create_mock_provider

        assert CLITestHelper is not None
        assert create_mock_provider is not None

        # Test package imports
        from tests.utils import CLITestHelper as PackageCLIHelper

        assert PackageCLIHelper is CLITestHelper
