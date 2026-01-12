"""Simple configuration management for TTS CLI.

This module provides a lightweight configuration system that supports:
- TOML configuration file (~/.matilda/config.toml)
- Environment variable overrides (TTS_<KEY>)
- Simple function-based access pattern

Usage:
    from .config import get_config_value
    port = get_config_value('chatterbox_server_port')  # Returns 12345 or env override
"""

import logging
import os
import tomllib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import toml

logger = logging.getLogger(__name__)

# All configuration defaults in one flat dictionary
CONFIG_DEFAULTS = {
    # Network & Communication
    "chatterbox_server_port": 12345,
    "socket_recv_buffer_size": 4096,
    "http_streaming_chunk_size": 1024,
    # Timeouts (seconds)
    "server_startup_timeout": 30,
    "server_poll_interval": 1,
    "socket_connection_timeout": 1,
    "voice_loading_timeout": 30,
    "audio_check_timeout": 2,
    "ffprobe_timeout": 5,
    "ffmpeg_validation_timeout": 5,
    "ffplay_timeout": 5,
    "ffplay_termination_timeout": 2,
    "ffmpeg_conversion_timeout": 30,
    # User Interface
    "ui_double_click_time": 0.8,
    "ui_filter_panel_width": 20,
    "ui_preview_panel_width": 18,
    "ui_status_display_time": 1000,
    "ui_click_feedback_time": 500,
    "ui_success_message_time": 1500,
    "ui_page_scroll_amount": 10,
    "ui_printable_char_range_start": 32,
    "ui_printable_char_range_end": 126,
    # Audio Processing
    "audio_16bit_scale": 32767,
    "audio_amplitude_limit": 0.95,
    "audio_channels": 1,
    "audio_sample_width": 2,
    "audio_cards_min_size": 0,
    # Provider Defaults - ElevenLabs
    "elevenlabs_default_stability": 0.5,
    "elevenlabs_default_similarity_boost": 0.5,
    "elevenlabs_default_style": 0.0,
    "elevenlabs_voice_id_length": 32,
    "elevenlabs_api_key_length": 32,
    # Provider Defaults - Google TTS
    "google_default_speaking_rate": 1.0,
    "google_default_pitch": 0.0,
    "google_api_key_length": 39,
    "oauth_token_min_length": 50,
    "service_account_json_min_length": 100,
    # Provider Defaults - Chatterbox
    "chatterbox_default_exaggeration": 0.5,
    "chatterbox_default_cfg_weight": 0.5,
    "chatterbox_default_temperature": 0.8,
    "chatterbox_default_min_p": 0.05,
    # HTTP Status Codes
    "http_unauthorized": 401,
    "http_forbidden": 403,
    "http_rate_limit": 429,
    "http_payment_errors": [402],
    "http_server_error_range_start": 500,
    "http_server_error_range_end": 600,
    "error_message_max_length": 100,
    # API Key Validation
    "openai_api_key_min_length": 48,
    "openai_api_key_max_length": 51,
    # Streaming & Progress
    "streaming_progress_interval": 10,
    "streaming_playback_start_threshold": 3,
    # Voice & Sample Management
    "provider_sample_voices_count": 5,
    "voice_list_max_display": 15,
    "voice_name_display_length": 25,
    "voice_name_truncation_offset": 18,
    # System Resources
    "thread_pool_max_workers": 1,
    "memory_gb_conversion_factor": 1024,
    # Cache Settings
    "cache_file_ttl_seconds": 86400,  # 24 hours
    "cache_recent_access_window_seconds": 3600,  # 1 hour
    # Provider-specific Limits
    "google_service_account_json_min_length": 100,
    # Voice Defaults
    "default_provider": "edge_tts",
    "default_voice": "en-US-EmmaMultilingualNeural",
    "default_rate": "+0%",
    "default_pitch": "+0Hz",
    "default_output_format": "mp3",
}

# Default configuration for voice settings (minimal)
DEFAULT_CONFIG = {
    "version": "1.0",
    "default_action": "stream",
    "voice": "edge_tts:en-US-EmmaMultilingualNeural",
    "rate": "+0%",
    "pitch": "+0Hz",
    "output_dir": "~/Downloads",
    "log_level": "info",
    "document_parsing": {
        "default_format": "auto",
        "emotion_detection": True,
        "preserve_formatting": False,
        "cache_enabled": True,
        "cache_ttl": 3600,
    },
    "speech_synthesis": {
        "emotion_level": "moderate",
        "timing_precision": "standard",
        "ssml_platform": "generic",
        "paragraph_pause": 1.0,
        "sentence_pause": 0.5,
    },
}

_config_cache = None


def load_toml_config() -> Dict[str, Any]:
    """Load configuration from TOML file and environment variables."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config = CONFIG_DEFAULTS.copy()

    config_file = get_config_path()
    if config_file.exists():
        try:
            with open(config_file, "rb") as f:
                full_config = tomllib.load(f)
            file_config = full_config.get("voice")
            if file_config is None:
                raise KeyError("Missing [voice] section in matilda config")

            # Flatten nested TOML sections to flat keys
            for section, values in file_config.items():
                if isinstance(values, dict):
                    for key, value in values.items():
                        flat_key = f"{section}_{key}"
                        if flat_key in config:
                            config[flat_key] = value
                else:
                    if section in config:
                        config[section] = values

            logger.debug(f"Loaded TOML config from {config_file}")
        except Exception:
            logger.exception(f"Failed to load TOML config from {config_file}")

    # Environment variable overrides (highest precedence)
    for key in config:
        env_value = os.environ.get(f"TTS_{key.upper()}")
        if env_value is not None:
            config[key] = _parse_env_value(env_value, type(config[key]))
            logger.debug(f"Override from env: {key} = {config[key]}")

    _config_cache = config
    return config


def _parse_env_value(value: str, expected_type: type) -> Any:
    """Parse environment variable value to appropriate type."""
    if expected_type is bool:
        return value.lower() in ("true", "1", "yes", "on")
    elif expected_type is int:
        try:
            return int(value)
        except ValueError:
            return value
    elif expected_type is float:
        try:
            return float(value)
        except ValueError:
            return value
    elif expected_type is list:
        # Simple list parsing for things like http_payment_errors
        try:
            return [int(x.strip()) for x in value.split(",")]
        except ValueError:
            return value.split(",")
    return value


def get_config_value(key: str, default: Any = None) -> Any:
    """Get a configuration value. Simple function - no classes needed."""
    config = load_toml_config()
    return config.get(key, default)


def reload_config() -> None:
    """Reload configuration from files (useful for testing)."""
    global _config_cache
    _config_cache = None


# Configuration file management
def get_config_path() -> Path:
    """Get the configuration file path, using XDG standard with fallback."""
    env_path = os.environ.get("MATILDA_CONFIG")
    if env_path:
        return Path(env_path)
    return Path.home() / ".matilda" / "config.toml"


def get_default_config() -> Dict[str, Any]:
    """Get the default configuration."""
    return DEFAULT_CONFIG.copy()


def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> Dict[str, Any]:
    """Load TOML configuration from file."""
    config_path = get_config_path()
    config = get_default_config()

    if not config_path.exists():
        logger.debug(f"Config file not found at {config_path}, using defaults")
        return config

    try:
        with open(config_path, "rb") as f:
            full_config = tomllib.load(f)
        file_config = full_config.get("voice", {})
        return _merge_dicts(config, file_config)
    except Exception as e:
        logger.warning(f"Failed to load config from {config_path}: {e}. Using defaults.")
        return config


def save_config(config: Dict[str, Any]) -> bool:
    """Save configuration to file atomically."""
    config_path = get_config_path()

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)

        if config_path.exists():
            with open(config_path, "rb") as f:
                full_config = tomllib.load(f)
        else:
            full_config = {}

        full_config["voice"] = config
        temp_path = config_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(toml.dumps(full_config))

        temp_path.replace(config_path)
        logger.info(f"Configuration saved to {config_path}")
        return True

    except (IOError, OSError) as e:
        logger.error(f"Failed to save config to {config_path}: {e}")
        return False


def parse_voice_setting(voice_str: str) -> Tuple[Optional[str], str]:
    """Parse voice setting, returning (provider, voice) tuple.

    Handles both explicit provider:voice format and auto-detection.

    Args:
        voice_str: Voice string like "edge_tts:en-IE-EmilyNeural" or "en-IE-EmilyNeural"

    Returns:
        (provider, voice) tuple. Provider may be None for auto-detection.
    """
    if ":" in voice_str:
        # Explicit provider format: "openai:nova", "google:en-US-Neural2-A", etc.
        provider, voice = voice_str.split(":", 1)
        return provider, voice
    else:
        # Auto-detect provider based on voice characteristics
        if "/" in voice_str or voice_str.endswith((".wav", ".mp3", ".flac", ".ogg", ".m4a")):
            # File path - likely chatterbox voice cloning
            return "chatterbox", voice_str
        elif voice_str in ["alloy", "echo", "fable", "nova", "onyx", "shimmer"]:
            # OpenAI voice names
            return "openai", voice_str
        elif voice_str.startswith(("en-", "es-", "fr-", "de-", "it-", "pt-", "ja-", "ko-", "zh-")) and (
            "Neural2" in voice_str or "Wavenet" in voice_str
        ):
            # Google Cloud TTS format like "en-US-Neural2-A" or "en-US-Wavenet-A"
            return "google", voice_str
        elif voice_str in ["rachel", "domi", "bella", "antoni", "elli", "josh", "arnold", "adam", "sam"]:
            # ElevenLabs default voice names
            return "elevenlabs", voice_str
        elif "Neural" in voice_str or (
            len(voice_str.split("-")) >= 3
            and voice_str.startswith(("en-", "es-", "fr-", "de-", "it-", "pt-", "ru-", "ja-", "ko-", "zh-"))
        ):
            # Standard Azure/Edge TTS format like "en-US-JennyNeural"
            # (language-region-voice pattern)
            return "edge_tts", voice_str
        else:
            # Unknown format, let current provider handle it
            return None, voice_str


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clean configuration values."""
    validated = config.copy()

    # Validate default_action
    if validated.get("default_action") not in ["stream", "save"]:
        validated["default_action"] = "stream"

    # Validate log_level
    valid_levels = ["debug", "info", "warning", "error"]
    if validated.get("log_level") not in valid_levels:
        validated["log_level"] = "info"

    # Expand output_dir tilde
    if "output_dir" in validated:
        validated["output_dir"] = str(Path(validated["output_dir"]).expanduser())

    return validated


def get_setting(key: str, default: Any = None) -> Any:
    """Get a single setting from configuration."""
    config = load_config()
    return config.get(key, default)


def set_setting(key: str, value: Any) -> bool:
    """Set a single setting in configuration."""
    config = load_config()
    config[key] = value
    validated_config = validate_config(config)
    return save_config(validated_config)


def validate_api_key(provider: str, api_key: str) -> bool:
    """Validate API key format for different providers."""
    if not api_key or not isinstance(api_key, str) or not provider or not isinstance(provider, str):
        return False

    if provider == "openai":
        # OpenAI keys start with sk- and are typically 48-51 chars
        min_length = int(get_config_value("openai_api_key_min_length", 48))
        max_length = int(get_config_value("openai_api_key_max_length", 51))
        return api_key.startswith("sk-") and min_length <= len(api_key) <= max_length

    elif provider == "google":
        # Google API keys are 39 chars, start with AIza or can be OAuth token
        google_key_length = int(get_config_value("google_api_key_length", 39))
        oauth_min_length = int(get_config_value("oauth_token_min_length", 50))
        service_account_min_length = int(get_config_value("service_account_json_min_length", 100))
        return (
            (api_key.startswith("AIza") and len(api_key) == google_key_length)
            or (api_key.startswith("ya29.") and len(api_key) > oauth_min_length)
            or len(api_key) > service_account_min_length
        )  # Service account JSON string

    elif provider == "elevenlabs":
        # ElevenLabs keys are 32 char hex strings
        elevenlabs_key_length = int(get_config_value("elevenlabs_api_key_length", 32))
        return len(api_key) == elevenlabs_key_length and all(c in "0123456789abcdef" for c in api_key.lower())

    else:
        # Unknown provider, return False for security
        return False


def get_api_key(provider: str) -> Optional[str]:
    """Get API key for a provider, checking TOML config and environment.

    Search order:
    1. Environment variables (PROVIDER_API_KEY)
    2. TOML configuration (provider_api_key)

    Args:
        provider: Provider name (e.g., 'elevenlabs', 'openai', 'google')

    Returns:
        API key string if found and valid, None otherwise
    """
    # Check TOML config
    config_key = f"{provider}_api_key"
    json_api_key = get_setting(config_key)
    if json_api_key and validate_api_key(provider, str(json_api_key)):
        return str(json_api_key)

    # Fallback to environment variables
    env_key = f"{provider.upper()}_API_KEY"
    env_api_key = os.environ.get(env_key)
    if env_api_key and validate_api_key(provider, env_api_key):
        return env_api_key

    return None


def set_api_key(provider: str, api_key: str) -> bool:
    """Set and validate API key for a provider."""
    if not validate_api_key(provider, api_key):
        return False

    config_key = f"{provider}_api_key"
    return set_setting(config_key, api_key)
