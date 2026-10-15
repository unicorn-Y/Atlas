"""Keyed web-search APIs used ahead of the scraped engines in ``atlas.tools.web``.

Bocha (博查, api.bochaai.com) is the primary: a mainland service, reachable
without a proxy. Tavily (api.tavily.com) is the second: good English results,
1000 free credits a month, but abroad, so it goes through the system proxy
first. Keys live in the OS credential store (set from Settings → 联网搜索);
``BOCHA_API_KEY`` / ``TAVILY_API_KEY`` environment variables also work, which is
what SSH sessions and tests use, since Windows network logons have no
credential store.

Request/response shapes follow the providers' docs:
- Bocha ``POST /v1/web-search`` {query, count, summary} →
  ``data.webPages.value[]`` {name, url, snippet, summary}
- Tavily ``POST /search`` {query, max_results, include_domains, exclude_domains} →
  ``results[]`` {title, url, content}
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchProvider:
    id: str
    name: str
    credential_key: str
    env_var: str
    signup_url: str
    proxy_first: bool


PROVIDERS: tuple[SearchProvider, ...] = (
    SearchProvider("bocha", "博查", "atlas.search.bocha_api_key", "BOCHA_API_KEY",
                   "https://open.bochaai.com/", proxy_first=False),
    SearchProvider("tavily", "Tavily", "atlas.search.tavily_api_key", "TAVILY_API_KEY",
                   "https://app.tavily.com/", proxy_first=True),
)
PROVIDERS_BY_ID = {provider.id: provider for provider in PROVIDERS}


class SearchAPIError(RuntimeError):
    """A keyed search API answered with an error (bad key, quota, outage)."""


def _credential_store() -> Any:
    from atlas.telegram import KeyringCredentialStore

    return KeyringCredentialStore()


def api_key(provider: SearchProvider) -> tuple[str | None, str | None]:
    """(key, source) where source is ``"keyring"`` or ``"env"``; (None, None) when unset."""
    try:
        stored = _credential_store().get(provider.credential_key)
    except Exception:  # noqa: BLE001 — no credential store (SSH logon, headless): try env
        logger.debug("atlas.tools.search_api: credential store unavailable", exc_info=True)
        stored = None
    if stored and stored.strip():
        return stored.strip(), "keyring"
    env = os.environ.get(provider.env_var, "").strip()
    if env:
        return env, "env"
    return None, None


async def _post_json(provider: SearchProvider, url: str, key: str,
                     body: dict[str, Any], proxy: str | None) -> dict[str, Any]:
    """POST over the provider's preferred route first, the other one second."""
    if proxy:
        routes: Sequence[str | None] = (proxy, None) if provider.proxy_first else (None, proxy)
    else:
        routes = (None,)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last: Exception | None = None
    for route in routes:
        try:
            async with httpx.AsyncClient(proxy=route, timeout=20.0, trust_env=False) as client:
                response = await client.post(url, json=body, headers=headers)
        except httpx.TransportError as exc:
            last = exc
            continue
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code != 200:
            detail = ""
            if isinstance(payload, dict):
                detail = str(payload.get("msg") or payload.get("message")
                             or payload.get("detail") or payload.get("error") or "")
            if response.status_code in (401, 403):
                detail = detail or "API key 无效或已停用"
            raise SearchAPIError(f"HTTP {response.status_code}: {detail}".rstrip(": "))
        return payload if isinstance(payload, dict) else {}
    assert last is not None
    raise last


async def bocha_search(key: str, query: str, count: int, *,
                       proxy: str | None) -> list[dict[str, str]]:
    payload = await _post_json(
        PROVIDERS_BY_ID["bocha"], "https://api.bochaai.com/v1/web-search", key,
        {"query": query, "count": max(1, min(count, 50)), "summary": True, "freshness": "noLimit"},
        proxy,
    )
    code = payload.get("code")
    if code not in (None, 200, "200"):
        raise SearchAPIError(f"code {code}: {payload.get('msg') or ''}".rstrip(": "))
    data = payload.get("data") or {}
    items = ((data.get("webPages") or {}).get("value")) or []
    results: list[dict[str, str]] = []
    for item in items:
        url = str(item.get("url") or "")
        title = str(item.get("name") or "").strip()
        if not url.startswith("http") or not title:
            continue
        result = {"title": title, "url": url}
        snippet = str(item.get("summary") or item.get("snippet") or "").strip()
        if snippet:
            result["snippet"] = snippet
        if item.get("datePublished"):
            result["published"] = str(item["datePublished"])
        results.append(result)
    return results


async def tavily_search(key: str, query: str, count: int, *, proxy: str | None,
                        allowed: Sequence[str] = (),
                        blocked: Sequence[str] = ()) -> list[dict[str, str]]:
    body: dict[str, Any] = {"query": query, "max_results": max(1, min(count, 20)),
                            "search_depth": "basic"}
    if allowed:
        body["include_domains"] = list(allowed)
    if blocked:
        body["exclude_domains"] = list(blocked)
    payload = await _post_json(PROVIDERS_BY_ID["tavily"], "https://api.tavily.com/search",
                               key, body, proxy)
    results: list[dict[str, str]] = []
    for item in payload.get("results") or []:
        url = str(item.get("url") or "")
        title = str(item.get("title") or "").strip()
        if not url.startswith("http") or not title:
            continue
        result = {"title": title, "url": url}
        snippet = str(item.get("content") or "").strip()
        if snippet:
            result["snippet"] = snippet
        results.append(result)
    return results
