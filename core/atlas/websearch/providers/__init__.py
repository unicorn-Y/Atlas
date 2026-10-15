# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: agent/web_search_registry.py (MIT)
"""Built-in web providers, by config name (translated registry of Hermes ``agent/web_search_registry.py``)."""

from __future__ import annotations

from atlas.websearch.providers.base import WebProvider
from atlas.websearch.providers.ddgs import DDGSProvider
from atlas.websearch.providers.keyed import (
    BochaProvider, BraveProvider, ExaProvider, KeenableProvider, ParallelProvider, PerplexityProvider,
    SearXNGProvider, TavilyProvider,
)
from atlas.websearch.providers.local import KeylessProvider, LocalProvider

PROVIDERS: dict[str, WebProvider] = {
    p.name: p for p in (
        BochaProvider(), ExaProvider(), ParallelProvider(), TavilyProvider(), BraveProvider(),
        KeenableProvider(), PerplexityProvider(), SearXNGProvider(), DDGSProvider(),
        LocalProvider(), KeylessProvider(),
    )
}

ALIASES = {"brave-free": "brave", "duckduckgo": "ddgs", "free": "keyless"}


def get_provider(name: str) -> WebProvider | None:
    key = (name or "").strip().lower()
    return PROVIDERS.get(ALIASES.get(key, key))


__all__ = ["PROVIDERS", "WebProvider", "get_provider"]
