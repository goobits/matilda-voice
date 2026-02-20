# Matilda Voice

Unified Voice CLI supporting multiple providers with streaming and file output.

## Quick Start

```bash
./scripts/setup.sh install
voice "Hello world"
voice save "Hello world" -o greeting.mp3
```

## Basic Usage

```bash
voice @edge "Hello"
voice @openai "Hello"
voice @elevenlabs "Hello"
voice @google "Hello"
voice @chatterbox "Hello"
./scripts/test.py --help
```

## Configuration

```bash
voice config set openai_api_key YOUR_KEY
voice config set elevenlabs_api_key YOUR_KEY
voice config set google_api_key YOUR_KEY
voice config show
```

## Development

```bash
./scripts/setup.sh install --dev
make test
make quality
```

## Documentation

- `docs/getting-started.md`
- `docs/user-guide.md`
- `docs/providers.md`
- `docs/advanced.md`
