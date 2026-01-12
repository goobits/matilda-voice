#!/usr/bin/env python3
"""Hook handlers for Voice CLI."""

from typing import Optional

from matilda_voice.i18n import t, t_common

from .utils import exit_with_message, get_engine


def _get_config_functions():
    """Late-bind config functions to allow patching."""
    from matilda_voice.internal.config import load_config, save_config

    return load_config, save_config


def on_status(**kwargs) -> int:
    """Handle the status command"""
    try:
        load_config, save_config = _get_config_functions()
        engine = get_engine()
        config = load_config()

        print(f"{t_common('icons.info')} {t('status.title')}")
        print("==================")

        print("\n📋 Provider Status:")
        available = engine.get_available_providers()

        ready_count = 0
        needs_setup_count = 0
        error_count = 0

        for provider in available:
            status = engine.get_provider_status(provider)

            # Determine status indicator and count
            if status["available"] and status["configured"]:
                status_icon = "✅"
                status_text = "Ready"
                ready_count += 1
            elif status["available"] and not status["configured"]:
                status_icon = "🔑"
                status_text = "Needs API key"
                needs_setup_count += 1
            elif not status["installed"]:
                status_icon = "❌"
                status_text = "Not installed"
                error_count += 1
            elif status["error"]:
                status_icon = "⚠️"
                status_text = f"Warning: {status['error']}"
                error_count += 1
            else:
                status_icon = "❓"
                status_text = "Unknown"
                error_count += 1

            print(f"  {status_icon} {provider:<15} {status_text}")

            # Show helpful setup hints for providers that need configuration
            if not status["configured"] and status["installed"]:
                api_key_name = engine._get_api_key_provider_name(provider)
                if provider == "openai_tts":
                    print(f"      💡 Run: voice config set {api_key_name}_api_key YOUR_KEY")
                elif provider == "elevenlabs":
                    print(f"      💡 Run: voice config set {api_key_name}_api_key YOUR_KEY")
                elif provider == "google_tts":
                    print(f"      💡 Run: voice config set {api_key_name}_api_key YOUR_KEY")
                    print(f"      💡 Or:  voice config set {api_key_name}_credentials_path /path/to/creds.json")

        # Summary
        total = len(available)
        print(f"\n📊 Summary: {ready_count}/{total} ready, {needs_setup_count} need setup, {error_count} errors")

        print("\n⚙️  Configuration:")
        print(f"  Default voice: {config.get('voice', 'Not set')}")
        print(f"  Config file: {config.get('config_path', 'Default location')}")

        # Show some important config values
        important_keys = ["openai_api_key", "elevenlabs_api_key", "google_api_key", "google_credentials_path"]
        configured_apis = []
        for key in important_keys:
            if config.get(key):
                api_name = key.replace("_api_key", "").replace("_credentials_path", "")
                configured_apis.append(api_name)

        if configured_apis:
            print(f"  Configured APIs: {', '.join(configured_apis)}")
        else:
            print("  Configured APIs: None")

        # Show helpful next steps
        if needs_setup_count > 0:
            print("\n💡 Setup Help:")
            print("  • Get OpenAI key: https://platform.openai.com/api-keys")
            print("  • Get ElevenLabs key: https://elevenlabs.io/profile")
            print("  • Get Google Cloud creds: https://console.cloud.google.com/")
            print("  • Run 'voice info <provider>' for detailed setup instructions")

        return 0
    except (ImportError, KeyError, AttributeError) as e:
        print(f"Error in status command: {e}")
        return 1


def on_config(action: Optional[str], key: Optional[str], value: Optional[str], **kwargs) -> int:
    """Handle the config command"""
    try:
        load_config, save_config = _get_config_functions()
        config = load_config()

        if action == "show" or not action:
            print("🔧 Voice Configuration")
            print("===================")
            for k, v in config.items():
                if k != "config_path":  # Skip internal keys
                    print(f"  {k}: {v}")
        elif action == "get":
            if not key:
                exit_with_message("Error: Missing config key", exit_code=2, show_usage=True)
            print(config.get(key, "Not set"))
        elif action == "set":
            if not key:
                exit_with_message("Error: Missing config key", exit_code=2, show_usage=True)
            if value is None:
                exit_with_message("Error: Missing config value", exit_code=2, show_usage=True)
            config[key] = value
            save_config(config)
            print(f"Set {key} = {value}")
        else:
            exit_with_message("Usage: config [show|get|set] [key] [value]", exit_code=2, show_usage=True)

        return 0
    except (IOError, OSError, ValueError, KeyError) as e:
        exit_with_message(f"Error in config command: {e}", exit_code=1)
