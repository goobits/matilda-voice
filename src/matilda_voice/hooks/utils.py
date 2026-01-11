#!/usr/bin/env python3
"""Hook handlers for TTS CLI."""

from typing import Any, Optional

from matilda_voice.core import get_tts_engine

# Provider registry - this should match what was in the original CLI
PROVIDERS_REGISTRY = {
    "azure_tts": "matilda_voice.providers.azure_tts",
    "edge_tts": "matilda_voice.providers.edge_tts",
    "openai_tts": "matilda_voice.providers.openai_tts",
    "elevenlabs": "matilda_voice.providers.elevenlabs",
    "google_tts": "matilda_voice.providers.google_tts",
    "chatterbox": "matilda_voice.providers.chatterbox",
    "coqui": "matilda_voice.providers.coqui",
}

# Provider shortcuts mapping for @provider syntax
PROVIDER_SHORTCUTS = {
    "azure": "azure_tts",
    "edge": "edge_tts",
    "openai": "openai_tts",
    "elevenlabs": "elevenlabs",
    "google": "google_tts",
    "chatterbox": "chatterbox",
    "coqui": "coqui",
}


def parse_provider_shortcuts(args: list) -> tuple[Optional[str], list]:
    """Parse @provider shortcuts from arguments"""
    if not args:
        return None, args

    # Check if first argument is a provider shortcut
    first_arg = args[0]
    if first_arg.startswith("@"):
        shortcut = first_arg[1:]  # Remove @
        if shortcut in PROVIDER_SHORTCUTS:
            provider_name = PROVIDER_SHORTCUTS[shortcut]
            remaining_args = args[1:]  # Rest of the arguments
            return provider_name, remaining_args
        else:
            # Invalid shortcut - let calling function handle the error
            return first_arg, args[1:]

    return None, args


def handle_provider_shortcuts(provider_arg: Optional[str]) -> Optional[str]:
    """Handle @provider syntax in commands"""
    if not provider_arg:
        return None

    if provider_arg.startswith("@"):
        shortcut = provider_arg[1:]  # Remove @
        if shortcut in PROVIDER_SHORTCUTS:
            return PROVIDER_SHORTCUTS[shortcut]
        else:
            # Return the original for error handling
            return provider_arg

    return provider_arg


def get_engine() -> Any:
    """Get or create TTS engine instance"""
    try:
        return get_tts_engine()
    except (ImportError, AttributeError, RuntimeError):
        from matilda_voice.core import initialize_tts_engine

        return initialize_tts_engine(PROVIDERS_REGISTRY)
