"""
Matilda Voice i18n Module
=========================

Internationalization support for Matilda Voice.

Usage:
    from matilda_voice.i18n import t, t_voice, t_common, set_language

    # Voice-specific translation (default domain)
    print(t("cli.name"))                      # "Voice"
    print(t("status.title"))                  # "TTS System Status"

    # With interpolation
    print(t("errors.api_key_not_found", provider="OpenAI", command="..."))

    # Common domain (shared terms)
    print(t_common("status.ready"))           # "Ready"
    print(t_common("errors.not_found", item="Voice"))

    # Change language
    set_language("es")
"""

import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional


def _find_i18n_root() -> Path | None:
    env_path = os.environ.get("MATILDA_I18N_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate

    for base in [Path(__file__).resolve(), Path.cwd()]:
        for parent in [base, *base.parents]:
            candidate = parent / "i18n"
            if candidate.exists():
                return candidate
    return None


# Add central i18n to path for base_loader import
_I18N_PATH = _find_i18n_root()
if _I18N_PATH and str(_I18N_PATH) not in sys.path:
    sys.path.insert(0, str(_I18N_PATH))

try:
    from base_loader import I18nLoader as ExternalI18nLoader  # type: ignore[import-not-found]
    from base_loader import get_monorepo_locales_path

    I18nLoader = ExternalI18nLoader
except ImportError:
    # Fallback: define minimal loader inline if base not available
    import json
    import os
    import threading

    def get_monorepo_locales_path() -> Path:
        i18n_root = _find_i18n_root()
        if i18n_root:
            candidate = i18n_root / "locales"
            if candidate.exists():
                return candidate
        local_path = Path(__file__).parent / "locales"
        if local_path.exists():
            return local_path
        return local_path

    class FallbackI18nLoader:
        def __init__(
            self, locales_path: Optional[Path] = None, default_domain: str = "common", default_language: str = "en"
        ) -> None:
            self.locales_path = locales_path or get_monorepo_locales_path()
            self.default_domain = default_domain
            self._cache: Dict[str, dict] = {}
            self._lock = threading.Lock()
            self._lang = default_language

        def set_language(self, lang: str) -> None:
            self._lang = lang
            self._cache.clear()

        def get_language(self) -> str:
            return str(os.environ.get("MATILDA_LANG", self._lang))[:2]

        def _load_domain(self, domain: str, lang: Optional[str] = None) -> dict[str, Any]:
            lang = lang or self.get_language()
            key = f"{lang}:{domain}"
            with self._lock:
                if key not in self._cache:
                    for try_lang in [lang, "en"]:
                        path = self.locales_path / try_lang / f"{domain}.json"
                        if path.exists():
                            self._cache[key] = json.loads(path.read_text(encoding="utf-8"))
                            break
                    else:
                        self._cache[key] = {}
                return self._cache.get(key, {})

        def t(self, key: str, domain: Optional[str] = None, **kw: Any) -> str:
            domain = domain or self.default_domain
            val: Any = self._load_domain(domain)
            for part in key.split("."):
                val = val.get(part, {}) if isinstance(val, dict) else {}
            if not isinstance(val, str):
                return self.t(key, "common", **kw) if domain != "common" else key
            return val.format(**kw) if kw else val

        def t_domain(self, domain: str) -> Callable[[str], str]:
            return lambda key, **kw: self.t(key, domain, **kw)

    I18nLoader = FallbackI18nLoader


# =============================================================================
# Voice-specific loader instance
# =============================================================================

_loader = I18nLoader(default_domain="voice")

# Primary translation function (defaults to voice domain)
t = _loader.t

# Domain-specific shortcuts
t_voice = _loader.t_domain("voice")
t_common = _loader.t_domain("common")

# Language management
set_language = _loader.set_language
get_language = _loader.get_language

# Re-export for convenience
__all__ = [
    "t",
    "t_voice",
    "t_common",
    "set_language",
    "get_language",
    "I18nLoader",
]
