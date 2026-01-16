"""
HTTP server for TTS (Text-to-Speech) API.

Exposes TTS functionality over HTTP for Matilda integration.
Supports text-to-speech synthesis with provider/voice selection.

Usage:
    voice serve --port 8771

    # Or directly:
    python -m matilda_voice.server --port 8771
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import secrets
import tempfile

from aiohttp import web
from aiohttp.web import Request, Response

from .internal.security import get_allowed_origins
from .internal.token_storage import get_or_create_token
from matilda_transport import ensure_pipe_supported, prepare_unix_socket, resolve_transport

logger = logging.getLogger(__name__)

# Security: API Token Management
API_TOKEN = get_or_create_token()


@web.middleware
async def auth_middleware(request: Request, handler):
    """Middleware to enforce token authentication."""
    # Allow public endpoints
    if request.path in ["/", "/health", "/providers"]:
        return await handler(request)

    # Allow CORS preflight options
    if request.method == "OPTIONS":
        return await handler(request)

    # Check Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return add_cors_headers(
            web.json_response({"error": "Unauthorized: Missing or invalid Authorization header"}, status=401), request
        )

    token = auth_header.split(" ")[1]
    if not secrets.compare_digest(token, API_TOKEN):
        return add_cors_headers(web.json_response({"error": "Forbidden: Invalid token"}, status=403), request)

    return await handler(request)


# CORS headers for browser/cross-origin access
ALLOWED_ORIGINS = get_allowed_origins()


def add_cors_headers(response: Response, request: Request = None) -> Response:
    """Add CORS headers to response.

    Only sets Access-Control-Allow-Origin when:
    1. A request with Origin header is present, AND
    2. That origin is in the allowed list

    If no origins are configured or the origin is not allowed,
    the CORS header is not set (browser will block the request).
    """
    # Always set these headers for CORS support
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"

    # Only set Allow-Origin if request has Origin and it's in allowed list
    if request:
        req_origin = request.headers.get("Origin")
        if req_origin and ALLOWED_ORIGINS and req_origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = req_origin

    return response


async def handle_options(request: Request) -> Response:
    """Handle CORS preflight requests."""
    return add_cors_headers(Response(status=200), request)


async def handle_health(request: Request) -> Response:
    """Health check endpoint."""
    return add_cors_headers(web.json_response({"status": "ok", "service": "voice"}), request)


async def handle_speak(request: Request) -> Response:
    """
    Synthesize and play text-to-speech.

    POST /speak
    {
        "text": "Hello world",
        "voice": "edge_tts:en-US-AriaNeural",  // optional
        "provider": "edge_tts"                  // optional (inferred from voice)
    }

    Response:
    {
        "success": true,
        "text": "Hello world",
        "voice": "edge_tts:en-US-AriaNeural"
    }
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return add_cors_headers(web.json_response({"error": "Invalid JSON"}, status=400), request)

    text = data.get("text")
    if not text:
        return add_cors_headers(web.json_response({"error": "Missing 'text' field"}, status=400), request)

    voice = data.get("voice")
    provider = data.get("provider")

    try:
        # Import here to avoid circular imports
        from .app_hooks import on_speak

        # Run synthesis (this plays audio)
        loop = asyncio.get_event_loop()
        options = ()
        text_arg = text
        if provider:
            shortcut = provider if provider.startswith("@") else f"@{provider}"
            options = (shortcut, text)
            text_arg = None
        await loop.run_in_executor(
            None,
            lambda: on_speak(
                text=text_arg,
                options=options,
                voice=voice,
                rate=None,
                pitch=None,
                debug=False,
                ssml=False,
            ),
        )

        result = {
            "success": True,
            "text": text,
            "voice": voice,
        }
        return add_cors_headers(web.json_response(result), request)

    except Exception as e:
        logger.exception("Failed to handle speak request")
        return add_cors_headers(web.json_response({"error": str(e)}, status=500), request)


async def handle_synthesize(request: Request) -> Response:
    """
    Synthesize text and return audio data (no playback).

    POST /synthesize
    {
        "text": "Hello world",
        "voice": "edge_tts:en-US-AriaNeural",  // optional
        "provider": "edge_tts",                 // optional
        "format": "wav"                         // optional: wav, mp3
    }

    Response:
    {
        "success": true,
        "audio": "<base64-encoded audio>",
        "format": "wav",
        "text": "Hello world"
    }
    """
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return add_cors_headers(web.json_response({"error": "Invalid JSON"}, status=400), request)

    text = data.get("text")
    if not text:
        return add_cors_headers(web.json_response({"error": "Missing 'text' field"}, status=400), request)

    voice = data.get("voice")
    provider = data.get("provider")
    audio_format = data.get("format", "wav")

    try:
        from .app_hooks import on_save

        # Create temp file for audio
        with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Run synthesis to file
            loop = asyncio.get_event_loop()
            options = ()
            text_arg = text
            if provider:
                shortcut = provider if provider.startswith("@") else f"@{provider}"
                options = (shortcut, text)
                text_arg = None
            await loop.run_in_executor(
                None,
                lambda: on_save(
                    text=text_arg,
                    options=options,
                    output=tmp_path,
                    voice=voice,
                    format=audio_format,
                    json=False,
                    debug=False,
                    rate=None,
                    pitch=None,
                    ssml=False,
                ),
            )

            # Read audio file and encode as base64
            with open(tmp_path, "rb") as f:
                audio_data = f.read()
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")

            result = {
                "success": True,
                "audio": audio_base64,
                "format": audio_format,
                "text": text,
                "size_bytes": len(audio_data),
            }
            return add_cors_headers(web.json_response(result), request)

        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        logger.exception("Failed to handle synthesize request")
        return add_cors_headers(web.json_response({"error": str(e)}, status=500), request)


async def handle_providers(request: Request) -> Response:
    """
    List available TTS providers.

    GET /providers

    Response:
    {
        "providers": ["edge_tts", "openai", "elevenlabs", ...]
    }
    """
    try:
        from .app_hooks import PROVIDERS_REGISTRY

        providers = list(PROVIDERS_REGISTRY.keys())
        return add_cors_headers(web.json_response({"providers": providers}), request)

    except Exception as e:
        logger.exception("Failed to list providers")
        return add_cors_headers(web.json_response({"error": str(e)}, status=500), request)


async def handle_reload(request: Request) -> Response:
    """
    Reload configuration from disk.

    POST /reload

    Response:
    {"status": "ok", "message": "Configuration reloaded"}
    """
    try:
        from .internal.config import reload_config

        # Clear configuration cache
        reload_config()

        logger.info("Configuration reloaded via API")
        return add_cors_headers(web.json_response({"status": "ok", "message": "Configuration reloaded"}), request)
    except Exception as e:
        logger.exception("Error reloading configuration")
        return add_cors_headers(web.json_response({"error": str(e)}, status=500), request)


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application(middlewares=[auth_middleware])

    # Routes
    app.router.add_route("OPTIONS", "/{path:.*}", handle_options)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_health)
    app.router.add_post("/speak", handle_speak)
    app.router.add_post("/synthesize", handle_synthesize)
    app.router.add_post("/reload", handle_reload)

    return app


def run_server(host: str = "0.0.0.0", port: int = 8771):
    """Run the HTTP server."""
    app = create_app()
    transport = resolve_transport("MATILDA_VOICE_TRANSPORT", "MATILDA_VOICE_ENDPOINT", host, port)

    print(f"Starting Voice server on http://{host}:{port}")
    print("  POST /speak      - Synthesize and play audio")
    print("  POST /synthesize - Synthesize and return audio data")
    print("  GET  /providers  - List available providers")
    print("  GET  /health     - Health check")
    print()

    if transport.transport == "unix" and transport.endpoint:
        prepare_unix_socket(transport.endpoint)
        web.run_app(app, path=transport.endpoint, print=None)
        return
    if transport.transport == "pipe":
        ensure_pipe_supported(transport)
        async def run_pipe():
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.NamedPipeSite(runner, transport.endpoint)
            await site.start()
            await asyncio.Event().wait()

        asyncio.run(run_pipe())
        return

    web.run_app(app, host=transport.host, port=transport.port, print=None)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Voice TTS HTTP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", "-p", type=int, default=8771, help="Port to listen on")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
