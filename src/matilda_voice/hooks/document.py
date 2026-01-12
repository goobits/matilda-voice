#!/usr/bin/env python3
"""Hook handlers for TTS CLI."""

from typing import Any, Dict, Optional

from .utils import exit_with_message, get_engine


def on_document(
    document_path: str,
    options: tuple,
    save: bool,
    output: Optional[str],
    format: Optional[str],
    voice: Optional[str],
    json: bool,
    debug: bool,
    doc_format: str,
    ssml_platform: str,
    emotion_profile: str,
    rate: Optional[str],
    pitch: Optional[str],
    **kwargs,
) -> int:
    """Handle the document command"""
    try:
        from pathlib import Path

        from matilda_voice.document_processing.parser_factory import DocumentParserFactory

        if not document_path:
            exit_with_message("Error: Document path is required", exit_code=2, show_usage=True)

        # Check if document file exists
        doc_file = Path(document_path)
        if not doc_file.exists():
            print(f"Error: Document file not found: {document_path}")
            return 1

        # Read document content
        try:
            content = doc_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"Error: Unable to read document as UTF-8: {document_path}")
            return 1

        # Parse document using factory
        factory = DocumentParserFactory()
        semantic_elements = factory.parse_document(content=content, filename=document_path, format_override=doc_format)

        if not semantic_elements:
            print("Warning: No content found in document")
            return 1

        # Extract text from semantic elements
        text_parts = []
        for element in semantic_elements:
            if hasattr(element, "content") and element.content:
                text_parts.append(element.content)

        if not text_parts:
            print("Warning: No text content extracted from document")
            return 1

        final_text = " ".join(text_parts)

        if debug:
            print(f"Extracted {len(semantic_elements)} elements")
            print(f"Text length: {len(final_text)} characters")

        # Get TTS engine and synthesize
        engine = get_engine()

        # Create output parameters
        output_params: Dict[str, Any] = {"debug": debug}

        if rate:
            output_params["rate"] = rate
        if pitch:
            output_params["pitch"] = pitch
        if format:
            output_params["format"] = format

        # Determine if we should save or stream
        if save or output:
            # Save mode
            if not output:
                # Generate output filename based on input
                output = doc_file.with_suffix(".mp3").name

            output_params["stream"] = False
            result = engine.synthesize_text(text=final_text, voice=voice, output_path=output, **output_params)

            if result:
                print(f"Document audio saved to: {output}")
                return 0
            else:
                return 1
        else:
            # Stream mode (default)
            output_params["stream"] = True
            result = engine.synthesize_text(text=final_text, voice=voice, output_path=None, **output_params)

            return 0 if result else 1

    except Exception:
        # Re-raise to let CLI handle it with user-friendly messages
        raise
