# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: plugins/web/_common.py (MIT)
"""Shared result shapes, HTTP helpers and failure classification for Atlas web search.

Translated from Hermes ``plugins/web/_common.py`` + the failover heuristics of
``plugins/web/keyless_mcp.py`` (NousResearch/hermes-agent@c9e076b). Atlas owns this
code: async httpx throughout, no Hermes config/plugin/pm plumbing.

Result contract (every provider returns these shapes, never raises)::

    search:  {"success": True, "data": {"web": [{"title", "url", "description", "position", ...}]}}
    extract: [{"url", "title", "content", "error"?, "metadata"?}, ...]
    failure: {"success": False, "error": str}
"""

from __future__ import annotations

import re
from typing import Any

import httpx

SEARCH_LIMIT_CAP = 20  # every vendor here caps max_results at 20 server-side
USER_AGENT = "Atlas/1.0 (+web-search)"

# What a vendor call can raise: transport (httpx / OS / timeout), vendor errors surfaced as
# ValueError / RuntimeError, and malformed payloads (KeyError / TypeError / AttributeError).
VENDOR_ERRORS: tuple[type[BaseException], ...] = (
    httpx.HTTPError, OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError,
)


def search_ok(rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"web": rows}
    data.update(extra)
    return {"success": True, "data": data}


def search_fail(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def hit(url: str, title: str, description: str, position: int, **extra: Any) -> dict[str, Any]:
    row = {"title": title or "", "url": url or "", "description": (description or "").strip(), "position": position}
    for key, value in extra.items():
        if value:
            row[key] = value
    return row


def document(url: str, title: str, content: str, **metadata: Any) -> dict[str, Any]:
    return {"url": url, "title": title or "", "content": content or "",
            "metadata": {k: v for k, v in metadata.items() if v}}


def page_error(url: str, error: str) -> dict[str, Any]:
    return {"url": url, "title": "", "content": "", "error": error}


def extract_fail(urls: list[str], error: str) -> list[dict[str, Any]]:
    return [page_error(u, error) for u in urls]


# --- failure classification (decides whether the next provider may serve the call) ---

_RATE_LIMIT_MARKERS = ("rate limit", "rate-limit", "ratelimit", "too many requests", "429",
                       "quota exceeded", "quota", "slow down", "insufficient", "余额", "额度", "频率")

# Vendor refusals / outages: 401/402/403 and 5xx anchored at the start of the message, so an
# error that merely echoes the query ("HTTP 400: invalid query 'http 503'") does not match.
_VENDOR_REFUSAL_RE = re.compile(
    r"\s*(?:[\w ]+?(?:search|extract)\s+failed:\s*)?"
    r"(?:http(?:\s+status)?|status(?:\s+code)?|client\s+error|error\s+code)"
    r"\s*[:=']*\s*(?:40[123]|5\d\d)\b",
    re.IGNORECASE,
)


def is_rate_limited(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _RATE_LIMIT_MARKERS)


def is_vendor_side(message: str) -> bool:
    """True when another provider could plausibly serve the same call: throttling, refusals,
    outages, timeouts, transport errors. A malformed query is the caller's fault and fails
    everywhere, but Atlas treats almost every vendor error as vendor-side because the chain is
    short and a wasted retry is cheaper than a missing answer."""
    if not message:
        return True
    if is_rate_limited(message) or _VENDOR_REFUSAL_RE.match(message):
        return True
    lowered = message.lower()
    return any(token in lowered for token in (
        "timed out", "timeout", "could not reach", "connect", "network", "ssl", "eof",
        "unexpected payload", "parse", "not set", "no results", "unauthorized", "forbidden",
    ))


# --- HTTP ---

def http_detail(response: httpx.Response) -> str:
    body = (response.text or "").strip()
    return f"HTTP {response.status_code}: {body[:300]}" if body else f"HTTP {response.status_code}"


def decoded_text(response: httpx.Response) -> str:
    """Body decoded with the declared charset, else UTF-8 (SSE bodies carry no charset and a
    latin-1 guess turns every CJK result into mojibake)."""
    content_type = response.headers.get("content-type", "").lower()
    charset = None
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip() or None
    try:
        return response.content.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return response.content.decode("utf-8", errors="replace")


def client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Vendor API client. ``trust_env`` keeps the user's system proxy (Clash) in the path; vendor
    hosts are fixed public endpoints, so the SSRF guard used for arbitrary page fetches is not
    needed here."""
    return httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}, trust_env=True)


def describe(exc: BaseException) -> str:
    """``Type: message`` — httpx transport errors often carry an empty message."""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


async def _with_retry(send, timeout: float) -> httpx.Response:
    """One retry on a connect-level failure (fresh proxy tunnel, TLS reset). Read timeouts and
    HTTP errors are not retried: the vendor saw the request and may have billed it."""
    for attempt in (1, 2):
        try:
            async with client(timeout) as http:
                return await send(http)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


async def post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None,
                    timeout: float = 30.0) -> Any:
    """POST JSON, return parsed JSON. Raises ``ValueError`` carrying the vendor's own error text."""
    async def _send(http: httpx.AsyncClient) -> httpx.Response:
        return await http.post(url, json=payload, headers={"Content-Type": "application/json", **(headers or {})})

    response = await _with_retry(_send, timeout)
    if response.status_code >= 400:
        raise ValueError(http_detail(response))
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"unexpected payload (not JSON): {decoded_text(response)[:200]!r}") from exc


async def get_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
                   timeout: float = 20.0) -> Any:
    async def _send(http: httpx.AsyncClient) -> httpx.Response:
        return await http.get(url, params=params, headers={"Accept": "application/json", **(headers or {})})

    response = await _with_retry(_send, timeout)
    if response.status_code >= 400:
        raise ValueError(http_detail(response))
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"unexpected payload (not JSON): {decoded_text(response)[:200]!r}") from exc


def clamp_limit(limit: Any, default: int = 5) -> int:
    try:
        return max(1, min(int(limit), SEARCH_LIMIT_CAP))
    except (TypeError, ValueError):
        return default
