"""
Pytest configuration and fixtures for TTS CLI tests.

This module provides selective mocking infrastructure to isolate tests
from external dependencies while preserving provider business logic:
- Network-only mocking of HTTP requests and API calls
- Audio environment mocking (PyAudio devices, ffmpeg)
- File system operations
- Configuration directory

Design: Uses real provider classes with mocked external dependencies,
preserving provider logic while avoiding network/hardware dependencies.
"""

import json
import os
import shutil
import socket
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import toml

from matilda_voice.base import TTSProvider
from matilda_voice.internal.types import Config, ProviderInfo


def provider_available() -> bool:
    """Check if any real TTS provider is available for testing."""
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        return False

    # Quick check for Edge TTS (most reliable free provider)
    import importlib.util

    if importlib.util.find_spec("edge_tts") is not None:
        return True

    # Check for other providers via environment variables
    api_keys = ["OPENAI_API_KEY", "ELEVENLABS_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"]

    return any(os.getenv(key) for key in api_keys)


# Import network-only mocking infrastructure (selective imports)
# Note: These imports were removed as they were unused in the codebase


# ==============================================================================
# AUDIO ENVIRONMENT MOCKS
# ==============================================================================


@pytest.fixture
def mock_audio_environment(monkeypatch):
    """Mock audio environment to avoid PyAudio initialization."""

    # Mock check_audio_environment function
    def mock_check_audio_env() -> Dict[str, Any]:
        return {
            "available": True,
            "reason": "Mock audio environment",
            "pulse_available": True,
            "alsa_available": True,
        }

    # Apply mock
    monkeypatch.setattr("matilda_voice.internal.audio_utils.check_audio_environment", mock_check_audio_env)

    return mock_check_audio_env


@pytest.fixture
def mock_audio_playback(monkeypatch):
    """Mock audio playback functions."""

    # Mock subprocess calls for ffplay
    mock_popen = MagicMock()
    mock_popen.wait.return_value = 0
    mock_popen.returncode = 0
    mock_popen.poll.return_value = 0

    def mock_subprocess_popen(*args, **kwargs):
        # Track the command being run
        if args and args[0] and "ffplay" in args[0][0]:
            mock_popen.command = args[0]
        return mock_popen

    monkeypatch.setattr("subprocess.Popen", mock_subprocess_popen)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MagicMock(returncode=0))
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")

    return mock_popen


@pytest.fixture
def mock_audio_conversion(monkeypatch):
    """Mock audio conversion functions."""

    def mock_convert_with_cleanup(input_path: str, output_path: str, output_format: str) -> None:
        """Mock audio conversion that copies the input file to output."""
        input_file = Path(input_path)
        output_file = Path(output_path)

        # Create output directory if needed
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Copy the input file to output (simulating conversion)
        if input_file.exists():
            import shutil

            shutil.copy2(input_path, output_path)
        else:
            # Create a mock file if input doesn't exist
            with open(output_path, "wb") as f:
                f.write(b"mock converted audio data")

    def mock_convert_audio(input_path: str, output_path: str, target_format: str = "mp3") -> None:
        """Mock convert_audio function."""
        mock_convert_with_cleanup(input_path, output_path, target_format)

    # Mock both conversion functions
    monkeypatch.setattr("matilda_voice.internal.audio_utils.convert_with_cleanup", mock_convert_with_cleanup)
    monkeypatch.setattr("matilda_voice.internal.audio_utils.convert_audio", mock_convert_audio)

    return mock_convert_with_cleanup


# ==============================================================================
# CONFIGURATION FIXTURES
# ==============================================================================


@pytest.fixture
def test_safe_environment(monkeypatch):
    """Create a minimal test environment that only sets environment variables.

    This fixture sets TEST_MODE environment variables to bypass API key validation
    and other external checks without using mocking. It's the most minimal approach
    for fixing tests while using real code paths.
    """
    # Set TEST_MODE environment variable
    monkeypatch.setenv("TTS_TEST_MODE", "true")

    # Set valid test API keys as environment variables
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test1234567890abcdefghijklmnopqrstuvwxyz12345678")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "abcdef0123456789abcdef0123456789")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSyD-test1234567890abcdefghijklmnopq")

    # Return the environment settings for inspection if needed
    return {
        "test_mode": True,
        "openai_key": "sk-test1234567890abcdefghijklmnopqrstuvwxyz12345678",
        "elevenlabs_key": "abcdef0123456789abcdef0123456789",
        "google_key": "AIzaSyD-test1234567890abcdefghijklmnopq",
    }


@pytest.fixture
def test_config_factory():
    """Factory for creating test configuration data with customizable options."""

    def _create_config(
        include_api_keys: bool = True,
        provider: str = "edge_tts",
        voice: str = "en-US-AvaNeural",
        output_format: str = "mp3",
        custom_settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create test configuration data.

        Args:
            include_api_keys: Whether to include API keys in config
            provider: Default provider to use
            voice: Default voice to use
            output_format: Default output format
            custom_settings: Additional custom settings to include

        Returns:
            Configuration dictionary
        """
        base_config = {
            "default_voice": voice,
            "default_provider": provider,
            "output_format": output_format,
        }

        if include_api_keys:
            base_config.update(
                {
                    "openai_api_key": "sk-test1234567890abcdefghijklmnopqrstuvwxyz12345678",
                    "elevenlabs_api_key": "abcdef0123456789abcdef0123456789",
                    "google_cloud_api_key": "AIzaSyD-test1234567890abcdefghijklmnopq",
                }
            )

        if custom_settings:
            base_config.update(custom_settings)

        return base_config

    return _create_config


@pytest.fixture
def requires_providers():
    """Fixture that skips tests if no providers are available."""
    if not provider_available():
        pytest.skip("No TTS providers available for testing")


# Pytest markers
def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line("markers", "requires_providers: mark test to require actual TTS providers")
    config.addinivalue_line("markers", "requires_credentials: mark test to require API credentials")


def pytest_collection_modifyitems(config, items):
    """Deselect tests based on environment conditions.

    This hook checks for marker-based requirements and deselects tests
    that cannot run in the current environment. This provides cleaner
    output than runtime skips - tests show as "deselected" rather than "skipped".
    """
    # Check environment conditions once
    is_ci = os.getenv("CI") or os.getenv("GITHUB_ACTIONS")
    has_elevenlabs = bool(os.getenv("ELEVENLABS_API_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_google = bool(os.getenv("GOOGLE_CLOUD_API_KEY") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

    # Check for chatterbox library
    try:
        import chatterbox  # noqa: F401

        has_chatterbox = True
    except ImportError:
        has_chatterbox = False

    def _network_available() -> bool:
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=1):
                return True
        except OSError:
            return False

    allow_network_skips = os.getenv("VOICE_ALLOW_NETWORK_SKIPS") == "1"
    has_network = _network_available()

    # Check for any real provider availability
    has_any_provider = False
    if not is_ci:
        try:
            import edge_tts  # noqa: F401

            has_any_provider = True
        except ImportError:
            pass
        if not has_any_provider:
            has_any_provider = has_elevenlabs or has_openai or has_google

    # Collect items to deselect
    deselected = []
    selected = []

    for item in items:
        # Check each marker condition
        should_deselect = False

        if item.get_closest_marker("requires_ci_skip") and is_ci:
            should_deselect = True
        elif item.get_closest_marker("requires_chatterbox") and not has_chatterbox:
            should_deselect = True
        elif item.get_closest_marker("requires_elevenlabs") and not has_elevenlabs:
            should_deselect = True
        elif item.get_closest_marker("requires_openai") and not has_openai:
            should_deselect = True
        elif item.get_closest_marker("requires_google") and not has_google:
            should_deselect = True
        elif item.get_closest_marker("requires_network") and not has_network:
            if allow_network_skips:
                should_deselect = True
            else:
                raise pytest.UsageError(
                    "Network is required for tests marked requires_network. "
                    "Set VOICE_ALLOW_NETWORK_SKIPS=1 to deselect these tests."
                )
        elif item.get_closest_marker("requires_credentials") and not (has_elevenlabs or has_openai or has_google):
            should_deselect = True
        elif item.get_closest_marker("requires_providers") and not has_any_provider:
            should_deselect = True

        if should_deselect:
            deselected.append(item)
        else:
            selected.append(item)

    # Update the items list and report deselections
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch, test_config_factory):
    """Create an isolated configuration directory for testing with full config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Create a test config file with comprehensive settings
    config_file = config_dir / "config.toml"
    config_data = test_config_factory(
        include_api_keys=True,
        custom_settings={
            "output_directory": str(tmp_path / "output"),
            "auto_provider_selection": True,
            "voice_loading_enabled": True,
            "http_streaming_chunk_size": 1024,
            "streaming_progress_interval": 100,
            "ffmpeg_conversion_timeout": 300,
            "ffplay_timeout": 120,
            "thread_pool_max_workers": 4,
            "browser_page_size": 20,
            "browser_preview_text": "Hello, this is a test.",
        },
    )

    with open(config_file, "w") as f:
        f.write(toml.dumps({"voice": config_data}))

    # Mock XDG config directory
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # Mock the get_config_path function to return our test config file
    monkeypatch.setattr("matilda_voice.internal.config.get_config_path", lambda: config_file)

    # Create output directory
    (tmp_path / "output").mkdir(exist_ok=True)

    return config_dir


@pytest.fixture
def mock_config(isolated_config_dir, monkeypatch):
    """Mock configuration with test values."""

    test_config: Config = {
        "default_voice": "en-US-AvaNeural",
        "default_provider": "edge_tts",
        "output_format": "mp3",
        "output_directory": str(isolated_config_dir.parent / "output"),
        "openai_api_key": "sk-test1234567890abcdefghijklmnopqrstuvwxyz12345678",
        "elevenlabs_api_key": "abcdef0123456789abcdef0123456789",
        "google_cloud_api_key": "AIzaSyD-test1234567890abcdefghijklmnopq",
        "auto_provider_selection": True,
        "voice_loading_enabled": True,
        "http_streaming_chunk_size": 1024,
        "streaming_progress_interval": 100,
        "ffmpeg_conversion_timeout": 300,
        "ffplay_timeout": 120,
        "thread_pool_max_workers": 4,
        "browser_page_size": 20,
        "browser_preview_text": "Hello, this is a test.",
    }

    def mock_load_config():
        return test_config.copy()

    def mock_get_config_value(key: str, default: Any = None) -> Any:
        return test_config.get(key, default)

    def mock_set_setting(key: str, value: Any) -> bool:
        test_config[key] = value
        return True

    def mock_get_setting(key: str, default: Any = None) -> Any:
        return test_config.get(key, default)

    monkeypatch.setattr("matilda_voice.internal.config.load_config", mock_load_config)
    monkeypatch.setattr("matilda_voice.internal.config.get_config_value", mock_get_config_value)
    monkeypatch.setattr("matilda_voice.internal.config.set_setting", mock_set_setting)
    monkeypatch.setattr("matilda_voice.internal.config.get_setting", mock_get_setting)

    return test_config


# ==============================================================================
# SELECTIVE MOCKING FIXTURES
# ==============================================================================


@pytest.fixture
def mock_selective_imports():
    """Mock only problematic imports while preserving provider loading logic."""

    # Mock only the heavy external dependencies that cause import issues
    # while keeping the actual provider classes and logic intact

    mocks = {}

    # Mock edge-tts async operations that can cause issues in test environment
    try:
        mock_edge_module = MagicMock()
        mock_edge_module.Communicate = MagicMock()
        mock_edge_module.list_voices = AsyncMock(
            return_value=[
                {"Name": "en-US-AvaNeural", "ShortName": "en-US-AvaNeural", "Gender": "Female"},
                {"Name": "en-GB-SoniaNeural", "ShortName": "en-GB-SoniaNeural", "Gender": "Female"},
            ]
        )
        mocks["edge_tts"] = mock_edge_module
    except ImportError:
        pass

    # Don't mock the actual provider modules - let them load normally
    # The network mocking will handle external calls

    yield mocks


# ==============================================================================
# UNIFIED MOCK BACKEND INFRASTRUCTURE
# ==============================================================================


class MockBackend:
    """
    Unified mock backend infrastructure for TTS provider testing.

    This class consolidates all mock provider functionality into a single,
    configurable backend that can simulate different provider behaviors.
    """

    def __init__(self, provider_type: str = "generic", name: str = "mock_provider"):
        """
        Initialize mock backend for a specific provider type.

        Args:
            provider_type: Type of provider ("generic", "edge_tts", "openai", "elevenlabs", "google")
            name: Provider name for identification
        """
        self.provider_type = provider_type
        self.name = name
        self.synthesize_called = False
        self.last_text = None
        self.last_output_path = None
        self.last_kwargs = {}
        self._call_history = []

    def create_tts_provider(self) -> "MockTTSProvider":
        """Create a mock TTS provider instance."""
        return MockTTSProvider(self)

    def create_communicate_class(self):
        """Create a mock Communicate class for edge-tts."""
        backend = self

        class MockCommunicate:
            def __init__(self, text, voice, **kwargs):
                self.text = text
                self.voice = voice
                backend._record_call("communicate_init", {"text": text, "voice": voice, **kwargs})

            async def save(self, output_path):
                """Mock save method that creates a real audio file."""
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # Create provider-specific mock audio content
                content = backend._get_mock_audio_content()
                with open(output_path, "wb") as f:
                    f.write(content)
                backend._record_call("save", {"output_path": str(output_path)})

            def stream(self):
                """Mock async generator for streaming."""

                async def _stream():
                    chunks = backend._get_stream_chunks()
                    for chunk in chunks:
                        yield chunk

                backend._record_call("stream", {})
                return _stream()

        return MockCommunicate

    def create_openai_client(self):
        """Create a mock OpenAI client."""
        backend = self

        class MockOpenAIResponse:
            def __init__(self, content=None):
                self.content = content or backend._get_mock_audio_content()

            def stream_to_file(self, path):
                """Mock stream_to_file method."""
                with open(path, "wb") as f:
                    f.write(self.content)
                backend._record_call("stream_to_file", {"path": str(path)})

            def iter_bytes(self, chunk_size=1024):
                """Mock iter_bytes method for streaming."""
                for i in range(0, len(self.content), chunk_size):
                    yield self.content[i : i + chunk_size]

        class MockOpenAIAudio:
            def __init__(self):
                self.speech = self

            def create(self, **kwargs):
                """Mock OpenAI audio.speech.create method."""
                backend._record_call("openai_create", kwargs)
                return MockOpenAIResponse()

        class MockOpenAIClient:
            def __init__(self, **kwargs):
                self.audio = MockOpenAIAudio()
                backend._record_call("openai_client_init", kwargs)

        return MockOpenAIClient

    def _get_mock_audio_content(self) -> bytes:
        """Get provider-specific mock audio content."""
        provider_content = {
            "edge_tts": b"mock edge-tts audio data with sufficient content for testing",
            "openai": b"mock openai audio content",
            "elevenlabs": b"mock elevenlabs audio content",
            "google": b"mock google tts audio content",
            "generic": b"mock audio data",
        }
        return provider_content.get(self.provider_type, provider_content["generic"])

    def _get_stream_chunks(self) -> List[Dict[str, Any]]:
        """Get mock streaming chunks."""
        return [
            {"type": "audio", "data": b"chunk1"},
            {"type": "audio", "data": b"chunk2"},
            {"type": "audio", "data": b"chunk3"},
        ]

    def _record_call(self, method: str, args: Dict[str, Any]) -> None:
        """Record method calls for testing verification."""
        self._call_history.append({"method": method, "args": args})

    def get_call_history(self) -> List[Dict[str, Any]]:
        """Get recorded call history."""
        return self._call_history.copy()

    def reset_call_history(self) -> None:
        """Reset call history."""
        self._call_history.clear()


class MockTTSProvider(TTSProvider):
    """Unified mock TTS provider backed by MockBackend."""

    def __init__(self, backend: MockBackend):
        self.backend = backend
        self.name = backend.name

    def synthesize(self, text: str, output_path: Optional[str], **kwargs: Any) -> None:
        """Mock synthesize method that tracks calls."""
        self.backend.synthesize_called = True
        self.backend.last_text = text
        self.backend.last_output_path = output_path
        self.backend.last_kwargs = kwargs
        self.backend._record_call("synthesize", {"text": text, "output_path": output_path, **kwargs})

        # If output_path is provided, create a dummy file
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(self.backend._get_mock_audio_content())

    def get_info(self) -> Optional[ProviderInfo]:
        """Return mock provider info."""
        provider_samples = {
            "edge_tts": ["en-US-AvaNeural", "en-GB-SoniaNeural"],
            "openai": ["alloy", "echo", "fable"],
            "elevenlabs": ["Rachel", "Domi"],
            "google": ["en-US-Standard-A", "en-US-Standard-B"],
            "generic": ["mock-voice-1", "mock-voice-2"],
        }

        return {
            "name": self.backend.name,
            "ShortName": self.backend.name.lower().replace(" ", "_"),
            "description": f"Mock {self.backend.name} provider for testing",
            "options": {"voice": "Mock voice selection"},
            "output_formats": ["mp3", "wav"],
            "sample_voices": provider_samples.get(self.backend.provider_type, provider_samples["generic"]),
            "capabilities": ["stream", "save"],
        }


# ==============================================================================
# MOCK BACKEND FIXTURES
# ==============================================================================


@pytest.fixture
def mock_backend():
    """Create a generic mock backend for testing."""
    return MockBackend()


@pytest.fixture
def mock_edge_tts_backend():
    """Create an edge-tts specific mock backend."""
    return MockBackend("edge_tts", "edge_tts")


@pytest.fixture
def mock_openai_backend():
    """Create an OpenAI specific mock backend."""
    return MockBackend("openai", "openai_tts")


@pytest.fixture
def mock_elevenlabs_backend():
    """Create an ElevenLabs specific mock backend."""
    return MockBackend("elevenlabs", "elevenlabs")


@pytest.fixture
def mock_google_backend():
    """Create a Google TTS specific mock backend."""
    return MockBackend("google", "google_tts")


# Legacy compatibility - provide the old MockTTSProvider interface
@pytest.fixture
def mock_tts_provider():
    """Legacy fixture for backward compatibility."""
    backend = MockBackend()
    return backend.create_tts_provider()


# ==============================================================================
# FILE SYSTEM FIXTURES
# ==============================================================================


@pytest.fixture
def temp_audio_file(tmp_path):
    """Create a temporary audio file for testing."""
    audio_file = tmp_path / "test_audio.mp3"
    audio_file.write_bytes(b"mock audio data")
    return audio_file


@pytest.fixture
def temp_voice_file(tmp_path):
    """Create a temporary voice file for testing."""
    voice_file = tmp_path / "test_voice.wav"
    voice_file.write_bytes(b"mock voice data")
    return voice_file


@pytest.fixture
def mock_file_operations(monkeypatch):
    """Mock file operations for safe testing."""
    original_open = open
    original_exists = os.path.exists

    def mock_open(path, mode="r", *args, **kwargs):
        # Allow opening files in temp directories
        if str(path).startswith("/tmp") or "test" in str(path):
            return original_open(path, mode, *args, **kwargs)
        # For other paths, return a mock file
        if "b" in mode:
            from io import BytesIO

            return BytesIO(b"mock file content")
        else:
            from io import StringIO

            return StringIO("mock file content")

    def mock_exists(path):
        # Always return True for config files
        if "config" in str(path):
            return True
        return original_exists(path)

    monkeypatch.setattr("builtins.open", mock_open)
    monkeypatch.setattr("os.path.exists", mock_exists)


# ==============================================================================
# VOICE MANAGER FIXTURES
# ==============================================================================


@pytest.fixture
def mock_voice_manager(monkeypatch, tmp_path):
    """Mock voice manager for testing."""

    class MockVoiceManager:
        def __init__(self):
            self.voice_dir = tmp_path / "voices"
            self.voice_dir.mkdir(exist_ok=True)
            self.loaded_voices = {}

        def load_voice(self, voice_path: str, voice_name: Optional[str] = None) -> str:
            name = voice_name or Path(voice_path).stem
            self.loaded_voices[name] = voice_path
            return name

        def get_voice(self, voice_name: str) -> Optional[str]:
            return self.loaded_voices.get(voice_name)

        def list_voices(self) -> List[str]:
            return list(self.loaded_voices.keys())

        def get_voice_dir(self) -> Path:
            return self.voice_dir

    mock_manager = MockVoiceManager()
    monkeypatch.setattr("matilda_voice.voice_manager.VoiceManager", lambda: mock_manager)
    return mock_manager


# ==============================================================================
# CLI FIXTURES
# ==============================================================================


@pytest.fixture
def cli_runner():
    """Create a Click CLI test runner."""
    from click.testing import CliRunner

    return CliRunner()


@pytest.fixture
def mock_minimal_network_calls(monkeypatch):
    """Minimal network mocking - just mock requests to avoid actual network calls."""

    def mock_request_handler(method, url, *args, **kwargs):
        """Handle different API endpoints with realistic responses."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        # ElevenLabs API endpoints
        if "api.elevenlabs.io" in str(url):
            if "/voices" in str(url):
                mock_response.json.return_value = {
                    "voices": [
                        {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
                        {"voice_id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi"},
                    ]
                }
            elif "/text-to-speech" in str(url):
                mock_response.content = b"mock audio content"
                mock_response.headers = {"content-type": "audio/mpeg"}
                mock_response.iter_content = lambda chunk_size: [b"chunk1", b"chunk2"]
            else:
                mock_response.json.return_value = {"status": "ok"}

        # OpenAI API endpoints
        elif "api.openai.com" in str(url):
            mock_response.json.return_value = {"status": "ok"}

        # Google Cloud TTS endpoints
        elif "texttospeech.googleapis.com" in str(url):
            mock_response.json.return_value = {"audioContent": "bW9jayBhdWRpbw=="}

        # Default response
        else:
            mock_response.content = b"mock audio content"
            mock_response.headers = {"content-type": "audio/mpeg"}
            mock_response.json.return_value = {"status": "ok"}

        return mock_response

    # Mock requests at the module level
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: mock_request_handler("GET", *args, **kwargs))
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: mock_request_handler("POST", *args, **kwargs))

    return mock_request_handler


@pytest.fixture
def mock_edge_tts_simple(monkeypatch, mock_edge_tts_backend):
    """Simple edge-tts mocking using unified MockBackend."""

    # Use the unified backend to create MockCommunicate
    MockCommunicate = mock_edge_tts_backend.create_communicate_class()

    # Create a comprehensive edge_tts mock module
    mock_edge_module = MagicMock()
    mock_edge_module.Communicate = MockCommunicate
    mock_edge_module.list_voices = AsyncMock(
        return_value=[
            {"Name": "en-US-AvaNeural", "ShortName": "en-US-AvaNeural", "Gender": "Female"},
            {"Name": "en-GB-SoniaNeural", "ShortName": "en-GB-SoniaNeural", "Gender": "Female"},
        ]
    )

    # Mock the import in sys.modules so any import will get our mock
    import sys

    sys.modules["edge_tts"] = mock_edge_module

    # Also set up monkeypatch mocking in case edge_tts is already imported
    try:
        # Use the mock_edge_module we already created instead of importing edge_tts
        monkeypatch.setattr("edge_tts.Communicate", MockCommunicate)

        # Mock list_voices as well
        async def mock_list_voices():
            return [
                {"Name": "en-US-AvaNeural", "ShortName": "en-US-AvaNeural", "Gender": "Female"},
                {"Name": "en-GB-SoniaNeural", "ShortName": "en-GB-SoniaNeural", "Gender": "Female"},
            ]

        monkeypatch.setattr("edge_tts.list_voices", mock_list_voices)
    except ImportError:
        pass

    return MockCommunicate


@pytest.fixture
def mock_cli_environment(
    mock_config,
    mock_selective_imports,
    mock_audio_environment,
    mock_audio_playback,
    mock_audio_conversion,
    mock_minimal_network_calls,
    mock_edge_tts_simple,
    isolated_config_dir,
    test_safe_environment,
):
    """Complete selective mock environment for CLI testing."""
    # This fixture combines minimal mocks that preserve provider logic
    # while mocking only essential external dependencies
    return {
        "config": mock_config,
        "selective_imports": mock_selective_imports,
        "audio_env": mock_audio_environment,
        "audio_playback": mock_audio_playback,
        "audio_conversion": mock_audio_conversion,
        "minimal_network": mock_minimal_network_calls,
        "edge_tts": mock_edge_tts_simple,
        "config_dir": isolated_config_dir,
        "test_env": test_safe_environment,
    }


# ==============================================================================
# SIMPLIFIED TEST FIXTURE ARCHITECTURE
# ==============================================================================
#
# This section provides a tiered fixture architecture that promotes minimal mocking
# and more real testing. Choose the appropriate fixture based on your test needs:
#
# 1. minimal_test_environment:
#    - Uses only environment variables (TTS_TEST_MODE, TTS_DISABLE_PLAYBACK)
#    - No mocking, just bypasses external dependencies via environment flags
#    - Use for: Simple unit tests, basic functionality tests
#    - Fastest option, most reliable
#
# 2. unit_test_config:
#    - Builds on minimal_test_environment + isolated config
#    - Provides temporary config directory and files
#    - Use for: Tests that need configuration isolation
#    - Good for testing config-related functionality
#
# 3. integration_test_env:
#    - Builds on unit_test_config + minimal audio mocking
#    - Mocks only audio hardware dependencies (PyAudio, ffplay processes)
#    - Preserves real provider logic while avoiding hardware requirements
#    - Use for: CLI integration tests, provider testing, audio-related tests
#    - Recommended for most CLI tests
#
# 4. full_cli_env:
#    - Builds on integration_test_env + comprehensive mocking
#    - Mocks network calls, external APIs, and complex provider dependencies
#    - Equivalent to old mock_cli_environment but built on cleaner architecture
#    - Use for: Comprehensive smoke tests, tests requiring full provider mocking
#    - Backward compatibility with existing complex tests
#
# Guidelines:
# - Start with minimal_test_environment and only add complexity if needed
# - Use integration_test_env for most CLI tests
# - Use full_cli_env only when you need to test against mocked external APIs
# - Keep the test_safe_environment fixture (created by Agent 1) for existing tests
#
# ==============================================================================


@pytest.fixture
def minimal_test_environment(monkeypatch):
    """Minimal test environment that only sets essential environment variables.

    This fixture uses environment variables to control behavior instead of heavy mocking.
    It's the simplest approach for most tests and should be the default choice.

    Environment variables set:
    - TTS_TEST_MODE=1: Bypasses network calls and provider instantiation in core.py
    - TTS_DISABLE_PLAYBACK=1: Prevents audio output during testing
    - Valid test API keys for authentication checks
    """
    # Core test mode flags
    monkeypatch.setenv("TTS_TEST_MODE", "1")
    monkeypatch.setenv("TTS_DISABLE_PLAYBACK", "1")

    # Set valid test API keys to pass authentication checks
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test1234567890abcdefghijklmnopqrstuvwxyz12345678")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "abcdef0123456789abcdef0123456789")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSyD-test1234567890abcdefghijklmnopq")

    return {"test_mode": True, "disable_playback": True, "has_api_keys": True}


@pytest.fixture
def unit_test_config(minimal_test_environment, tmp_path, monkeypatch, test_config_factory):
    """Unit test fixture that combines minimal environment with isolated config.

    Use this for:
    - Testing individual functions or classes
    - Tests that need config isolation but minimal mocking
    - Fast-running unit tests
    """
    # Create isolated config directory
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Mock XDG config directory
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # Create minimal config file using factory (without API keys for unit tests)
    config_file = config_dir / "config.toml"
    config_data = test_config_factory(
        include_api_keys=False, custom_settings={"output_directory": str(tmp_path / "output")}
    )

    with open(config_file, "w") as f:
        f.write(toml.dumps({"voice": config_data}))

    # Mock the get_config_path function to return our test config file
    monkeypatch.setattr("matilda_voice.internal.config.get_config_path", lambda: config_file)

    # Create output directory
    (tmp_path / "output").mkdir(exist_ok=True)

    return {
        **minimal_test_environment,
        "config_dir": config_dir,
        "config_file": config_file,
        "config_data": config_data,
    }


@pytest.fixture
def integration_test_env(unit_test_config, monkeypatch):
    """Integration test fixture that adds minimal audio mocking.

    Use this for:
    - Testing CLI commands and integration between components
    - Tests that need audio environment but want real provider logic
    - Integration tests that cross multiple modules
    """

    # Mock only the audio environment to prevent hardware dependencies
    def mock_check_audio_env() -> Dict[str, Any]:
        return {
            "available": True,
            "reason": "Mock audio environment",
            "pulse_available": True,
            "alsa_available": True,
        }

    monkeypatch.setattr("matilda_voice.internal.audio_utils.check_audio_environment", mock_check_audio_env)

    # Mock subprocess calls for audio playback
    from unittest.mock import MagicMock

    mock_popen = MagicMock()
    mock_popen.wait.return_value = 0
    mock_popen.returncode = 0
    mock_popen.poll.return_value = 0

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_popen)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MagicMock(returncode=0))
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")

    return {**unit_test_config, "audio_mocked": True, "mock_popen": mock_popen}


@pytest.fixture
def full_cli_env(integration_test_env, monkeypatch, mock_edge_tts_backend, mock_openai_backend):
    """Full CLI test environment with comprehensive mocking using unified MockBackend.

    Use this for:
    - Comprehensive CLI smoke tests
    - Tests that need full provider mocking (network calls, etc.)
    - Backward compatibility with existing tests
    - Tests that specifically test mocking behavior

    This is equivalent to the old mock_cli_environment but built on the new architecture.
    """
    # Add network mocking for comprehensive testing
    from unittest.mock import MagicMock

    def mock_request_handler(method, url, *args, **kwargs):
        """Handle different API endpoints with realistic responses."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        # ElevenLabs API endpoints
        if "api.elevenlabs.io" in str(url):
            if "/voices" in str(url):
                mock_response.json.return_value = {
                    "voices": [
                        {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
                        {"voice_id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi"},
                    ]
                }
            elif "/text-to-speech" in str(url):
                mock_response.content = b"mock audio content"
                mock_response.headers = {"content-type": "audio/mpeg"}
                mock_response.iter_content = lambda chunk_size: [b"chunk1", b"chunk2"]
            else:
                mock_response.json.return_value = {"status": "ok"}

        # OpenAI API endpoints
        elif "api.openai.com" in str(url):
            mock_response.json.return_value = {"status": "ok"}

        # Google Cloud TTS endpoints
        elif "texttospeech.googleapis.com" in str(url):
            mock_response.json.return_value = {"audioContent": "bW9jayBhdWRpbw=="}

        # Default response
        else:
            mock_response.content = b"mock audio content"
            mock_response.headers = {"content-type": "audio/mpeg"}
            mock_response.json.return_value = {"status": "ok"}

        return mock_response

    # Mock requests at the module level
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: mock_request_handler("GET", *args, **kwargs))
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: mock_request_handler("POST", *args, **kwargs))

    # Use unified backend for edge-tts mocking
    MockCommunicate = mock_edge_tts_backend.create_communicate_class()

    # Mock edge_tts module
    mock_edge_module = MagicMock()
    mock_edge_module.Communicate = MockCommunicate
    from unittest.mock import AsyncMock

    mock_edge_module.list_voices = AsyncMock(
        return_value=[
            {"Name": "en-US-AvaNeural", "ShortName": "en-US-AvaNeural", "Gender": "Female"},
            {"Name": "en-GB-SoniaNeural", "ShortName": "en-GB-SoniaNeural", "Gender": "Female"},
        ]
    )

    # Use unified backend for OpenAI mocking
    MockOpenAIClient = mock_openai_backend.create_openai_client()

    # Mock OpenAI module
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI = MockOpenAIClient

    # Mock the import in sys.modules so any import will get our mock
    import sys

    sys.modules["edge_tts"] = mock_edge_module
    sys.modules["openai"] = mock_openai_module

    return {
        **integration_test_env,
        "network_mocked": True,
        "edge_tts_mocked": True,
        "comprehensive_mocking": True,
        "edge_backend": mock_edge_tts_backend,
        "openai_backend": mock_openai_backend,
    }


# ==============================================================================
# UTILITY FIXTURES
# ==============================================================================


@pytest.fixture
def capture_logs():
    """Capture log output for testing."""
    import logging
    from io import StringIO

    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)

    # Add handler to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)

    yield log_capture

    # Clean up
    root_logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def cleanup_temp_files():
    """Automatically clean up temporary files after each test."""
    yield
    # Clean up any temp files created during tests
    temp_dir = tempfile.gettempdir()
    for file in Path(temp_dir).glob("tts_test_*"):
        try:
            if file.is_file():
                file.unlink()
            elif file.is_dir():
                shutil.rmtree(file)
        except Exception:
            pass
