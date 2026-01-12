# Changelog

All notable changes to Goobits Voice will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-01-12

### Added
- **Azure TTS Provider** - Native Azure speech synthesis with SSML support
- **SSML CLI Flag** - Generate SSML markup directly from command line
- **Coqui TTS Provider** - Local neural TTS with GPU acceleration

### Changed
- **TOML Configuration** - Migrated from YAML to TOML format for consistency
- **Provider Architecture** - Refactored provider system with cleaner public API
- **Error Handling** - Improved error messages and exception handling in CLI hooks

### Fixed
- Removed legacy StreamPlayer alias and dead re-exports
- CORS security improvements with persistent token storage

### Removed
- Legacy YAML configuration support

## [1.1.4] - 2025-11-10

### Added
- Comprehensive documentation structure in `docs/` directory
  - Getting Started guide
  - Complete User Guide
  - Provider comparison and setup guide
  - Advanced usage documentation
- Concise README focused on quick start and overview
- Professional provider comparison table

### Changed
- README reduced from 207 to 127 lines for better scanability
- Removed excessive emoji usage for cleaner presentation
- Updated package metadata to use README.md instead of CLAUDE.md
- Standardized GitHub repository URLs to github.com/goobits/voice
- Fixed documentation accuracy issues (version command, line-length references)
- Configuration file format standardized to .toml

### Fixed
- Corrected version command syntax (voice --version)
- Fixed line-length documentation (128 characters)
- Removed false BeautifulSoup claim (uses regex-based HTML parsing)
- Fixed configuration file path documentation

## [1.1.3] - 2025-08

### Added
- Enhanced user experience with visual status indicators
- Provider shortcuts (@edge, @openai, @elevenlabs, etc.)
- Rich configuration display with organized sections
- Pipeline integration examples (Ears → Brain → Voice)
- Comprehensive providers command with setup instructions

## [1.0.0] - Repository Cleanup (August 2025)

### Changed
- Removed 3,849 venv/ files from git tracking (virtual environment cleanup)
- Removed 29 cache/temp files (.cache/ and .temp/ directories)
- Updated .gitignore to prevent future tracking violations

### Added
- .gitignore protections for:
  - `venv/` (virtual environments)
  - `.cache/` (cache directories)
  - `.temp/` (temporary directories)
  - Enhanced Python build artifact coverage

### Notes
This was a one-time maintenance task to improve repository hygiene. Users with existing forks/clones should:
```bash
git pull origin main  # Get the cleanup commits
# Or for a fresh start:
git clone [repo-url]  # Re-clone to get clean history
```
