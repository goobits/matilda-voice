"""
Hook implementations for Matilda Voice - Text to Speech.

This file re-exports hook implementations from the hooks package.
The CLI imports hooks from here, which delegates to the real implementations.
"""

# Re-export all hooks from the hooks package
from matilda_voice.hooks import (
    PROVIDER_SHORTCUTS,
    # Registries
    PROVIDERS_REGISTRY,
    get_engine,
    handle_provider_shortcuts,
    on_config,
    # Document
    on_document,
    on_info,
    on_install,
    on_providers,
    on_save,
    # Core
    on_speak,
    # System
    on_status,
    # Voice
    on_voice_load,
    on_voice_status,
    on_voice_unload,
    # Providers
    on_voices,
    # Utils
    parse_provider_shortcuts,
)

# Re-export config functions for backwards compatibility
from matilda_voice.internal.config import load_config, save_config

__all__ = [
    # Registries
    "PROVIDERS_REGISTRY",
    "PROVIDER_SHORTCUTS",
    # Utils
    "parse_provider_shortcuts",
    "handle_provider_shortcuts",
    "get_engine",
    # Core
    "on_speak",
    "on_save",
    # Providers
    "on_voices",
    "on_providers",
    "on_install",
    "on_info",
    # Voice
    "on_voice_load",
    "on_voice_unload",
    "on_voice_status",
    # System
    "on_status",
    "on_config",
    # Document
    "on_document",
    # Config
    "load_config",
    "save_config",
]
