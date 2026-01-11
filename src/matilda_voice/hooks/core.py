#!/usr/bin/env python3
"""Hook handlers for TTS CLI."""

import sys
from typing import Any, Dict, Optional

from .utils import (
    PROVIDER_SHORTCUTS,
    get_engine,
    parse_provider_shortcuts,
)
from matilda_voice.speech_synthesis.ssml.generator import SSMLGenerator, SSMLPlatform


def on_speak(
    text: Optional[str],
    options: tuple,
    voice: Optional[str],
    rate: Optional[str],
    pitch: Optional[str],
    debug: bool,
    ssml: bool = False,
    **kwargs,
) -> int:
    """Handle the speak command"""
    try:
        # Parse provider shortcuts from text and options
        provider_name = None
        all_args = []

        # Collect all arguments
        if text:
            all_args.append(text)
        if options:
            all_args.extend(options)

        # Check if first argument is a provider shortcut
        if all_args and all_args[0].startswith("@"):
            provider_name, remaining_args = parse_provider_shortcuts(all_args)
            # Handle invalid shortcuts
            if provider_name and provider_name.startswith("@"):
                shortcut = provider_name[1:]
                print(f"Error: Unknown provider shortcut '@{shortcut}'", file=sys.stderr)
                print(f"Available providers: {', '.join('@' + k for k in PROVIDER_SHORTCUTS.keys())}", file=sys.stderr)
                raise ValueError(f"Unknown provider shortcut '@{shortcut}'")
            all_args = remaining_args

        # Parse any additional text from remaining arguments
        all_text = all_args

        if not all_text:
            # If no text provided, try to read from stdin
            if not sys.stdin.isatty():
                try:
                    text_input = sys.stdin.read().strip()
                    if text_input:
                        all_text.append(text_input)
                except (BrokenPipeError, IOError):
                    # Stdin was closed (e.g., in a pipeline that was interrupted)
                    # Exit gracefully without error message
                    return 0

        if not all_text:
            print("Error: No text provided to speak")
            return 1

        final_text = " ".join(all_text)

        # Convert to SSML if requested
        if ssml:
            generator = SSMLGenerator(SSMLPlatform.AZURE)  # Edge TTS uses Azure SSML
            final_text = generator.convert_speech_markdown(final_text)
            if debug:
                print(f"Generated SSML:\n{final_text}", file=sys.stderr)

        # Get TTS engine and synthesize
        engine = get_engine()

        # Create output parameters
        output_params: Dict[str, Any] = {
            "stream": True,  # For speaking, we want to stream to speakers
            "debug": debug,
        }

        if rate:
            output_params["rate"] = rate
        if pitch:
            output_params["pitch"] = pitch

        # Synthesize the text
        result = engine.synthesize_text(
            text=final_text,
            voice=voice,
            provider_name=provider_name,
            output_path=None,  # None means stream to speakers
            **output_params,
        )

        return 0 if result else 1

    except KeyboardInterrupt:
        # Clean shutdown on Ctrl+C
        return 0
    except BrokenPipeError:
        # Exit gracefully when output pipe is broken
        return 0
    except IOError as e:
        # Check if it's a broken pipe error
        import errno

        if e.errno == errno.EPIPE:
            return 0
        # Re-raise other IO errors
        raise
    except Exception:
        # Re-raise to let CLI handle it with user-friendly messages
        raise


def on_save(
    text: Optional[str],
    options: tuple,
    output: Optional[str],
    format: Optional[str],
    voice: Optional[str],
    json: bool,
    debug: bool,
    rate: Optional[str],
    pitch: Optional[str],
    ssml: bool = False,
    **kwargs,
) -> int:
    """Handle the save command"""
    try:
        # Parse provider shortcuts from text and options
        provider_name = None
        all_args = []

        # Collect all arguments
        if text:
            all_args.append(text)
        if options:
            all_args.extend(options)

        # Check if first argument is a provider shortcut
        if all_args and all_args[0].startswith("@"):
            provider_name, remaining_args = parse_provider_shortcuts(all_args)
            # Handle invalid shortcuts
            if provider_name and provider_name.startswith("@"):
                shortcut = provider_name[1:]
                print(f"Error: Unknown provider shortcut '@{shortcut}'", file=sys.stderr)
                print(f"Available providers: {', '.join('@' + k for k in PROVIDER_SHORTCUTS.keys())}", file=sys.stderr)
                raise ValueError(f"Unknown provider shortcut '@{shortcut}'")
            all_args = remaining_args

        # Parse any additional text from remaining arguments
        all_text = all_args

        if not all_text:
            print("Error: No text provided to save")
            return 1

        final_text = " ".join(all_text)

        # Convert to SSML if requested
        if ssml:
            generator = SSMLGenerator(SSMLPlatform.AZURE)  # Edge TTS uses Azure SSML
            final_text = generator.convert_speech_markdown(final_text)
            if debug:
                print(f"Generated SSML:\n{final_text}", file=sys.stderr)

        # Default output filename if not provided
        if not output:
            output = "output.mp3"

        # Get TTS engine and synthesize
        engine = get_engine()

        # Create output parameters
        output_params: Dict[str, Any] = {
            "stream": False,  # For saving, we don't stream
            "debug": debug,
        }

        if rate:
            output_params["rate"] = rate
        if pitch:
            output_params["pitch"] = pitch
        if format:
            output_params["format"] = format

        # Synthesize the text
        result = engine.synthesize_text(
            text=final_text, voice=voice, provider_name=provider_name, output_path=output, **output_params
        )

        if result:
            print(f"Audio saved to: {output}")
            return 0
        else:
            return 1

    except Exception:
        # Re-raise to let CLI handle it with user-friendly messages
        raise
