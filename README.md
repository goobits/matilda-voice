# Matilda Voice

Unified Voice CLI supporting multiple providers with streaming and file output.

## Quick Start

```bash
./setup.sh install
voice "Hello world"
voice save "Hello world" -o greeting.mp3
```

## Providers

```bash
voice @edge "Hello"
voice @openai "Hello"
voice @elevenlabs "Hello"
voice @google "Hello"
voice @chatterbox "Hello"
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
./setup.sh install --dev
./scripts/test.py
make quality
```

## Documentation

- `docs/getting-started.md`
- `docs/user-guide.md`
- `docs/providers.md`
- `docs/advanced.md`
