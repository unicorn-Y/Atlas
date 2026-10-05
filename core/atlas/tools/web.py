"""Web access tools for the normal Agent: search + page fetch, no API key.

``web_search`` queries DuckDuckGo's HTML endpoint and parses result links,
titles, and snippets with the stdlib HTML parser. ``web_fetch`` downloads a
page and returns readable text (tags stripped, scripts/styles dropped).
Both are plain httpx calls with short timeouts; network failures return
structured errors instead of raising into the agent loop.
"""

from __future__ import annotations

import html as html_module
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx

import logging

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"


class _TextExtractor(HTMLParser):
    """Collect readable text, skipping script/style, recording links."""

    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []
        self.links: list[tuple[str, str]] = []  # (href, text)
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "a" and self._href is not None:
            text = "".join(self._link_text).strip()
            if text:
                self.links.append((self._href or "", text))
            self._href = None
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self.chunks.append(stripped)
            if self._href is not None:
                self._link_text.append(data)


def extract_text(html: str) -> str:
    """HTML -> readable text, whitespace-collapsed."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        logger.debug("atlas.tools.web: ignored error", exc_info=True)
    return re.sub(r"\s+", " ", " ".join(parser.chunks)).strip()


def parse_ddg_results(html: str, base_url: str = "https://duckduckgo.com") -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML result links: title, url, snippet."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        logger.debug("atlas.tools.web: ignored error", exc_info=True)
    results: list[dict[str, str]] = []
    for href, text in parser.links:
        if "uddg=" in href:
            match = re.search(r"uddg=([^&]+)", href)
            if match:
                from urllib.parse import unquote

                href = unquote(match.group(1))
        elif href.startswith("/"):
            href = urljoin(base_url, href)
        if not href.startswith("http"):
            continue
        if re.match(r"https?://(www\.)?duckduckgo\.com/", href):
            continue  # DDG-internal redirects (ads / tracking), not results
        results.append({"title": html_module.unescape(text), "url": href})
    return results


class WebRuntime:
    """Stateless web tools exposed to the Agent."""

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        try:
            if name == "web_search":
                data = await self.web_search(
                    str(args.get("query", "")), int(args.get("max_results", 5)),
                )
            elif name == "web_fetch":
                data = await self.web_fetch(
                    str(args.get("url", "")), int(args.get("max_chars", 8000)),
                )
            else:
                return self._error(f"Unknown web tool: {name}")
        except Exception as exc:
            return self._error(f"{name} failed: {exc}")
        return {
            "data": data,
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "is_error": False,
        }

    async def web_search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query is required")
        response = await self._get(SEARCH_URL.format(query=quote_plus(query.strip())))
        results = parse_ddg_results(response)[: max(1, max_results)]
        return {"query": query, "results": results}

    async def web_fetch(self, url: str, max_chars: int = 8000) -> dict[str, Any]:
        if not re.match(r"^https?://", url):
            raise ValueError("url must start with http:// or https://")
        response = await self._get(url)
        text = extract_text(response)
        return {"url": url, "text": text[: max(200, max_chars)], "length": len(text)}

    async def _get(self, url: str) -> str:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15.0, headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {
            "data": {"error": message},
            "content": [{"type": "text", "text": message}],
            "is_error": True,
        }


WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web (DuckDuckGo) and return result links.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            }, "required": ["query"], "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Download a web page and return its readable text.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 50000},
            }, "required": ["url"], "additionalProperties": False},
        },
    },
]
