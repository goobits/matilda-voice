#!/usr/bin/env python3
"""Hook handlers for TTS CLI."""

import sys
from typing import Optional

from .utils import (
    PROVIDER_SHORTCUTS,
    PROVIDERS_REGISTRY,
    exit_with_message,
    get_engine,
    handle_provider_shortcuts,
)


def on_voices(args: tuple, **kwargs) -> int:
    """Handle the voices command"""
    import os

    try:
        from matilda_voice.voice_browser import VoiceBrowser

        engine = get_engine()

        # Create and launch voice browser
        browser = VoiceBrowser(PROVIDERS_REGISTRY, engine.load_provider)

        # Try to reset terminal state before launching curses
        try:
            # Reset terminal to a clean state
            os.system("stty sane")
        except OSError:
            pass

        # Run the browser with its built-in curses wrapper
        browser.run()
        return 0
    except Exception:
        # Re-raise to let CLI handle it with user-friendly messages
        raise


def on_providers(provider_name: Optional[str], **kwargs) -> int:
    """Handle the providers command"""
    try:
        engine = get_engine()
        available = engine.get_available_providers()

        if provider_name:
            if provider_name in available:
                info = engine.get_provider_info(provider_name)
                if info:
                    print(f"Provider: {provider_name}")
                    for key, value in info.items():
                        print(f"  {key}: {value}")
                else:
                    print(f"No info available for {provider_name}")
            else:
                print(f"Provider {provider_name} not found")
                print(f"Available providers: {', '.join(available)}")
        else:
            print("Available TTS providers:")
            for provider in available:
                print(f"  • {provider}")

        return 0
    except (KeyError, AttributeError, ValueError) as e:
        print(f"Error in providers command: {e}")
        return 1


def on_install(args: tuple, **kwargs) -> int:
    """Handle the install command"""
    try:
        import subprocess

        if not args:
            print("🔧 Voice Provider Installation")
            print("===========================")
            print()
            print("Available providers to install:")
            print("  • edge-tts        - Microsoft Edge voice (free)")
            print("  • openai          - OpenAI voice API")
            print("  • elevenlabs      - ElevenLabs voice API")
            print("  • google-tts      - Google Cloud voice API")
            print("  • chatterbox      - Local voice cloning")
            print()
            print("Usage: voice install <provider>")
            print("Example: voice install edge-tts")
            return 0

        provider = args[0].lower()

        # Provider installation mappings
        install_commands = {
            "edge-tts": ["pip", "install", "edge-tts"],
            "edge_tts": ["pip", "install", "edge-tts"],
            "openai": ["pip", "install", "openai"],
            "elevenlabs": ["pip", "install", "elevenlabs"],
            "google-tts": ["pip", "install", "google-cloud-texttospeech"],
            "google_tts": ["pip", "install", "google-cloud-texttospeech"],
            "chatterbox": ["pip", "install", "torch", "torchaudio", "transformers", "librosa"],
        }

        if provider not in install_commands:
            print(f"❌ Unknown provider: {provider}", file=sys.stderr)
            print("Available providers: edge-tts, openai, elevenlabs, google-tts, chatterbox", file=sys.stderr)
            raise ValueError(f"Unknown provider: {provider}")

        print(f"🔧 Installing {provider}...")
        print("=" * 40)

        try:
            # Special handling for chatterbox (multiple packages)
            if provider == "chatterbox":
                packages = ["torch", "torchaudio", "transformers", "librosa"]
                for package in packages:
                    print(f"📦 Installing {package}...")
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", package], capture_output=True, text=True
                    )

                    if result.returncode != 0:
                        print(f"❌ Failed to install {package}")
                        print(f"Error: {result.stderr}")
                        return 1
                    else:
                        print(f"✅ {package} installed successfully")
            else:
                # Single package installation
                cmd = install_commands[provider]
                print(f"📦 Running: {' '.join(cmd)}")

                result = subprocess.run(
                    [sys.executable, "-m"] + cmd[1:],  # Use current Python interpreter
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0:
                    print("❌ Installation failed")
                    print(f"Error: {result.stderr}")
                    return 1

            print(f"✅ {provider} installed successfully!")

            # Provide next steps
            if provider in ["openai", "elevenlabs", "google-tts", "google_tts"]:
                print("\n💡 Next steps:")
                if provider == "openai":
                    print("   Set your API key: voice config set openai_api_key YOUR_KEY")
                elif provider == "elevenlabs":
                    print("   Set your API key: voice config set elevenlabs_api_key YOUR_KEY")
                elif provider in ["google-tts", "google_tts"]:
                    print("   Set up authentication:")
                    print("   • API key: voice config set google_api_key YOUR_KEY")
                    print("   • Or service account: voice config set google_credentials_path /path/to/credentials.json")

            # Test the installation
            print(f"\n🧪 Testing {provider}...")
            engine = get_engine()
            test_result = engine.test_provider(provider.replace("-", "_"))

            if test_result.get("available", False):
                print(f"✅ {provider} is working correctly!")
            else:
                error = test_result.get("error", "Unknown error")
                print(f"⚠️  {provider} installed but not fully configured: {error}")

            return 0

        except subprocess.CalledProcessError as e:
            print(f"❌ Installation failed: {e}")
            return 1
        except (ImportError, OSError, RuntimeError) as e:
            print(f"❌ Unexpected error during installation: {e}")
            return 1

    except (ImportError, ValueError, KeyError) as e:
        print(f"Error in install command: {e}")
        return 1


def on_info(provider: Optional[str], **kwargs) -> int:
    """Handle the info command"""
    try:
        engine = get_engine()

        if provider:
            # Handle provider shortcuts
            resolved_provider = handle_provider_shortcuts(provider)

            if resolved_provider and resolved_provider.startswith("@"):
                shortcut = resolved_provider[1:]
                exit_with_message(
                    "\n".join(
                        [
                            f"Error: Unknown provider shortcut '@{shortcut}'",
                            f"Available providers: {', '.join('@' + k for k in PROVIDER_SHORTCUTS.keys())}",
                        ]
                    ),
                    exit_code=1,
                )

            provider_name = resolved_provider or provider

            # Use safe info method that handles authentication gracefully
            info = engine.get_provider_info_safe(provider_name)
            status = engine.get_provider_status(provider_name)

            # Determine status indicator
            if status["available"] and status["configured"]:
                status_icon = "✅"
                status_text = "Ready"
            elif status["available"] and not status["configured"]:
                status_icon = "🔑"
                status_text = "Needs API key"
            elif not status["installed"]:
                status_icon = "❌"
                status_text = "Not installed"
            elif status["error"]:
                status_icon = "⚠️"
                status_text = f"Warning: {status['error']}"
            else:
                status_icon = "❓"
                status_text = "Unknown status"

            print(f"📋 Provider: {provider_name} {status_icon}")
            print("=" * 40)
            print(f"🔄 Status: {status_text}")

            for key, value in info.items():
                if key == "name":
                    print(f"🏢 Name: {value}")
                elif key == "description":
                    print(f"📝 Description: {value}")
                elif key == "options":
                    print("⚙️  Options:")
                    for opt_key, opt_value in value.items():
                        print(f"   • {opt_key}: {opt_value}")
                elif key == "output_formats":
                    if isinstance(value, list):
                        print(f"🎵 Formats: {', '.join(value)}")
                    else:
                        print(f"🎵 Formats: {value}")
                elif key == "sample_voices":
                    if isinstance(value, list) and value:
                        print(f"🎤 Sample Voices ({len(value)}):")
                        for voice in value[:10]:  # Show first 10
                            print(f"   • {voice}")
                        if len(value) > 10:
                            print(f"   ... and {len(value) - 10} more")
                    else:
                        print("🎤 Sample Voices: None available")
                elif key == "capabilities":
                    if isinstance(value, list) and value:
                        print(f"⭐ Capabilities: {', '.join(value)}")
                elif key not in ["status", "error"]:  # Skip internal status fields
                    print(f"   {key}: {value}")

            # Show setup instructions for unconfigured providers
            if not status["configured"] and status["installed"]:
                print("\n💡 Setup Instructions:")
                api_key_name = engine._get_api_key_provider_name(provider_name)
                if provider_name == "openai_tts":
                    print(f"   Set API key: voice config set {api_key_name}_api_key YOUR_KEY")
                    print("   Get your key at: https://platform.openai.com/api-keys")
                elif provider_name == "elevenlabs":
                    print(f"   Set API key: voice config set {api_key_name}_api_key YOUR_KEY")
                    print("   Get your key at: https://elevenlabs.io/profile")
                elif provider_name == "google_tts":
                    print(f"   Option 1 - API key: voice config set {api_key_name}_api_key YOUR_KEY")
                    print(
                        f"   Option 2 - Service account: voice config set {api_key_name}_credentials_path "
                        "/path/to/credentials.json"
                    )
                    print("   Get credentials at: https://console.cloud.google.com/")

        else:
            # Show general info about all providers
            print("📋 TTS Provider Information")
            print("==========================")
            available = engine.get_available_providers()

            for provider_name in available:
                info = engine.get_provider_info_safe(provider_name)
                status = engine.get_provider_status(provider_name)

                # Determine status indicator
                if status["available"] and status["configured"]:
                    status_icon = "✅"
                elif status["available"] and not status["configured"]:
                    status_icon = "🔑"
                elif not status["installed"]:
                    status_icon = "❌"
                else:
                    status_icon = "⚠️"

                name = info.get("name", provider_name)
                description = info.get("description", "No description")
                print(f"\n{status_icon} {name}")
                print(f"   {description}")

                # Find shortcut
                shortcut = None
                for k, v in PROVIDER_SHORTCUTS.items():
                    if v == provider_name:
                        shortcut = k
                        break
                if shortcut:
                    print(f"   💡 Use: @{shortcut} or {provider_name}")
                else:
                    print(f"   💡 Use: {provider_name}")

            print("\n💡 Get detailed info: voice info <provider>")
            print("Example: voice info @edge")

        return 0
    except (KeyError, AttributeError, ValueError) as e:
        exit_with_message(f"Error in info command: {e}", exit_code=1)
