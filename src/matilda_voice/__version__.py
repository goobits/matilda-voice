import tomllib
from importlib import metadata
from pathlib import Path


def _get_version() -> str:
    """Read version from package metadata or pyproject.toml."""
    try:
        return metadata.version("goobits-matilda-voice")
    except Exception:
        pass

    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return str(data["project"]["version"])
    except Exception:
        return "unknown"


__version__ = _get_version()
