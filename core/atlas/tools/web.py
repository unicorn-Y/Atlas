"""Web access tools for the normal Agent: ``web_search`` + ``web_fetch``.

Both delegate to :mod:`atlas.websearch`, which walks a configured provider chain (Bocha for
Chinese queries, Exa / Brave / Parallel / Tavily / … with keys, the anonymous free tiers, ddgs)
and reads pages locally first, falling back to vendor renderers. Failures come back as
structured errors instead of raising into the agent loop.
"""

from __future__ import annotations

import json
import re
from typing import Any

from atlas.websearch import WebSearchService, get_service


class WebPolicyError(RuntimeError):
    """A web request was denied by URL or redirect policy."""


def _str_list(value: Any) -> list[str]:
    return [str(item).strip() for item in (value or []) if isinstance(item, str) and str(item).strip()]


class WebRuntime:
    """Agent-facing web tools over the shared :class:`WebSearchService`."""

    def __init__(self, service: WebSearchService | None = None) -> None:
        self._service = service

    @property
    def service(self) -> WebSearchService:
        return self._service or get_service()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        try:
            if name == "web_search":
                data = await self.web_search(
                    str(args.get("query", "")), int(args.get("max_results", 5) or 5),
                    allowed_domains=args.get("allowed_domains"),
                    blocked_domains=args.get("blocked_domains"),
                    mode=str(args.get("mode") or "balanced"),
                )
            elif name == "web_fetch":
                data = await self.web_fetch(
                    str(args.get("url", "")), int(args.get("max_chars", 15000) or 15000),
                )
            else:
                return self._error(f"Unknown web tool: {name}")
        except WebPolicyError as exc:
            return self._error(f"{name} failed: {exc}", error_category="policy")
        except (ValueError, RuntimeError, OSError, TypeError) as exc:
            return self._error(f"{name} failed: {exc}")
        return {
            "data": data,
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "is_error": False,
        }

    async def web_search(self, query: str, max_results: int = 5, *,
                         allowed_domains: Any = None,
                         blocked_domains: Any = None,
                         mode: str = "balanced") -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query is required")
        allowed, blocked = _str_list(allowed_domains), _str_list(blocked_domains)
        search_mode = str(mode or "balanced").strip().casefold()
        if search_mode not in {"balanced", "strict", "long"}:
            search_mode = "balanced"
        # "long" asks for a wider sweep; "strict" keeps the list short and on-target.
        count = {"long": max(max_results, 10), "strict": min(max_results, 5)}.get(search_mode, max_results)
        result = await self.service.search(query, count, allowed_domains=allowed, blocked_domains=blocked)
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "web search failed"))
        data = result.get("data") or {}
        results = [
            {k: row[k] for k in ("title", "url", "description", "published", "site") if row.get(k)}
            for row in data.get("web") or []
        ]
        payload: dict[str, Any] = {
            "query": query, "mode": search_mode,
            "allowed_domains": allowed, "blocked_domains": blocked,
            "provider": data.get("served_by", ""),
            "results": results[: max(1, count)],
        }
        if data.get("fallbacks"):
            payload["fallbacks"] = data["fallbacks"]
        if data.get("cached"):
            payload["cached"] = True
        return payload

    async def web_fetch(self, url: str, max_chars: int = 15000) -> dict[str, Any]:
        if not re.match(r"^https?://", url):
            raise ValueError("url must start with http:// or https://")
        page = (await self.service.extract([url], char_limit=max_chars))[0]
        if page.get("error"):
            if page.get("error_category") == "policy":
                raise WebPolicyError(str(page["error"]))
            raise RuntimeError(str(page["error"]))
        text = str(page.get("content") or "")
        meta = page.get("metadata") or {}
        payload: dict[str, Any] = {
            "url": page.get("url") or url, "title": page.get("title", ""), "text": text,
            "length": len(text),
            "truncated": bool(page.get("truncated") or meta.get("truncated")),
            "provider": meta.get("served_by", ""),
        }
        if isinstance(page.get("status_code"), int):
            payload["status_code"] = page["status_code"]
        if meta.get("fallbacks"):
            payload["fallbacks"] = meta["fallbacks"]
        return payload

    @staticmethod
    def _error(message: str, *, error_category: str | None = None) -> dict[str, Any]:
        data = {"error": message}
        if error_category:
            data["error_category"] = error_category
        return {
            "data": data,
            "content": [{"type": "text", "text": message}],
            "is_error": True,
        }


WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web and return ranked results (title, url, snippet, publish date). "
                "Chinese queries are routed to a Chinese index automatically. Use web_fetch to read a result. "
                "For questions that need several searches and cross-checked sources (comparisons, prices, "
                "market or product state, 'latest' anything), call deep_research once instead of many web_search calls."
            ),
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string",
                    "description": "Search query. Operators such as \"exact phrase\" or -term work on most backends."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                "allowed_domains": {"type": "array", "items": {"type": "string"},
                    "description": "Restrict results to these hosts and their subdomains."},
                "blocked_domains": {"type": "array", "items": {"type": "string"},
                    "description": "Drop results served by these hosts and their subdomains."},
                "mode": {"type": "string", "enum": ["balanced", "strict", "long"],
                    "description": "balanced (default), strict (few on-target results) or long (wide sweep, 10+)."},
            }, "required": ["query"], "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Read a web page (or PDF / video captions) and return its main text as markdown. "
                "Long pages return head + tail with a footer naming the saved full text for read_file."
            ),
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 100000},
            }, "required": ["url"], "additionalProperties": False},
        },
    },
]
