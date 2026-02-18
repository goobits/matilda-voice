"""Core TTS engine functionality separated from CLI concerns."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Type

from .base import TTSProvider
from .exceptions import ProviderLoadError, ProviderNotFoundError, TTSError
from .internal.config import CONFIG_DEFAULTS, get_api_key, load_config, parse_voice_setting
from .internal.types import ProviderInfo


class TTSEngine:
    """Core TTS engine that handles synthesis without CLI dependencies."""

    def __init__(self, providers_registry: Dict[str, str]) -> None:
        """Initialize TTS engine with provider registry.

        Args:
            providers_registry: Dictionary mapping provider names to module paths
        """
        self.providers_registry = providers_registry
        self.logger = logging.getLogger(__name__)
        self._loaded_providers: Dict[str, Type[TTSProvider]] = {}

    def load_provider(self, name: str) -> Type[TTSProvider]:
        """Load a TTS provider by name using the existing loader.

        Args:
            name: Provider name (e.g., 'edge_tts', 'openai')

        Returns:
            Provider class

        Raises:
            ProviderNotFoundError: If provider not found in registry
            ProviderLoadError: If provider module cannot be loaded
        """
        if name in self._loaded_providers:
            return self._loaded_providers[name]

        # Load provider directly from the registry
        if name not in self.providers_registry:
            raise ProviderNotFoundError(f"Provider '{name}' not found in registry")

        module_path = self.providers_registry[name]

        try:
            # Import the provider module dynamically
            import importlib

            module = importlib.import_module(module_path)

            # Find the provider class in the module
            # Look for a class that inherits from TTSProvider
            provider_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, TTSProvider) and attr is not TTSProvider:
                    provider_class = attr
                    break

            if not provider_class:
                raise ProviderLoadError(f"No TTSProvider subclass found in module {module_path}")

            self._loaded_providers[name] = provider_class
            return provider_class

        except ImportError as e:
            raise ProviderLoadError(f"Failed to import provider module {module_path}: {e}") from e
        except (AttributeError, TypeError, ValueError) as e:
            raise ProviderLoadError(f"Failed to load provider {name}: {e}") from e

    def get_available_providers(self) -> list[str]:
        """Get list of available provider names."""
        return list(self.providers_registry.keys())

    def synthesize_text(
        self,
        text: str,
        output_path: Optional[str] = None,
        provider_name: Optional[str] = None,
        voice: Optional[str] = None,
        stream: bool = True,
        output_format: str = "wav",
        **kwargs: Any,
    ) -> Optional[str]:
        """Synthesize text to speech.

        Args:
            text: Text to synthesize
            output_path: Path to save audio file (if None and stream=False, auto-generate)
            provider_name: Specific provider to use (if None, auto-detect from voice)
            voice: Voice to use (provider:voice format or just voice name)
            stream: Whether to stream audio to speakers
            output_format: Audio output format
            **kwargs: Additional provider-specific options

        Returns:
            Path to generated audio file if saved, None if streamed

        Raises:
            TTSError: If synthesis fails
            ProviderNotFoundError: If specified provider not found
        """
        # Load configuration
        config = load_config()

        # Determine voice and provider
        # If provider_name is explicitly provided, it takes precedence
        if provider_name:
            # Extract just the voice part if it contains a provider prefix
            if voice:
                _, voice_name = parse_voice_setting(voice)
                if voice_name:
                    voice = voice_name
            elif not voice:
                # No voice specified - use provider's default or None
                # Don't use config default if it's for a different provider
                default_voice = config.get(
                    "voice", f"{CONFIG_DEFAULTS['default_provider']}:{CONFIG_DEFAULTS['default_voice']}"
                )
                default_provider, default_voice_name = parse_voice_setting(default_voice)
                if default_provider == provider_name:
                    voice = default_voice_name
                # else: voice remains None, provider will use its own default
        else:
            # No explicit provider, auto-detect from voice
            if voice:
                detected_provider, voice_name = parse_voice_setting(voice)
                if detected_provider:
                    provider_name = detected_provider
                    voice = voice_name
            else:
                # Use default voice from config
                default_voice = config.get(
                    "voice", f"{CONFIG_DEFAULTS['default_provider']}:{CONFIG_DEFAULTS['default_voice']}"
                )
                provider_name, voice = parse_voice_setting(str(default_voice))

        if not provider_name:
            # Fallback to default provider if no provider detected
            provider_name = str(CONFIG_DEFAULTS["default_provider"])
        assert provider_name is not None

        # Load and instantiate provider
        try:
            provider_class = self.load_provider(provider_name)
            provider = provider_class()
        except (ProviderNotFoundError, ProviderLoadError) as e:
            self.logger.error(f"Failed to load provider {provider_name}: {e}")
            raise TTSError(f"Provider {provider_name} unavailable: {e}") from e

        # Prepare synthesis parameters
        synthesis_kwargs = {"stream": stream, "output_format": output_format, **kwargs}
        # Only include voice if it's not None to allow provider defaults
        if voice is not None:
            synthesis_kwargs["voice"] = voice

        # Generate output path if needed
        if not stream and not output_path:
            import tempfile

            suffix = f".{output_format}" if output_format else ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                output_path = tmp.name

        # Perform synthesis
        try:
            if stream:
                self.logger.info(f"Streaming synthesis with {provider_name} provider")
                provider.synthesize(text, None, **synthesis_kwargs)
                return None
            else:
                self.logger.info(f"Synthesizing audio to {output_path} with {provider_name} provider")
                provider.synthesize(text, output_path, **synthesis_kwargs)

                # Verify output file was created
                if output_path and Path(output_path).exists():
                    file_size = Path(output_path).stat().st_size
                    self.logger.info(f"Synthesis completed. File: {output_path} ({file_size} bytes)")
                    return output_path
                else:
                    raise TTSError("Synthesis completed but output file not found")

        except (IOError, OSError, RuntimeError, ValueError) as e:
            self.logger.error(f"Synthesis failed: {e}")
            raise TTSError(f"Synthesis failed: {e}") from e

    def get_provider_info(self, provider_name: str) -> Optional[ProviderInfo]:
        """Get information about a specific provider.

        Args:
            provider_name: Name of the provider

        Returns:
            Provider info dictionary or None if provider unavailable
        """
        try:
            provider_class = self.load_provider(provider_name)
            provider = provider_class()
            return provider.get_info()
        except (ProviderNotFoundError, ProviderLoadError, AttributeError, RuntimeError) as e:
            self.logger.warning(f"Could not get info for provider {provider_name}: {e}")
            return None

    def get_all_voices(self) -> Dict[str, list]:
        """Get all available voices from all providers.

        Returns:
            Dictionary mapping provider names to lists of available voices
        """
        all_voices = {}

        for provider_name in self.providers_registry.keys():
            try:
                info = self.get_provider_info(provider_name)
                if info:
                    voices = info.get("all_voices") or info.get("sample_voices", [])
                    if not isinstance(voices, list):
                        voices = []
                    all_voices[provider_name] = voices
                else:
                    all_voices[provider_name] = []
            except (AttributeError, KeyError, ValueError, RuntimeError) as e:
                self.logger.warning(f"Error getting voices for {provider_name}: {e}")
                all_voices[provider_name] = []

        return all_voices

    def validate_voice(self, voice: str, provider_name: Optional[str] = None) -> bool:
        """Validate that a voice is available.

        Args:
            voice: Voice name to validate
            provider_name: Specific provider to check (if None, parse from voice)

        Returns:
            True if voice is available, False otherwise
        """
        if not provider_name:
            provider_name, voice = parse_voice_setting(voice)

        if not provider_name:
            return False

        try:
            info = self.get_provider_info(provider_name)
            if not info:
                return False

            voices = info.get("all_voices") or info.get("sample_voices", [])
            if not isinstance(voices, list):
                voices = []
            return voice in voices

        except (AttributeError, KeyError, ValueError):
            return False

    def get_provider_status(self, provider_name: str) -> Dict[str, Any]:
        """Get defensive status information for a provider without throwing exceptions.

        Returns status information that can be used by CLI commands like 'info' and 'status'
        even when authentication is missing or provider setup is incomplete.

        Args:
            provider_name: Name of the provider to check

        Returns:
            Dictionary with status fields: name, installed, configured, available, error
        """
        status = {"name": provider_name, "installed": False, "configured": False, "available": False, "error": None}

        # Check if we're in test mode
        is_test_mode = os.environ.get("TTS_TEST_MODE", "").lower() in ("true", "1", "yes")

        try:
            # Try to load the provider class (checks if module exists)
            provider_class = self.load_provider(provider_name)
            status["installed"] = True

            # Check if provider needs API key and if it's configured
            api_key_needed = self._provider_needs_api_key(provider_name)
            if api_key_needed:
                api_key_provider = self._get_api_key_provider_name(provider_name)
                api_key = get_api_key(api_key_provider)
                status["configured"] = api_key is not None
            else:
                # Providers like edge_tts don't need API keys
                status["configured"] = True

            # In test mode, don't attempt actual provider instantiation
            if is_test_mode:
                status["available"] = status["installed"] and status["configured"]
            else:
                # Try basic provider instantiation without network calls
                try:
                    provider_class()
                    status["available"] = True
                except Exception as e:
                    self.logger.exception(f"Provider instantiation failed for {provider_name}")
                    status["error"] = f"Provider instantiation failed: {str(e)}"

        except ProviderNotFoundError:
            status["error"] = f"Provider '{provider_name}' not found in registry"
        except ProviderLoadError as e:
            status["error"] = f"Failed to load provider: {str(e)}"
        except ImportError as e:
            status["error"] = f"Missing dependencies: {str(e)}"
        except Exception as e:
            self.logger.exception(f"Unexpected error getting provider status for {provider_name}")
            status["error"] = f"Unexpected error: {str(e)}"

        return status

    def get_provider_info_safe(self, provider_name: str) -> Dict[str, Any]:
        """Get provider information safely without authentication requirements.

        Returns basic provider info even when API keys are missing. Falls back to
        provider-defined metadata when authentication fails.

        Args:
            provider_name: Name of the provider

        Returns:
            Dictionary with provider information (never None)
        """
        info: Dict[str, Any] = {
            "name": provider_name,
            "description": f"{provider_name.title()} TTS Provider",
            "sample_voices": [],
            "all_voices": [],
            "capabilities": [],
            "status": "unknown",
        }
        info.update(self._get_provider_fallback_info(provider_name))

        try:
            # Try to get the actual provider info
            provider_info = self.get_provider_info(provider_name)
            if provider_info:
                info.update(provider_info)
                info["status"] = "available"
            else:
                # Provider exists but info failed (likely auth issue)
                info["status"] = "authentication_required"

        except (ProviderNotFoundError, ProviderLoadError):
            info["status"] = "not_installed"
        except Exception as e:
            self.logger.exception(f"Error getting provider info for {provider_name}")
            info["status"] = "error"
            info["error"] = str(e)

        return info

    def _get_provider_fallback_info(self, provider_name: str) -> Dict[str, Any]:
        fallback_info: Dict[str, Any] = {}

        try:
            provider_class = self.load_provider(provider_name)
        except (ProviderNotFoundError, ProviderLoadError):
            return fallback_info

        provider_info = getattr(provider_class, "PROVIDER_INFO", None)
        if isinstance(provider_info, dict):
            fallback_info.update(provider_info)

        return fallback_info

    def _provider_needs_api_key(self, provider_name: str) -> bool:
        """Check if a provider requires an API key for operation.

        Args:
            provider_name: Name of the provider

        Returns:
            True if provider needs API key, False otherwise
        """
        # Providers that need API keys (match actual registry names)
        api_key_providers = {"openai_tts", "elevenlabs", "google_tts"}
        return provider_name.lower() in api_key_providers

    def _get_api_key_provider_name(self, provider_name: str) -> str:
        """Map provider registry name to API key config name.

        Args:
            provider_name: Provider name from registry (e.g., "openai_tts")

        Returns:
            API key provider name (e.g., "openai")
        """
        # Map registry names to config API key names
        mapping = {"openai_tts": "openai", "google_tts": "google", "elevenlabs": "elevenlabs"}
        return mapping.get(provider_name, provider_name)

    def test_provider(self, provider_name: str) -> Dict[str, Any]:
        """Test a provider's availability and basic functionality.

        Args:
            provider_name: Name of provider to test

        Returns:
            Dictionary with test results
        """
        result = {"provider": provider_name, "available": False, "error": None, "voice_count": 0, "sample_voices": []}

        try:
            provider_class = self.load_provider(provider_name)
            provider = provider_class()
            info = provider.get_info()

            if info:
                voices = info.get("all_voices") or info.get("sample_voices", [])
                if not isinstance(voices, list):
                    voices = []
                result.update(
                    {
                        "available": True,
                        "voice_count": len(voices),
                        "sample_voices": voices[:5],  # First 5 voices as samples
                    }
                )
            else:
                result["error"] = "No provider info available"

        except (ProviderNotFoundError, ProviderLoadError, AttributeError, RuntimeError) as e:
            result["error"] = str(e)

        return result


# Global TTS engine instance (initialized by CLI)
_tts_engine: Optional[TTSEngine] = None


def get_tts_engine() -> TTSEngine:
    """Get the global TTS engine instance.

    Returns:
        TTS engine instance

    Raises:
        RuntimeError: If engine not initialized
    """
    if _tts_engine is None:
        raise RuntimeError("TTS engine not initialized. Call initialize_tts_engine() first.")
    return _tts_engine


def initialize_tts_engine(providers_registry: Dict[str, str]) -> TTSEngine:
    """Initialize the global TTS engine.

    Args:
        providers_registry: Dictionary mapping provider names to module paths

    Returns:
        Initialized TTS engine instance
    """
    global _tts_engine
    _tts_engine = TTSEngine(providers_registry)
    return _tts_engine
