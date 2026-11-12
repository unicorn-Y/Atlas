"""Atlas web search: multi-provider search + page reading with failover.

Providers: Bocha (Chinese index), Exa, Parallel, Tavily, Brave, Keenable, Perplexity, SearXNG
(keyed), the anonymous Exa/Parallel/Keenable/Tavily free tiers, ddgs, and a local page reader.
Configured under ``[web]`` in ``config/atlas.toml`` (see :mod:`atlas.websearch.settings`).

Translated from Hermes Agent's web stack (NousResearch/hermes-agent@c9e076b); Atlas owns this
code and imports nothing from Hermes. Source map: ``core/atlas/engine/PORTED.md``.
"""

from atlas.websearch.service import WebSearchService, get_service
from atlas.websearch.settings import WebSettings, load_settings

__all__ = ["WebSearchService", "WebSettings", "get_service", "load_settings"]
