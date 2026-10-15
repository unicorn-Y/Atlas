# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: plugins/web/exa/provider.py (MIT)
"""Keyed REST providers: Bocha, Exa, Parallel, Tavily, Brave, Keenable, Perplexity, SearXNG.

Exa / Parallel / Tavily / Brave / Keenable / Perplexity / SearXNG are translated from Hermes
``plugins/web/<vendor>/provider.py`` (NousResearch/hermes-agent@c9e076b), rewritten against the
vendors' REST APIs with async httpx — Atlas carries no exa-py / parallel-web SDK. Bocha
(博查, bochaai.com) is Atlas's own: the Chinese-native index Hermes does not have.

A keyed provider without its key reports ``available() == False`` and is skipped by the
service; when the user has registered a key for Exa / Parallel / Tavily / Keenable the paid
path is used, otherwise those vendors are still reachable through the keyless ring.
"""

from __future__ import annotations

from typing import Any

from atlas.websearch.common import (
    SEARCH_LIMIT_CAP, VENDOR_ERRORS, document, get_json, hit, page_error, post_json, search_fail, search_ok,
)
from atlas.websearch.providers.base import WebProvider
from atlas.websearch.settings import WebSettings


class BochaProvider(WebProvider):
    """博查 Web Search API — native Chinese index with page summaries and publish dates."""

    name, display_name, signup_url = "bocha", "Bocha", "https://open.bochaai.com"
    ENDPOINT = "https://api.bochaai.com/v1/web-search"

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        key = settings.key(self.name)
        if not key:
            return search_fail(self.missing_key())

        async def _body() -> dict[str, Any]:
            data = await post_json(self.ENDPOINT, {
                "query": query, "freshness": "noLimit", "summary": True,
                "count": max(1, min(limit, 50)),
            }, headers={"Authorization": f"Bearer {key}"})
            if isinstance(data, dict) and data.get("code") not in (None, 200, "200"):
                raise ValueError(f"code {data.get('code')}: {data.get('msg') or data.get('message') or ''}")
            pages = ((data.get("data") or {}).get("webPages") or {}).get("value") or []
            return search_ok([
                hit(p.get("url") or "", p.get("name") or "", p.get("summary") or p.get("snippet") or "", i + 1,
                    site=p.get("siteName") or "", published=p.get("datePublished") or "")
                for i, p in enumerate(pages[:limit])
            ])

        return await self.guard_search(_body)


class ExaProvider(WebProvider):
    name, display_name, signup_url = "exa", "Exa", "https://exa.ai"
    can_extract = True
    BASE = "https://api.exa.ai"

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        key = settings.key(self.name)
        if not key:
            return search_fail(self.missing_key())

        async def _body() -> dict[str, Any]:
            data = await post_json(f"{self.BASE}/search", {
                "query": query, "numResults": limit, "type": "auto", "contents": {"highlights": True},
            }, headers={"x-api-key": key})
            return search_ok([
                hit(r.get("url") or "", r.get("title") or "", " ".join(r.get("highlights") or []), i + 1,
                    published=(r.get("publishedDate") or "")[:10])
                for i, r in enumerate(data.get("results") or [])
            ])

        return await self.guard_search(_body)

    async def extract(self, urls: list[str], settings: WebSettings) -> list[dict[str, Any]]:
        key = settings.key(self.name)
        if not key:
            return [page_error(u, self.missing_key()) for u in urls]

        async def _body() -> list[dict[str, Any]]:
            data = await post_json(f"{self.BASE}/contents", {"urls": urls, "text": True}, headers={"x-api-key": key}, timeout=60)
            got = {r.get("url") or "": r for r in data.get("results") or []}
            out = []
            for url in urls:
                r = got.get(url) or next((v for v in got.values() if (v.get("id") or "") == url), None)
                out.append(document(url, r.get("title") or "", r.get("text") or "", served_by="exa") if r
                           else page_error(url, "Exa returned no content"))
            return out

        return await self.guard_extract(urls, _body)


class ParallelProvider(WebProvider):
    name, display_name, signup_url = "parallel", "Parallel", "https://parallel.ai"
    can_extract = True
    BASE = "https://api.parallel.ai/v1"

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        key = settings.key(self.name)
        if not key:
            return search_fail(self.missing_key())

        async def _body() -> dict[str, Any]:
            data = await post_json(f"{self.BASE}/search", {
                "objective": query, "search_queries": [query], "mode": settings.parallel_mode,
                "advanced_settings": {"max_results": min(limit, SEARCH_LIMIT_CAP)},
            }, headers={"x-api-key": key})
            return search_ok([
                hit(r.get("url") or "", r.get("title") or "", " ".join(r.get("excerpts") or [])[:1200], i + 1,
                    published=r.get("publish_date") or "")
                for i, r in enumerate(data.get("results") or [])
            ])

        return await self.guard_search(_body)

    async def extract(self, urls: list[str], settings: WebSettings) -> list[dict[str, Any]]:
        key = settings.key(self.name)
        if not key:
            return [page_error(u, self.missing_key()) for u in urls]

        async def _body() -> list[dict[str, Any]]:
            data = await post_json(f"{self.BASE}/extract", {
                "urls": urls, "advanced_settings": {"full_content": True},
            }, headers={"x-api-key": key}, timeout=90)
            got = {r.get("url") or "": r for r in data.get("results") or []}
            errors = {e.get("url") or "": e for e in data.get("errors") or []}
            out = []
            for url in urls:
                if r := got.get(url):
                    content = r.get("full_content") or "\n\n".join(r.get("excerpts") or [])
                    out.append(document(url, r.get("title") or "", content, served_by="parallel"))
                else:
                    e = errors.get(url) or {}
                    out.append(page_error(url, str(e.get("content") or e.get("error_type") or "no content returned")))
            return out

        return await self.guard_extract(urls, _body)


class TavilyProvider(WebProvider):
    name, display_name, signup_url = "tavily", "Tavily", "https://app.tavily.com/home"
    can_extract = True
    BASE = "https://api.tavily.com"

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        key = settings.key(self.name)
        if not key:
            return search_fail(self.missing_key())

        async def _body() -> dict[str, Any]:
            data = await post_json(f"{self.BASE}/search", {
                "query": query, "max_results": min(limit, SEARCH_LIMIT_CAP),
                "include_raw_content": False, "include_images": False,
            }, headers={"Authorization": f"Bearer {key}"}, timeout=60)
            return search_ok([
                hit(r.get("url", ""), r.get("title", ""), r.get("content", ""), i + 1,
                    published=r.get("published_date") or "")
                for i, r in enumerate(data.get("results") or [])
            ])

        return await self.guard_search(_body)

    async def extract(self, urls: list[str], settings: WebSettings) -> list[dict[str, Any]]:
        key = settings.key(self.name)
        if not key:
            return [page_error(u, self.missing_key()) for u in urls]

        async def _body() -> list[dict[str, Any]]:
            data = await post_json(f"{self.BASE}/extract", {"urls": urls, "include_images": False},
                                   headers={"Authorization": f"Bearer {key}"}, timeout=60)
            got = {r.get("url", ""): r for r in data.get("results") or []}
            failed = {f.get("url", ""): f.get("error", "extraction failed") for f in data.get("failed_results") or []}
            return [document(u, got[u].get("title", ""), got[u].get("raw_content") or got[u].get("content", ""), served_by="tavily")
                    if u in got else page_error(u, str(failed.get(u, "extraction failed"))) for u in urls]

        return await self.guard_extract(urls, _body)


class BraveProvider(WebProvider):
    """Brave Search API — search only; strong on freshness and country/language filters."""

    name, display_name, signup_url = "brave", "Brave Search", "https://brave.com/search/api/"
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        key = settings.key(self.name)
        if not key:
            return search_fail(self.missing_key())

        async def _body() -> dict[str, Any]:
            data = await get_json(self.ENDPOINT, params={"q": query, "count": min(limit, 20)},
                                  headers={"X-Subscription-Token": key})
            rows = ((data.get("web") or {}).get("results") or [])[:limit]
            return search_ok([
                hit(str(r.get("url", "")), str(r.get("title", "")), str(r.get("description", "")), i + 1,
                    published=str(r.get("page_age") or r.get("age") or ""))
                for i, r in enumerate(rows)
            ])

        return await self.guard_search(_body)


class KeenableProvider(WebProvider):
    name, display_name, signup_url = "keenable", "Keenable", "https://keenable.ai"
    can_extract = True
    BASE = "https://api.keenable.ai"

    def _headers(self, key: str) -> dict[str, str]:
        return {"X-Keenable-Title": "atlas", "Authorization": f"Bearer {key}"}

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        key = settings.key(self.name)
        if not key:
            return search_fail(self.missing_key())

        async def _body() -> dict[str, Any]:
            data = await post_json(f"{self.BASE}/v1/search", {"query": query, "max_results": limit}, headers=self._headers(key))
            return search_ok([
                hit(r.get("url") or "", r.get("title") or "", r.get("snippet") or r.get("description") or "", i + 1)
                for i, r in enumerate(data.get("results") or [])
            ])

        return await self.guard_search(_body)

    async def extract(self, urls: list[str], settings: WebSettings) -> list[dict[str, Any]]:
        key = settings.key(self.name)
        if not key:
            return [page_error(u, self.missing_key()) for u in urls]
        out = []
        for url in urls:
            try:
                data = await get_json(f"{self.BASE}/v1/fetch", params={"url": url}, headers=self._headers(key), timeout=30)
                out.append(document(data.get("url") or url, data.get("title") or "", data.get("content") or "", served_by="keenable"))
            except VENDOR_ERRORS as exc:
                out.append(page_error(url, f"Keenable extract failed: {exc}"))
        return out


class PerplexityProvider(WebProvider):
    """Perplexity Search API (raw ranked results, not Sonar answers)."""

    name, display_name, signup_url = "perplexity", "Perplexity", "https://www.perplexity.ai/settings/api"
    ENDPOINT = "https://api.perplexity.ai/search"

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        key = settings.key(self.name)
        if not key:
            return search_fail(self.missing_key())

        async def _body() -> dict[str, Any]:
            # search_context_size "low" keeps snippets result-list sized; full pages belong to web_fetch.
            data = await post_json(self.ENDPOINT, {
                "query": query, "max_results": min(limit, SEARCH_LIMIT_CAP), "search_context_size": "low",
            }, headers={"Authorization": f"Bearer {key}"}, timeout=60)
            return search_ok([
                hit(r.get("url", "") or "", r.get("title", "") or "", r.get("snippet", "") or "", i + 1,
                    published=r.get("date") or "")
                for i, r in enumerate(data.get("results") or [])
            ])

        return await self.guard_search(_body)


class SearXNGProvider(WebProvider):
    """A user-hosted SearXNG instance (``[web.keys] searxng = "http://localhost:8080"``)."""

    name, display_name, signup_url = "searxng", "SearXNG", "https://docs.searxng.org"

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        base = settings.key(self.name).rstrip("/")
        if not base:
            return search_fail(self.missing_key())

        async def _body() -> dict[str, Any]:
            data = await get_json(f"{base}/search", params={"q": query, "format": "json", "pageno": 1}, timeout=15)
            raw = sorted(data.get("results") or [], key=lambda r: float(r.get("score", 0) or 0), reverse=True)[:limit]
            return search_ok([
                hit(str(r.get("url", "")), str(r.get("title", "")), str(r.get("content", "")), i + 1,
                    published=str(r.get("publishedDate") or ""))
                for i, r in enumerate(raw)
            ])

        return await self.guard_search(_body)
