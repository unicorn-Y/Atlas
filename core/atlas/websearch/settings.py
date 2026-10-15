"""``[web]`` settings in ``config/atlas.toml`` plus provider credentials.

Replaces Hermes ``web.backend`` / ``web.search_backend`` / ``web.provider_tier`` (config.yaml)
and ``get_provider_env`` (~/.hermes/.env). Example::

    [web]
    search_order = ["bocha", "exa", "brave", "parallel", "tavily", "keyless", "ddgs"]
    search_order_zh = ["bocha", "keyless", "ddgs"]   # used when the query is mostly Chinese
    extract_order = ["local", "exa", "parallel", "tavily", "keyless"]
    keyless = true             # anonymous free tiers (Exa / Parallel / Keenable / Tavily)
    cache_ttl_minutes = 20
    extract_char_limit = 15000

    [web.keys]
    bocha = "sk-..."           # or env BOCHA_API_KEY
    exa = ""                   # EXA_API_KEY
    parallel = ""              # PARALLEL_API_KEY

Every key may also come from its environment variable; the TOML value wins when both are set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# provider name -> environment variable holding its credential (or instance URL for searxng).
KEY_ENV = {
    "bocha": "BOCHA_API_KEY",
    "exa": "EXA_API_KEY",
    "parallel": "PARALLEL_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "brave": "BRAVE_SEARCH_API_KEY",
    "keenable": "KEENABLE_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "searxng": "SEARXNG_URL",
}

# English / other queries: keyed western engines first (a key means the user registered it),
# then the anonymous ring (Exa / Parallel quality, rate-limited), then Bocha — its index is
# Chinese-first and answers English queries with Chinese reposts — and the scraping fallback
# last. Providers without a key are skipped, so a fresh install degrades to keyless -> ddgs.
DEFAULT_SEARCH_ORDER = ("exa", "brave", "parallel", "perplexity", "tavily", "keenable", "searxng",
                        "keyless", "bocha", "ddgs")
# Chinese queries: Bocha has a native Chinese index; the western engines index Chinese sites
# (zhihu, weixin, bilibili, csdn) poorly, so they only back it up.
DEFAULT_SEARCH_ORDER_ZH = ("bocha", "keyless", "exa", "brave", "parallel", "tavily", "searxng", "ddgs")
DEFAULT_EXTRACT_ORDER = ("local", "exa", "parallel", "tavily", "keenable", "keyless")


@dataclass
class WebSettings:
    search_order: tuple[str, ...] = DEFAULT_SEARCH_ORDER
    search_order_zh: tuple[str, ...] = DEFAULT_SEARCH_ORDER_ZH
    extract_order: tuple[str, ...] = DEFAULT_EXTRACT_ORDER
    keyless: bool = True
    cache_enabled: bool = True
    cache_ttl_minutes: float = 20.0
    extract_char_limit: int = 15000
    parallel_mode: str = "fast"
    keys: dict[str, str] = field(default_factory=dict)

    def key(self, provider: str) -> str:
        value = (self.keys.get(provider) or "").strip()
        if value:
            return value
        env = KEY_ENV.get(provider)
        return (os.environ.get(env, "") if env else "").strip()


def _order(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        names = tuple(str(item).strip().lower() for item in value if str(item).strip())
        if names:
            return names
    return default


def load_settings(raw: dict[str, Any] | None = None) -> WebSettings:
    """Read ``[web]`` from the given dict, else from the live Atlas config singleton."""
    if raw is None:
        try:
            from atlas.config import get_config

            raw = get_config().raw
        except (ImportError, OSError, ValueError):
            raw = {}
    web = raw.get("web") if isinstance(raw, dict) else None
    web = web if isinstance(web, dict) else {}
    keys_raw = web.get("keys") if isinstance(web.get("keys"), dict) else {}
    keys = {str(k).strip().lower(): str(v) for k, v in keys_raw.items() if isinstance(v, str)}

    def _float(name: str, default: float) -> float:
        try:
            return float(web.get(name, default))
        except (TypeError, ValueError):
            return default

    def _int(name: str, default: int) -> int:
        try:
            return int(web.get(name, default))
        except (TypeError, ValueError):
            return default

    mode = str(web.get("parallel_mode") or "fast").strip().lower()
    return WebSettings(
        search_order=_order(web.get("search_order"), DEFAULT_SEARCH_ORDER),
        search_order_zh=_order(web.get("search_order_zh"), DEFAULT_SEARCH_ORDER_ZH),
        extract_order=_order(web.get("extract_order"), DEFAULT_EXTRACT_ORDER),
        keyless=bool(web.get("keyless", True)),
        cache_enabled=bool(web.get("cache_enabled", True)),
        cache_ttl_minutes=max(1.0, min(_float("cache_ttl_minutes", 20.0), 1440.0)),
        extract_char_limit=max(2000, min(_int("extract_char_limit", 15000), 500_000)),
        parallel_mode=mode if mode in {"turbo", "fast", "basic", "advanced"} else "fast",
        keys=keys,
    )
