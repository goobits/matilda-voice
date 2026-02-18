#!/usr/bin/env python3
"""Hook handlers for TTS CLI."""

from typing import Any


def on_voice_load(voice_files: tuple[str, ...], **kwargs: Any) -> int:
    """Handle the voice load command"""
    try:
        from pathlib import Path

        from matilda_voice.voice_manager import VoiceManager

        if not voice_files:
            print("Error: No voice files specified")
            print("Usage: voice voice load <voice_file> [voice_file2] ...")
            return 1

        manager = VoiceManager()
        loaded_count = 0
        failed_count = 0

        for voice_file in voice_files:
            voice_path = Path(voice_file)

            # Check if file exists
            if not voice_path.exists():
                print(f"❌ Voice file not found: {voice_file}")
                failed_count += 1
                continue

            # Check if already loaded
            if manager.is_voice_loaded(str(voice_path)):
                print(f"ℹ️  Voice already loaded: {voice_path.name}")
                continue

            try:
                print(f"🔄 Loading voice: {voice_path.name}...")
                success = manager.load_voice(str(voice_path))

                if success:
                    print(f"✅ Successfully loaded: {voice_path.name}")
                    loaded_count += 1
                else:
                    print(f"❌ Failed to load: {voice_path.name}")
                    failed_count += 1

            except (IOError, OSError, ValueError) as e:
                print(f"❌ Error loading {voice_path.name}: {e}")
                failed_count += 1

        # Summary
        total = len(voice_files)
        print("\n📊 Voice Loading Summary:")
        print(f"   Total: {total}, Loaded: {loaded_count}, Failed: {failed_count}")

        # Show currently loaded voices
        loaded_voices = manager.get_loaded_voices()
        if loaded_voices:
            print(f"\n🎤 Currently Loaded Voices ({len(loaded_voices)}):")
            for voice_info in loaded_voices:
                voice_path = Path(voice_info["path"])
                print(f"   • {voice_path.name}")

        return 0 if failed_count == 0 else 1

    except (ImportError, IOError, OSError) as e:
        print(f"Error in voice load command: {e}")
        return 1


def on_voice_unload(voice_files: tuple[str, ...], all: bool, **kwargs: Any) -> int:
    """Handle the voice unload command"""
    try:
        from pathlib import Path

        from matilda_voice.voice_manager import VoiceManager

        manager = VoiceManager()

        # Handle unload all
        if all:
            try:
                print("🔄 Unloading all voices...")
                unloaded_count = manager.unload_all_voices()

                if unloaded_count > 0:
                    print(f"✅ Successfully unloaded {unloaded_count} voices")
                else:
                    print("ℹ️  No voices were loaded")

                return 0

            except (IOError, OSError, RuntimeError) as e:
                print(f"❌ Error unloading all voices: {e}")
                return 1

        # Handle specific voice files
        if not voice_files:
            print("Error: No voice files specified")
            print("Usage: voice voice unload <voice_file> [voice_file2] ...")
            print("       voice voice unload --all")
            return 1

        unloaded_count = 0
        failed_count = 0

        for voice_file in voice_files:
            voice_path = Path(voice_file)

            # Check if voice is loaded
            if not manager.is_voice_loaded(str(voice_path)):
                print(f"ℹ️  Voice not loaded: {voice_path.name}")
                continue

            try:
                print(f"🔄 Unloading voice: {voice_path.name}...")
                success = manager.unload_voice(str(voice_path))

                if success:
                    print(f"✅ Successfully unloaded: {voice_path.name}")
                    unloaded_count += 1
                else:
                    print(f"❌ Failed to unload: {voice_path.name}")
                    failed_count += 1

            except (IOError, OSError, ValueError) as e:
                print(f"❌ Error unloading {voice_path.name}: {e}")
                failed_count += 1

        # Summary
        total = len(voice_files)
        print("\n📊 Voice Unloading Summary:")
        print(f"   Total: {total}, Unloaded: {unloaded_count}, Failed: {failed_count}")

        # Show remaining loaded voices
        loaded_voices = manager.get_loaded_voices()
        if loaded_voices:
            print(f"\n🎤 Still Loaded Voices ({len(loaded_voices)}):")
            for voice_info in loaded_voices:
                voice_path = Path(voice_info["path"])
                print(f"   • {voice_path.name}")
        else:
            print("\n✨ No voices currently loaded")

        return 0 if failed_count == 0 else 1

    except (ImportError, IOError, OSError) as e:
        print(f"Error in voice unload command: {e}")
        return 1


def on_voice_status(**kwargs: Any) -> int:
    """Handle the voice status command"""
    try:
        from pathlib import Path

        from matilda_voice.voice_manager import VoiceManager

        manager = VoiceManager()

        print("🎤 Voice Manager Status")
        print("======================")

        # Check if server is running
        if manager._is_server_running():
            print("✅ Chatterbox server: Running")
            print(f"🌐 Server address: {manager.server_host}:{manager.server_port}")
        else:
            print("❌ Chatterbox server: Not running")
            print("💡 Server will start automatically when loading voices")

        # Get loaded voices
        loaded_voices = manager.get_loaded_voices()

        if not loaded_voices:
            print("\n📭 No voices currently loaded")
            print("💡 Use 'voice voice load <voice_file>' to load voices for fast synthesis")
        else:
            print(f"\n🎤 Loaded Voices ({len(loaded_voices)}):")
            print("   " + "=" * 50)

            for i, voice_info in enumerate(loaded_voices, 1):
                voice_path = Path(voice_info["path"])
                print(f"   {i}. {voice_path.name}")
                print(f"      📁 Path: {voice_path}")

                # Show file size if available
                if voice_path.exists():
                    size_mb = voice_path.stat().st_size / (1024 * 1024)
                    print(f"      📏 Size: {size_mb:.1f} MB")
                else:
                    print("      ⚠️  File not found at original location")

                # Show additional info if available
                if "loaded_at" in voice_info:
                    print(f"      ⏰ Loaded: {voice_info['loaded_at']}")

                print()  # Empty line between voices

        # Show memory usage hint
        if loaded_voices:
            print("💡 Tips:")
            print("   • Use 'voice voice unload <voice_file>' to free memory")
            print("   • Use 'voice voice unload --all' to unload all voices")
            print("   • Loaded voices provide faster synthesis with Chatterbox")

        return 0

    except (ImportError, IOError, OSError, AttributeError) as e:
        print(f"Error in voice status command: {e}")
        return 1
