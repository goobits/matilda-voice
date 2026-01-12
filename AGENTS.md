# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Matilda Voice is a Python text-to-speech command-line tool that supports multiple Voice providers with smart auto-selection, voice cloning capabilities, and intelligent document processing. The project uses a pluggable provider architecture to support:

- **Edge Voice** (Microsoft Azure): Free, high-quality neural voices  
- **Chatterbox**: Local voice cloning with GPU/CPU support
- **OpenAI Voice**: API-based synthesis with premium voices
- **Google Cloud Voice**: Google's neural voices via REST API
- **ElevenLabs**: Advanced voice synthesis and cloning

Additionally, Voice CLI now includes advanced document-to-speech capabilities:
- **Multi-format support**: HTML, JSON, Markdown auto-conversion
- **Emotion detection**: Context-aware emotion profiles (technical, marketing, narrative, tutorial)
- **SSML generation**: Platform-optimized speech synthesis markup (Azure, Google, Amazon)
- **Performance caching**: Optimized document processing for repeated conversions

## Installation & Development Setup

**Use the setup script for installation - all dependencies are handled automatically**:

```bash
# Production install (for end users)
./setup.sh install         # Automatically installs all Python extras and system packages

# Development install (editable) - RECOMMENDED FOR DEVELOPMENT  
./setup.sh install --dev   # Installs with dev tools and all providers

# Upgrade to latest version
./setup.sh upgrade

# Uninstall
./setup.sh uninstall
```

**IMPORTANT FOR DEVELOPMENT**: Always use `./setup.sh install --dev` for development work. This creates an editable installation where code changes are immediately reflected without needing to reinstall or upgrade.

**Automatic Dependency Management**: The setup script now automatically handles:
- All Python extras (dev, openai, google, elevenlabs, chatterbox, etc.)
- System packages (ffmpeg, sox for audio processing)
- No manual pip install or apt-get commands needed

## CLI Generation
The project uses Goobits CLI framework: run `goobits build` to generate CLI and setup scripts from goobits.yaml configuration.
After generation, use `./scripts/setup.sh install --dev` for development installation with immediate code change reflection.

## Common Development Commands

**Testing:**
```bash
# Use the virtual environment when running commands, not the global python
./scripts/test.sh               # Main test runner with coverage
python -m pytest tests/ -v      # Direct pytest execution

# CLI-specific testing
python -m pytest tests/integration/test_cli_integration.py -v  # Detailed CLI functionality tests
python -m pytest tests/e2e/test_cli_smoke.py -v               # Comprehensive CLI smoke tests  
python test_cli.py                                             # Quick CLI validation script
```

**Code Quality:**
```bash
ruff check .                                              # Lint code
ruff check . --fix                                        # Auto-fix linting issues
black .                                                   # Format code (line-length 128)
mypy src/matilda_voice/                                            # Type checking
```

**Note:** If tools are installed via pipx, use the full path:
```bash
~/.local/share/pipx/venvs/goobits-matilda-voice/bin/ruff check .    # Lint code
~/.local/share/pipx/venvs/goobits-matilda-voice/bin/black .         # Format code  
~/.local/share/pipx/venvs/goobits-matilda-voice/bin/mypy src/matilda_voice/   # Type checking
```

**Building:**
```bash
python -m build         # Build package
```

## Architecture Overview

### Core Components

1. **src/matilda_voice/cli.py** - Main CLI entry point with generated commands
2. **src/matilda_voice/app_hooks.py** - Hook implementations connecting CLI to Voice functionality
3. **src/matilda_voice/core.py** - Core Voice engine with provider management
4. **src/matilda_voice/base.py** - Abstract `VoiceProvider` base class
5. **src/matilda_voice/config.py** - Configuration management with XDG compliance
6. **src/matilda_voice/voice_manager.py** - Voice loading/caching for fast access
7. **src/matilda_voice/providers/** - Provider implementations
8. **src/matilda_voice/document_processing/** - Document parsing (HTML, JSON, Markdown)
9. **src/matilda_voice/speech_synthesis/** - Emotion detection and SSML generation

### Provider Architecture

All providers inherit from `VoiceProvider` and implement:
- `synthesize(text, output_path, **kwargs)` - Core synthesis method
- `get_info()` - Returns provider capabilities and sample voices

Provider loading is dynamic via the `PROVIDERS_REGISTRY` dict in `src/matilda_voice/app_hooks.py:16-22`.

### Configuration System

- Default config in `config.py` (DEFAULT_CONFIG constant)
- XDG-compliant paths (`~/.matilda/config.toml` under `[voice]`)
- Voice format: `provider:voice_name` (e.g., `edge_tts:en-IE-EmilyNeural`)
- Auto-detection of providers from voice strings in `parse_voice_setting()`

### Key CLI Commands

**Package name:** `goobits-matilda-voice` (installs as `voice` command)

**IMPORTANT: Always use the setup script for installation:**
```bash
./setup.sh install           # Install the package with all dependencies
```

```bash
# Basic synthesis (direct streaming to speakers)
voice "Hello world"             # Stream audio (default behavior)
voice Hello world               # Unquoted text also works
echo "Hello world" | voice      # Pipe input support

# Provider shortcuts
voice @edge "Hello world"       # Edge Voice (free)
voice @openai "Hello world"     # OpenAI Voice
voice @elevenlabs "Hello world" # ElevenLabs
voice @google "Hello world"     # Google Cloud Voice
voice @chatterbox "Hello world" # Local voice cloning

# Save to file
voice save "text"               # Save to file
voice save @edge "text" -o audio.mp3  # Save with specific provider

# Voice and system management
voice voices                    # Interactive voice browser
voice voice load voice.wav      # Preload voice for fast access
voice voice status              # Show loaded voices
voice providers                 # Enhanced provider status display
voice providers @openai         # Provider-specific setup instructions
voice status                    # System health check
voice --version                 # Show version with suite branding

# Configuration (enhanced display)
voice config show               # Rich config display with emoji sections
voice config set openai_api_key YOUR_KEY    # Set API keys
voice config edit               # Interactive editor

# Document processing
voice document report.html      # Convert HTML to speech
voice document api.json --emotion-profile technical --save
voice document README.md --ssml-platform azure

# Pipeline examples (integration with Ears/Brain)
echo "Hello world" | voice                     # Simple pipe
brain "Fix grammar" < essay.txt | voice          # Fix then speak
ears recording.wav | voice @edge               # Transcribe and speak
```

## Code Style & Standards

- **Line length**: 128 characters (Black + Ruff configured)
- **Type hints**: Required for all functions (`mypy` enforced)
- **Error handling**: Use custom exceptions from `exceptions.py`
- **Logging**: Structured logging to console

## Key Implementation Details

### Real-time Streaming
The CLI defaults to streaming audio directly to speakers. Providers should support `stream=true` in kwargs to enable this.

### Voice Cloning (Chatterbox)
Voice files can be loaded into memory for fast synthesis:
```python
voice_manager = VoiceManager()
voice_manager.load_voice("/path/to/voice.wav")  # Pre-load for speed
```

### Interactive Voice Browser
Advanced curses-based interface in `src/matilda_voice/voice_browser.py` with:
- Three-panel layout (filters, voices, preview)
- Mouse and keyboard navigation
- Real-time voice preview with background audio playback
- Quality analysis and metadata extraction

### Automatic Dependency Management
All provider dependencies (including PyTorch for Chatterbox with GPU support) are automatically installed via the goobits extras system during setup.

## Testing Notes

- Tests organized by type with clear boundaries:
  - `tests/unit/` - Pure unit tests with mocks
  - `tests/integration/` - Integration tests with mocked external dependencies  
  - `tests/e2e/` - End-to-end workflow tests
  - `tests/providers/` - Provider-specific tests
- Tests gracefully skip when providers unavailable (CI-friendly)
- Use `pytest -v` for verbose output
- All external dependencies properly mocked for reliable testing

## Recent Features

### CLI Enhancement (v1.1.4)
- **Enhanced user experience**: Emoji-enhanced interface with visual status indicators
- **Provider shortcuts**: Use `@edge`, `@openai`, `@elevenlabs`, etc. for quick provider selection
- **Rich configuration display**: Organized sections showing API keys, defaults, audio settings, and paths
- **Pipeline integration examples**: Clear demonstrations of Ears → Brain → Voice workflows
- **Comprehensive providers command**: Detailed status checking and setup instructions

### Core Features
- **Real-time streaming support**: OpenAI, ElevenLabs with minimal latency
- **Enhanced voice browser**: Three-panel curses interface with advanced filtering
- **Dual authentication**: Google Cloud Voice supports both API key and service account
- **Voice loading/caching**: Preload voices for fast synthesis (Chatterbox)
- **Interactive configuration**: User-friendly config editor with validation
- **Document processing**: Multi-format support (HTML, JSON, Markdown) with emotion detection
- **SSML generation**: Platform-optimized markup (Azure, Google, Amazon)
- **Context-aware profiles**: Technical, marketing, narrative, tutorial emotion detection

## Important Files to Understand

- `src/matilda_voice/cli.py` - Generated CLI entry point with dynamic command loading
- `src/matilda_voice/app_hooks.py` - Hook implementations that provide actual Voice functionality
- `src/matilda_voice/core.py` - Core Voice engine with provider management and synthesis logic
- `src/matilda_voice/config.py` - Configuration management with voice parsing logic  
- `src/matilda_voice/voice_browser.py` - Interactive voice browser implementation
- `src/matilda_voice/providers/` - Provider implementations (Edge Voice, Chatterbox, etc.)
- `setup.sh` - Installation script (use this for all installs)
- `pyproject.toml` - Package configuration and dependencies

### Temporary Files
When creating temporary debug or test scripts, use `/tmp` directory to keep the project clean.

### Preventing __pycache__ Directories During Development

The setup script automatically sets `PYTHONDONTWRITEBYTECODE=1` during installation to prevent Python from creating `__pycache__` directories. 

For permanent prevention in your development environment:
```bash
# Add to your shell profile (.bashrc/.zshrc)
export PYTHONDONTWRITEBYTECODE=1
```

Alternative installation options to minimize build artifacts:
```bash
pip install -e . --no-build-isolation --no-deps
# Note: May require dependencies to be installed separately
```

The `.gitignore` file is already configured to exclude all Python build artifacts including:
- `__pycache__/`
- `*.py[cod]`
- `*.egg-info/`
- `build/`
- `dist/`
