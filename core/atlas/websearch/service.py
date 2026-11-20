# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: tools/web_tools.py (MIT)
"""Atlas web search service: ordered provider chain with per-call failover, caching, routing.

Translated from the dispatch half of Hermes ``tools/web_tools.py`` and
``tools/web_tools_rescue.py`` (NousResearch/hermes-agent@c9e076b), reshaped for Atlas:

* Hermes resolves ONE backend and, on failure, does a one-shot keyless rescue. Atlas walks the
  whole configured chain: every available provider is tried in order until one returns results,
  so a dead key, an exhausted quota or a vendor outage costs one hop, not the answer.
* Chinese queries use ``[web] search_order_zh`` (Bocha first); see :mod:`.router`.
* Page reads start with the free local reader and fall back to vendor extractors per URL.
* Every answer says which provider served it and which ones failed on the way, so a bad
  result can be traced in the run log.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from collections.abc import Sequence

from atlas.websearch import cache
from atlas.websearch.common import clamp_limit, search_fail
from atlas.websearch.providers import get_provider
from atlas.websearch.router import is_chinese_query
from atlas.websearch.settings import WebSettings, load_settings

logger = logging.getLogger("atlas.websearch")


def _host(url: str) -> str:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _domain_matches(host: str, domains: Sequence[str]) -> bool:
    for entry in domains:
        pattern = str(entry or "").strip().casefold().removeprefix("*.").removeprefix("www.")
        if pattern and (host == pattern or host.endswith("." + pattern)):
            return True
    return False


def _filter_rows(rows: list[dict], allowed: list[str], blocked: list[str]) -> list[dict]:
    kept = []
    for row in rows:
        host = _host(str(row.get("url") or ""))
        if allowed and not _domain_matches(host, allowed):
            continue
        if blocked and _domain_matches(host, blocked):
            continue
        kept.append(row)
    return kept


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for row in rows:
        key = str(row.get("url") or "").rstrip("/").split("#", 1)[0]
        if key and key not in seen:
            seen.add(key)
            out.append(row)
    for i, row in enumerate(out):
        row["position"] = i + 1
    return out


class WebSearchService:
    def __init__(self, settings: WebSettings | None = None) -> None:
        self._settings = settings

    @property
    def settings(self) -> WebSettings:
        # Re-read each call so editing [web] in atlas.toml (and reload_config) takes effect live.
        return self._settings or load_settings()

    def chain(self, kind: str, *, chinese: bool = False) -> list[str]:
        s = self.settings
        order = s.extract_order if kind == "extract" else (s.search_order_zh if chinese else s.search_order)
        names: list[str] = []
        for name in order:
            provider = get_provider(name)
            if provider is None or provider.name in names:
                continue
            capable = provider.can_extract if kind == "extract" else provider.can_search
            if capable and provider.available(s):
                names.append(provider.name)
        return names

    # --- search -----------------------------------------------------------------

    async def search(self, query: str, limit: int = 5, *, allowed_domains: Sequence[str] = (),
                     blocked_domains: Sequence[str] = ()) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return search_fail("query is required")
        limit = clamp_limit(limit)
        allowed = [d for d in (str(x).strip() for x in allowed_domains or []) if d]
        blocked = [d for d in (str(x).strip() for x in blocked_domains or []) if d]
        chinese = is_chinese_query(query, allowed)
        names = self.chain("search", chinese=chinese)
        if not names:
            return search_fail("no web search provider is available — set a key under [web.keys] in "
                               "config/atlas.toml or enable [web] keyless = true")
        vendor_query = query
        if allowed and len(allowed) == 1:
            vendor_query = f"{query} site:{allowed[0]}"
        # Over-fetch when results will be filtered client-side.
        fetch = min(20, limit * 3) if (allowed or blocked) else limit

        s = self.settings
        key = cache.search_memo.key("zh" if chinese else "en", f"{vendor_query}|{','.join(blocked)}", fetch)
        if s.cache_enabled and (hit := cache.search_memo.lookup(key)) is not None:
            hit.setdefault("data", {})["cached"] = True
            return cache.slice_rows(hit, limit)
        async with cache.search_memo.lock(key):
            if s.cache_enabled and (hit := cache.search_memo.lookup(key)) is not None:
                hit.setdefault("data", {})["cached"] = True
                return cache.slice_rows(hit, limit)
            result = await self._walk_search(names, vendor_query, fetch, allowed, blocked)
            if s.cache_enabled:
                cache.search_memo.store(key, result, s.cache_ttl_minutes * 60)
        return cache.slice_rows(result, limit)

    async def _walk_search(self, names: list[str], query: str, limit: int,
                           allowed: list[str], blocked: list[str]) -> dict[str, Any]:
        s = self.settings
        failures: list[str] = []
        for name in names:
            provider = get_provider(name)
            started = time.monotonic()
            result = await provider.search(query, limit, s)
            elapsed = time.monotonic() - started
            if result.get("success"):
                data = result.get("data") or {}
                rows = _dedupe(_filter_rows(list(data.get("web") or []), allowed, blocked))
                if rows:
                    served = str(data.get("served_by") or name)
                    logger.info("web_search ok via %s in %.1fs (%d results): %r", served, elapsed, len(rows), query)
                    for row in rows:
                        row.setdefault("provider", served)
                    extra = {"served_by": served}
                    if failures:
                        extra["fallbacks"] = failures
                    return {"success": True, "data": {"web": rows, **extra}}
                failures.append(f"{name}: no results")
            else:
                failures.append(f"{name}: {str(result.get('error') or 'failed')[:240]}")
            logger.info("web_search %s failed in %.1fs (%s); trying next", name, elapsed, failures[-1][:160])
        return search_fail("every web search provider failed — " + " | ".join(failures))

    # --- extract ----------------------------------------------------------------

    async def extract(self, urls: Sequence[str], *, char_limit: int | None = None) -> list[dict[str, Any]]:
        s = self.settings
        limit = max(200, min(int(char_limit or s.extract_char_limit), 500_000))
        urls = [str(u).strip() for u in urls if str(u).strip()]
        results: dict[str, dict[str, Any]] = {}
        policy_errors: dict[str, dict[str, Any]] = {}
        pending: list[str] = []
        for url in urls:
            if s.cache_enabled and (hit := cache.extract_cache_get(url, s.cache_ttl_minutes * 60)):
                results[url] = hit
            else:
                pending.append(url)
        failures: dict[str, list[str]] = {u: [] for u in pending}
        for name in self.chain("extract"):
            if not pending:
                break
            provider = get_provider(name)
            pages = await provider.extract(list(pending), s)
            by_url = {str(p.get("url") or ""): p for p in pages}
            still: list[str] = []
            for index, url in enumerate(pending):
                page = by_url.get(url) or (pages[index] if index < len(pages) and len(pages) == len(pending) else None)
                if page and not page.get("error") and (page.get("content") or "").strip():
                    page.setdefault("metadata", {}).setdefault("served_by", name)
                    if failures[url]:
                        page["metadata"]["fallbacks"] = failures[url]
                    results[url] = page
                    if s.cache_enabled:
                        cache.extract_cache_put(url, page)
                else:
                    if page and page.get("error_category") == "policy":
                        policy_errors[url] = page
                    else:
                        failures[url].append(f"{name}: {str((page or {}).get('error') or 'no content')[:200]}")
                        still.append(url)
            pending = still
        out = []
        for url in urls:
            if url in policy_errors:
                page = policy_errors[url]
                out.append({"url": url, "title": "", "content": "",
                            "error": str(page.get("error") or "web request rejected by policy"),
                            "error_category": "policy"})
                continue
            page = results.get(url)
            if page is None:
                reason = " | ".join(failures.get(url) or ["no web extract provider is available"])
                logger.info("web_fetch failed for %s: %s", url, reason[:300])
                out.append({"url": url, "title": "", "content": "", "error": f"could not read the page — {reason}"})
                continue
            text = cache.strip_base64_images(str(page.get("content") or ""))
            text, truncated = cache.truncate(text, url, limit)
            meta = dict(page.get("metadata") or {})
            logger.info("web_fetch ok via %s: %s (%d chars%s)", meta.get("served_by"), url, len(text),
                        ", truncated" if truncated else "")
            out.append({"url": str(page.get("url") or url), "title": str(page.get("title") or ""), "content": text,
                        "truncated": truncated or bool(meta.get("truncated")), "metadata": meta,
                        **({"status_code": meta["status_code"]} if isinstance(meta.get("status_code"), int) else {})})
        return out


_service: WebSearchService | None = None


def get_service() -> WebSearchService:
    global _service
    if _service is None:
        _service = WebSearchService()
    return _service
