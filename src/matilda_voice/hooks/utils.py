#!/usr/bin/env python3
"""Hook handlers for TTS CLI."""

from typing import Any, Optional

from matilda_voice.core import get_tts_engine
from matilda_voice.registry import PROVIDERS_REGISTRY, PROVIDER_SHORTCUTS

__all__ = [
    "get_engine",
    "parse_provider_shortcuts",
    "handle_provider_shortcuts",
    "PROVIDERS_REGISTRY",
    "PROVIDER_SHORTCUTS",
]


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
