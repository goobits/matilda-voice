"""Tests for configuration management functionality.

These tests cover pure functions in the config module without requiring
external dependencies or mocks. They test core business logic for:
- Environment variable parsing
- Voice setting parsing and provider auto-detection
- API key validation
- SSML detection and processing
"""

from matilda_voice.internal.config import (
    CONFIG_DEFAULTS,
    _parse_env_value,
    get_config_value,
    parse_voice_setting,
    validate_api_key,
)
from matilda_voice.speech_synthesis.ssml.utils import is_ssml, strip_ssml_tags


class TestParseEnvValue:
    """Test environment variable parsing to different types."""

    def test_parse_bool_values(self):
        """Test parsing boolean values for configuration."""
        # Test key true values that matter in practice
        assert _parse_env_value("true", bool) is True
        assert _parse_env_value("1", bool) is True
        assert _parse_env_value("yes", bool) is True

        # Test key false values
        assert _parse_env_value("false", bool) is False
        assert _parse_env_value("0", bool) is False
        assert _parse_env_value("no", bool) is False

        # Test case insensitivity for common cases
        assert _parse_env_value("TRUE", bool) is True
        assert _parse_env_value("FALSE", bool) is False

        # Test unknown values default to False (important behavior)
        assert _parse_env_value("maybe", bool) is False
        assert _parse_env_value("", bool) is False
        assert _parse_env_value("invalid", bool) is False

    def test_parse_int_valid(self):
        """Test parsing valid integer values."""
        assert _parse_env_value("42", int) == 42
        assert _parse_env_value("0", int) == 0
        assert _parse_env_value("-123", int) == -123
        assert _parse_env_value("999999", int) == 999999

    def test_parse_int_invalid(self):
        """Test parsing invalid integer values returns original string."""
        assert _parse_env_value("not_a_number", int) == "not_a_number"
        assert _parse_env_value("12.34", int) == "12.34"
        assert _parse_env_value("", int) == ""

    def test_parse_float_valid(self):
        """Test parsing valid float values."""
        assert _parse_env_value("3.14", float) == 3.14
        assert _parse_env_value("0.0", float) == 0.0
        assert _parse_env_value("-2.5", float) == -2.5
        assert _parse_env_value("42", float) == 42.0  # int parsed as float

    def test_parse_float_invalid(self):
        """Test parsing invalid float values returns original string."""
        assert _parse_env_value("not_a_float", float) == "not_a_float"
        assert _parse_env_value("", float) == ""

    def test_parse_list_comma_separated(self):
        """Test parsing comma-separated list values."""
        assert _parse_env_value("a,b,c", list) == ["a", "b", "c"]
        assert _parse_env_value("one,two,three", list) == ["one", "two", "three"]
        assert _parse_env_value("single", list) == ["single"]
        assert _parse_env_value("", list) == [""]

    def test_parse_list_with_spaces(self):
        """Test parsing lists with spaces (should be preserved)."""
        assert _parse_env_value("a, b, c", list) == ["a", " b", " c"]
        assert _parse_env_value(" first , second ", list) == [" first ", " second "]

    def test_parse_string_type(self):
        """Test parsing string type (passthrough)."""
        assert _parse_env_value("hello", str) == "hello"
        assert _parse_env_value("", str) == ""
        assert _parse_env_value("123", str) == "123"


class TestParseVoiceSetting:
    """Test voice setting parsing and provider auto-detection."""

    def test_explicit_provider_voice_format(self):
        """Test explicit provider:voice format parsing."""
        # Standard provider:voice format
        provider, voice = parse_voice_setting("edge_tts:en-US-JennyNeural")
        assert provider == "edge_tts"
        assert voice == "en-US-JennyNeural"

        provider, voice = parse_voice_setting("openai:nova")
        assert provider == "openai"
        assert voice == "nova"

        provider, voice = parse_voice_setting("elevenlabs:Rachel")
        assert provider == "elevenlabs"
        assert voice == "Rachel"

        provider, voice = parse_voice_setting("google:en-US-Neural2-A")
        assert provider == "google"
        assert voice == "en-US-Neural2-A"

        provider, voice = parse_voice_setting("chatterbox:my_voice.wav")
        assert provider == "chatterbox"
        assert voice == "my_voice.wav"

    def test_file_path_auto_detection(self):
        """Test file paths auto-detected as chatterbox provider."""
        # Relative paths
        provider, voice = parse_voice_setting("voice.wav")
        assert provider == "chatterbox"
        assert voice == "voice.wav"

        provider, voice = parse_voice_setting("my_voice.wav")
        assert provider == "chatterbox"
        assert voice == "my_voice.wav"

        # Absolute paths
        provider, voice = parse_voice_setting("/path/to/voice.wav")
        assert provider == "chatterbox"
        assert voice == "/path/to/voice.wav"

        provider, voice = parse_voice_setting("~/my_voice.wav")
        assert provider == "chatterbox"
        assert voice == "~/my_voice.wav"

        # Different audio extensions
        for ext in ["wav", "mp3", "flac", "ogg", "m4a"]:
            provider, voice = parse_voice_setting(f"voice.{ext}")
            assert provider == "chatterbox"
            assert voice == f"voice.{ext}"

    def test_edge_tts_auto_detection(self):
        """Test Edge TTS voices auto-detected by pattern."""
        edge_voices = [
            "en-US-JennyNeural",
            "en-GB-LibbyNeural",
            "en-IE-EmilyNeural",
            "en-AU-NatashaNeural",
            "fr-FR-DeniseNeural",
            "de-DE-KatjaNeural",
        ]

        for voice_name in edge_voices:
            provider, voice = parse_voice_setting(voice_name)
            assert provider == "edge_tts", f"Voice {voice_name} should be detected as edge_tts"
            assert voice == voice_name

    def test_google_tts_auto_detection(self):
        """Test Google TTS voices auto-detected by pattern."""
        google_voices = ["en-US-Neural2-A", "en-US-Neural2-B", "en-GB-Neural2-A", "fr-FR-Neural2-A", "de-DE-Neural2-A"]

        for voice_name in google_voices:
            provider, voice = parse_voice_setting(voice_name)
            assert provider == "google", f"Voice {voice_name} should be detected as google"
            assert voice == voice_name

    def test_openai_voices_auto_detection(self):
        """Test OpenAI voices auto-detected by known names."""
        openai_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

        for voice_name in openai_voices:
            provider, voice = parse_voice_setting(voice_name)
            assert provider == "openai", f"Voice {voice_name} should be detected as openai"
            assert voice == voice_name

    def test_unknown_voice_fallback(self):
        """Test unknown voices fall back to no provider detection."""
        provider, voice = parse_voice_setting("unknown_voice_123")
        assert provider is None
        assert voice == "unknown_voice_123"

        provider, voice = parse_voice_setting("random-voice-name")
        assert provider is None
        assert voice == "random-voice-name"

    def test_empty_and_edge_cases(self):
        """Test empty strings and edge cases."""
        provider, voice = parse_voice_setting("")
        assert provider is None
        assert voice == ""

        # Just a colon
        provider, voice = parse_voice_setting(":")
        assert provider == ""
        assert voice == ""

        # Provider but no voice
        provider, voice = parse_voice_setting("openai:")
        assert provider == "openai"
        assert voice == ""

        # Multiple colons (only first one counts)
        provider, voice = parse_voice_setting("edge_tts:voice:with:colons")
        assert provider == "edge_tts"
        assert voice == "voice:with:colons"


class TestValidateApiKey:
    """Test API key validation for different providers."""

    def test_openai_api_key_valid(self):
        """Test valid OpenAI API key formats."""
        # Standard format: sk- followed by 48 characters
        valid_keys = [
            "sk-1234567890abcdef1234567890abcdef12345678901234",  # 48 chars
            "sk-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRST",  # mixed case
            "sk-123456789012345678901234567890123456789012345678",  # all numbers
        ]

        for key in valid_keys:
            assert validate_api_key("openai", key) is True, f"Key '{key}' should be valid"

    def test_openai_api_key_invalid(self):
        """Test invalid OpenAI API key formats."""
        invalid_keys = [
            "",  # empty
            "sk-",  # too short
            "sk-123",  # too short
            "sk-123456789012345678901234567890123456789012345678901234567890",  # too long
            "sk_1234567890abcdef1234567890abcdef12345678901234",  # underscore instead of dash
            "1234567890abcdef1234567890abcdef12345678901234567890",  # missing sk- prefix
            "sk-12345678901234567890123456789012345678901234",  # 47 chars (one short)
            None,  # None value
        ]

        for key in invalid_keys:
            assert validate_api_key("openai", key) is False, f"Key '{key}' should be invalid"

    def test_elevenlabs_api_key_valid(self):
        """Test valid ElevenLabs API key formats."""
        # 32-character hexadecimal strings
        valid_keys = [
            "abcdef1234567890abcdef1234567890",  # lowercase hex
            "ABCDEF1234567890ABCDEF1234567890",  # uppercase hex
            "AbCdEf1234567890aBcDeF1234567890",  # mixed case hex
            "1234567890abcdef1234567890abcdef",  # numbers and letters
        ]

        for key in valid_keys:
            assert validate_api_key("elevenlabs", key) is True, f"Key '{key}' should be valid"

    def test_elevenlabs_api_key_invalid(self):
        """Test invalid ElevenLabs API key formats."""
        invalid_keys = [
            "",  # empty
            "123",  # too short
            "abcdef1234567890abcdef1234567890abcdef",  # too long (35 chars)
            "abcdef1234567890abcdef123456789",  # too short (31 chars)
            "abcdef1234567890abcdef1234567890g",  # invalid hex character
            "abcdef-1234567890abcdef1234567890",  # contains dash
            "abcdef 1234567890abcdef1234567890",  # contains space
            None,  # None value
        ]

        for key in invalid_keys:
            assert validate_api_key("elevenlabs", key) is False, f"Key '{key}' should be invalid"

    def test_google_api_key_valid(self):
        """Test valid Google API key formats."""
        # Google API keys are typically 39 characters starting with AIza
        valid_keys = [
            "AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI",  # Standard format
            "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567",  # Mixed alphanumeric
        ]

        for key in valid_keys:
            assert validate_api_key("google", key) is True, f"Key '{key}' should be valid"

    def test_google_api_key_invalid(self):
        """Test invalid Google API key formats."""
        invalid_keys = [
            "",  # empty
            "AIza",  # too short
            "AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI123456789",  # too long
            "BIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI",  # wrong prefix
            "AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsH",  # too short (38 chars)
            None,  # None value
        ]

        for key in invalid_keys:
            assert validate_api_key("google", key) is False, f"Key '{key}' should be invalid"

    def test_unknown_provider(self):
        """Test validation for unknown providers (should return False)."""
        assert validate_api_key("unknown_provider", "any_key") is False
        assert validate_api_key("", "any_key") is False
        assert validate_api_key(None, "any_key") is False

    def test_non_string_keys(self):
        """Test validation with non-string key values."""
        assert validate_api_key("openai", 123) is False
        assert validate_api_key("openai", []) is False
        assert validate_api_key("openai", {}) is False


class TestSSMLProcessing:
    """Test SSML detection and processing functions."""

    def test_is_ssml_valid_markup(self):
        """Test detection of valid SSML markup."""
        valid_ssml = [
            "<speak>Hello world</speak>",
            "<speak version='1.0'>Hello</speak>",
            "<speak xmlns='http://www.w3.org/2001/10/synthesis'>Hello</speak>",
            "  <speak>Hello world</speak>  ",  # with whitespace
            "<speak>Hello <break time='1s'/> world</speak>",
            "<speak><prosody rate='slow'>Hello</prosody></speak>",
        ]

        for text in valid_ssml:
            assert is_ssml(text) is True, f"'{text}' should be detected as SSML"

    def test_is_ssml_invalid_markup(self):
        """Test detection of non-SSML text."""
        invalid_ssml = [
            "Hello world",  # plain text
            "<div>Hello world</div>",  # HTML, not SSML
            "<speak>Hello world",  # missing closing tag
            "Hello world</speak>",  # missing opening tag
            "<SPEAK>Hello world</SPEAK>",  # wrong case
            "",  # empty string
            "<speak/>",  # self-closing (not standard SSML)
            "speak>Hello world</speak>",  # missing opening bracket
        ]

        for text in invalid_ssml:
            assert is_ssml(text) is False, f"'{text}' should NOT be detected as SSML"

    def test_strip_ssml_tags_simple(self):
        """Test removal of simple SSML tags."""
        assert strip_ssml_tags("<speak>Hello world</speak>") == "Hello world"
        assert strip_ssml_tags("<prosody rate='slow'>Slow speech</prosody>") == "Slow speech"
        assert strip_ssml_tags("<break time='1s'/>") == ""
        assert strip_ssml_tags("No tags here") == "No tags here"

    def test_strip_ssml_tags_complex(self):
        """Test removal of complex nested SSML tags."""
        complex_ssml = "<speak>Hello <break time='1s'/> " "<prosody rate='slow'>slow</prosody> world</speak>"
        expected = "Hello  slow world"
        assert strip_ssml_tags(complex_ssml) == expected

        nested_ssml = "<speak><prosody rate='fast'><emphasis>Important</emphasis> " "message</prosody></speak>"
        expected = "Important message"
        assert strip_ssml_tags(nested_ssml) == expected

    def test_strip_ssml_tags_with_attributes(self):
        """Test removal of tags with various attributes."""
        with_attrs = "<prosody rate='slow' pitch='+2st' volume='loud'>Hello</prosody>"
        assert strip_ssml_tags(with_attrs) == "Hello"

        self_closing = "Start <break time='500ms'/> End"
        assert strip_ssml_tags(self_closing) == "Start  End"

    def test_strip_ssml_tags_preserve_content(self):
        """Test that text content is preserved correctly."""
        # Content with special characters
        special_content = "<speak>Price: $19.99 (50% off!)</speak>"
        assert strip_ssml_tags(special_content) == "Price: $19.99 (50% off!)"

        # Content with numbers and symbols
        mixed_content = "<prosody>Call 1-800-123-4567 @ 9:00 AM</prosody>"
        assert strip_ssml_tags(mixed_content) == "Call 1-800-123-4567 @ 9:00 AM"


class TestConfigDefaults:
    """Test configuration default values and access."""

    def test_config_defaults_exist(self):
        """Test that expected configuration defaults exist."""
        # Network settings
        assert "chatterbox_server_port" in CONFIG_DEFAULTS
        assert "http_streaming_chunk_size" in CONFIG_DEFAULTS

        # Timeout settings
        assert "server_startup_timeout" in CONFIG_DEFAULTS
        assert "ffplay_timeout" in CONFIG_DEFAULTS

        # Performance settings
        assert "thread_pool_max_workers" in CONFIG_DEFAULTS
        assert "streaming_progress_interval" in CONFIG_DEFAULTS

    def test_config_default_types(self):
        """Test that configuration defaults have expected types."""
        # Should be integers
        int_configs = [
            "chatterbox_server_port",
            "http_streaming_chunk_size",
            "server_startup_timeout",
            "thread_pool_max_workers",
        ]

        for config_key in int_configs:
            if config_key in CONFIG_DEFAULTS:
                assert isinstance(CONFIG_DEFAULTS[config_key], int), f"{config_key} should be an integer"

    def test_get_config_value_defaults(self):
        """Test getting configuration values returns defaults when no override."""
        # Test some known defaults
        assert get_config_value("chatterbox_server_port") == CONFIG_DEFAULTS["chatterbox_server_port"]
        assert get_config_value("http_streaming_chunk_size") == CONFIG_DEFAULTS["http_streaming_chunk_size"]

        # Test with custom default
        assert get_config_value("nonexistent_key", "custom_default") == "custom_default"

    def test_get_config_value_unknown_key(self):
        """Test getting unknown configuration key returns None."""
        assert get_config_value("completely_unknown_key_12345") is None
