# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: plugins/web/keyless_mcp.py (MIT)
"""Anonymous free-tier search/extract ring: Exa, Parallel, Keenable and Tavily public endpoints.

Translated from Hermes ``plugins/web/keyless_mcp.py`` (NousResearch/hermes-agent@c9e076b).
Changes for Atlas: async httpx, Tavily joins the ring (its keyless header works), Firecrawl is
dropped (its anonymous tier refuses proxy/VPN exit IPs, which is how Atlas reaches the web),
and the ring is configured from ``[web] keyless`` instead of Hermes provider tiers.

Privacy: no user identifiers are sent. Parallel gets a random per-process ``session_id`` (its
free tier rate-limits on it); Exa / Keenable / Tavily get only the query.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import threading
import uuid
from typing import Any
from collections.abc import Awaitable, Callable

from atlas.websearch.common import (
    VENDOR_ERRORS, client, decoded_text, document, hit, http_detail, is_rate_limited, is_vendor_side, page_error,
    search_fail, search_ok,
)

logger = logging.getLogger("atlas.websearch")

EXA_MCP_URL = "https://mcp.exa.ai/mcp"
PARALLEL_MCP_URL = "https://search.parallel.ai/mcp"
KEENABLE_API_URL = "https://api.keenable.ai"
TAVILY_API_URL = "https://api.tavily.com"
_APP_TITLE = "atlas"
_TIMEOUT = 30.0
_SESSION_ID = uuid.uuid4().hex

RING = ("exa", "parallel", "keenable", "tavily")


class KeylessError(RuntimeError):
    """A keyless call failed (transport, rate limit, or tool error)."""


# --- MCP transport -------------------------------------------------------------

def parse_mcp_body(body: str) -> str:
    """First text item of an MCP ``tools/call`` reply: plain JSON (Parallel) or SSE ``data:``
    lines (Exa). Split on SSE terminators only — ``str.splitlines`` also breaks on U+2028/U+0085,
    which occur inside CJK page text."""

    def _from(payload: str) -> str | None:
        payload = payload.strip()
        if not payload.startswith("{"):
            return None
        data = json.loads(payload)
        if err := data.get("error"):
            raise KeylessError(str(err.get("message") if isinstance(err, dict) else err))
        result = data.get("result") or {}
        texts = [c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict)]
        if result.get("isError"):
            raise KeylessError(" ".join(t for t in texts if t) or "MCP tool call failed")
        return next((str(t) for t in texts if t), "")

    stripped = body.strip()
    candidates = [stripped] if stripped.startswith("{") else []
    candidates += [line[len("data: "):] for line in re.split(r"\r\n|\r|\n", body) if line.startswith("data: ")]
    seen_envelope = False
    for candidate in candidates:
        try:
            text = _from(candidate)
        except json.JSONDecodeError:
            continue
        if text:
            return text
        seen_envelope = seen_envelope or text == ""
    raise KeylessError("MCP response contained no text content" if seen_envelope else "Unrecognized MCP response shape")


async def mcp_call(url: str, tool: str, arguments: dict[str, Any], timeout: float = _TIMEOUT) -> str:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        async with client(timeout) as http:
            response = await http.post(url, json=payload, headers=headers)
    except Exception as exc:
        raise KeylessError(f"request failed: {type(exc).__name__}: {exc}") from exc
    if response.status_code >= 400:
        raise KeylessError(http_detail(response))
    return parse_mcp_body(decoded_text(response))


# --- Exa (mcp.exa.ai): ``---`` separated Title:/URL:/Published:/Highlights: blocks ----------

_EXA_LABELS = ("Title:", "URL:", "Highlights:", "Published:", "Author:")


def parse_exa_search_text(text: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in text.split("\n---\n"):
        title = url = published = ""
        highlights: list[str] = []
        in_highlights = False
        for line in map(str.strip, block.splitlines()):
            if line.startswith("Title:"):
                title = line[6:].strip()
            elif line.startswith("URL:"):
                url = line[4:].strip()
            elif line.startswith("Published:"):
                value = line[10:].strip()
                published = "" if value in {"N/A", "None"} else value
            elif in_highlights and line and not line.startswith(_EXA_LABELS):
                highlights.append(line)
            if line.startswith(_EXA_LABELS):
                in_highlights = line.startswith("Highlights:")
        if url:
            rows.append(hit(url, title, " ".join(highlights), len(rows) + 1, published=published))
        if limit and len(rows) >= limit:
            break
    return rows


async def exa_search(query: str, limit: int) -> list[dict[str, Any]]:
    text = await mcp_call(EXA_MCP_URL, "web_search_exa", {"query": query, "numResults": max(1, limit)})
    return parse_exa_search_text(text, limit)


async def exa_extract(url: str) -> dict[str, Any]:
    text = await mcp_call(EXA_MCP_URL, "web_fetch_exa", {"urls": [url]})
    titles = (s[2:].strip() if s.startswith("# ") else s[6:].strip()
              for s in map(str.strip, text.splitlines()) if s.startswith(("# ", "Title:")))
    return document(url, next(titles, ""), text, served_by="exa")


# --- Parallel (search.parallel.ai/mcp): JSON text payloads ------------------------

async def parallel_search(query: str, limit: int) -> list[dict[str, Any]]:
    text = await mcp_call(PARALLEL_MCP_URL, "web_search",
                          {"objective": query, "search_queries": [query], "session_id": _SESSION_ID})
    try:
        results = json.loads(text).get("results") or []
    except (json.JSONDecodeError, AttributeError) as exc:
        raise KeylessError(f"unexpected payload: {exc}") from exc
    return [hit(r.get("url") or "", r.get("title") or "", " ".join(r.get("excerpts") or [])[:1200], i + 1,
                published=r.get("publish_date") or "")
            for i, r in enumerate(results[:limit])]


async def parallel_extract(url: str) -> dict[str, Any]:
    text = await mcp_call(PARALLEL_MCP_URL, "web_fetch",
                          {"urls": [url], "objective": "Full page content", "session_id": _SESSION_ID})
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KeylessError(f"unexpected payload: {exc}") from exc
    for r in data.get("results") or []:
        content = r.get("full_content") or r.get("content") or "\n\n".join(r.get("excerpts") or [])
        return document(r.get("url") or url, r.get("title") or "", content, served_by="parallel")
    errors = data.get("errors") or []
    detail = errors[0].get("content") or errors[0].get("error_type") if errors else "no content returned"
    raise KeylessError(str(detail))


# --- Keenable (api.keenable.ai public endpoints) ------------------------------------

async def _keenable(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    headers = {"X-Keenable-Title": _APP_TITLE}
    try:
        async with client(_TIMEOUT) as http:
            response = await http.request(method, f"{KEENABLE_API_URL}{path}", headers=headers, **kwargs)
    except Exception as exc:
        raise KeylessError(f"request failed: {type(exc).__name__}: {exc}") from exc
    if response.status_code >= 400:
        raise KeylessError(http_detail(response))
    return response.json()


async def keenable_search(query: str, limit: int) -> list[dict[str, Any]]:
    data = await _keenable("POST", "/v1/search/public", json={"query": query, "max_results": max(1, limit)})
    return [hit(r.get("url") or "", r.get("title") or "", r.get("snippet") or r.get("description") or "", i + 1)
            for i, r in enumerate(data.get("results") or [])]


async def keenable_extract(url: str) -> dict[str, Any]:
    data = await _keenable("GET", "/v1/fetch/public", params={"url": url})
    return document(data.get("url") or url, data.get("title") or "", data.get("content") or "", served_by="keenable")


# --- Tavily (X-Tavily-Access-Mode: keyless) -----------------------------------------

async def _tavily(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"X-Tavily-Access-Mode": "keyless", "X-Client-Name": _APP_TITLE}
    try:
        async with client(60.0) as http:
            response = await http.post(f"{TAVILY_API_URL}/{endpoint}", json=payload, headers=headers)
    except Exception as exc:
        raise KeylessError(f"request failed: {type(exc).__name__}: {exc}") from exc
    if response.status_code >= 400:
        raise KeylessError(http_detail(response))
    return response.json()


async def tavily_search(query: str, limit: int) -> list[dict[str, Any]]:
    data = await _tavily("search", {"query": query, "max_results": max(1, limit), "include_raw_content": False})
    return [hit(r.get("url", ""), r.get("title", ""), r.get("content", ""), i + 1, published=r.get("published_date") or "")
            for i, r in enumerate(data.get("results") or [])]


async def tavily_extract(url: str) -> dict[str, Any]:
    data = await _tavily("extract", {"urls": [url], "include_images": False})
    for r in data.get("results") or []:
        return document(r.get("url") or url, r.get("title", ""), r.get("raw_content") or r.get("content", ""), served_by="tavily")
    failed = data.get("failed_results") or []
    raise KeylessError(str(failed[0].get("error")) if failed else "no content returned")


_SEARCHERS: dict[str, Callable[[str, int], Awaitable[list[dict[str, Any]]]]] = {
    "exa": exa_search, "parallel": parallel_search, "keenable": keenable_search, "tavily": tavily_search,
}
_EXTRACTORS: dict[str, Callable[[str], Awaitable[dict[str, Any]]]] = {
    "exa": exa_extract, "parallel": parallel_extract, "keenable": keenable_extract, "tavily": tavily_extract,
}

# Round-robin start so successive calls spread load over the free tiers instead of
# exhausting one vendor's anonymous quota first.
_ring_lock = threading.Lock()
_ring_cursor = itertools.count(int(_SESSION_ID, 16) % len(RING))


def ring_order(start: str | None = None) -> list[str]:
    if start in RING:
        index = RING.index(start)
    else:
        with _ring_lock:
            index = next(_ring_cursor) % len(RING)
    return list(RING[index:] + RING[:index])


async def search(query: str, limit: int, *, start: str | None = None) -> dict[str, Any]:
    """Walk the ring until a vendor answers with results. Rate limits, refusals, outages and
    empty answers advance to the next vendor."""
    errors: list[str] = []
    for vendor in ring_order(start):
        try:
            rows = await _SEARCHERS[vendor](query, limit)
        except VENDOR_ERRORS as exc:
            message = f"{vendor}: {exc}"
            errors.append(message)
            logger.info("keyless %s search failed (%s); trying next", vendor, str(exc)[:160])
            continue
        if rows:
            return search_ok(rows[:limit], served_by=f"keyless:{vendor}")
        errors.append(f"{vendor}: no results")
    return search_fail("all keyless vendors failed — " + "; ".join(errors))


async def extract(urls: list[str], *, start: str | None = None) -> list[dict[str, Any]]:
    """Per URL: walk the ring until one vendor returns non-empty content."""
    order = ring_order(start)
    results: list[dict[str, Any]] = []
    for url in urls:
        errors: list[str] = []
        for vendor in order:
            try:
                page = await _EXTRACTORS[vendor](url)
            except VENDOR_ERRORS as exc:
                errors.append(f"{vendor}: {str(exc)[:160]}")
                continue
            if (page.get("content") or "").strip():
                results.append(page)
                break
            errors.append(f"{vendor}: empty content")
        else:
            results.append(page_error(url, "keyless extract failed — " + "; ".join(errors)))
    return results


__all__ = ["RING", "KeylessError", "extract", "is_rate_limited", "is_vendor_side", "mcp_call",
           "parse_exa_search_text", "parse_mcp_body", "ring_order", "search"]
