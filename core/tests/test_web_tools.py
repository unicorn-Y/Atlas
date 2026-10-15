"""Web tools: offline parsers, routing and provider-chain failover (no network)."""

from __future__ import annotations

from typing import Any

from atlas.tools.web import WEB_TOOLS, WebRuntime
from atlas.websearch import WebSearchService, WebSettings, cache
from atlas.websearch.common import search_fail, search_ok
from atlas.websearch.keyless import parse_exa_search_text, parse_mcp_body
from atlas.websearch.providers import PROVIDERS
from atlas.websearch.providers.base import WebProvider
from atlas.websearch.router import is_chinese_query


def test_mcp_body_and_exa_blocks_parse() -> None:
    sse = 'event: message\ndata: {"result":{"content":[{"type":"text","text":"Title: A\\nURL: https://a.dev\\nPublished: 2026-01-02\\nHighlights:\\nfirst line\\n---\\nTitle: B\\nURL: https://b.dev\\nHighlights:\\nsecond"}]}}\n'
    rows = parse_exa_search_text(parse_mcp_body(sse), 5)
    assert [r["url"] for r in rows] == ["https://a.dev", "https://b.dev"]
    assert rows[0]["description"] == "first line" and rows[0]["published"] == "2026-01-02"


def test_chinese_routing() -> None:
    assert is_chinese_query("知乎上怎么评价 Hermes Agent")
    assert is_chinese_query("python asyncio", ["zhihu.com"])
    assert not is_chinese_query("OpenAI Codex CLI web search")


class _Fake(WebProvider):
    needs_key = False

    def __init__(self, name: str, result: dict[str, Any]) -> None:
        self.name, self.display_name, self.result, self.calls = name, name, result, 0

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        self.calls += 1
        return self.result


async def test_chain_fails_over_and_reports(monkeypatch) -> None:
    dead = _Fake("dead", search_fail("HTTP 429: quota exceeded"))
    empty = _Fake("empty", search_ok([]))
    good = _Fake("good", search_ok([
        {"title": "Doc", "url": "https://docs.example.com/x", "description": "d", "position": 1},
        {"title": "Dup", "url": "https://docs.example.com/x/", "description": "d", "position": 2},
        {"title": "Ad", "url": "https://spam.example.net/", "description": "d", "position": 3},
    ]))
    for fake in (dead, empty, good):
        monkeypatch.setitem(PROVIDERS, fake.name, fake)
    cache.search_memo.clear()
    service = WebSearchService(WebSettings(search_order=("dead", "empty", "good"), cache_enabled=True))
    runtime = WebRuntime(service)

    result = await runtime.call_tool("web_search", {"query": "q", "blocked_domains": ["spam.example.net"]})
    data = result["data"]
    assert result["is_error"] is False and data["provider"] == "good"
    assert [r["url"] for r in data["results"]] == ["https://docs.example.com/x"]  # deduped + filtered
    assert len(data["fallbacks"]) == 2

    again = await runtime.call_tool("web_search", {"query": "Q ", "blocked_domains": ["spam.example.net"]})
    assert again["data"]["cached"] is True and good.calls == 1  # memo keyed on the normalized query

    monkeypatch.setitem(PROVIDERS, "good", _Fake("good", search_fail("HTTP 503")))
    cache.search_memo.clear()
    failed = await runtime.call_tool("web_search", {"query": "other"})
    assert failed["is_error"] is True and "every web search provider failed" in failed["data"]["error"]


async def test_tool_surface_and_argument_errors() -> None:
    assert {item["function"]["name"] for item in WEB_TOOLS} == {"web_search", "web_fetch"}
    runtime = WebRuntime(WebSearchService(WebSettings(search_order=(), keyless=False)))
    assert (await runtime.call_tool("web_search", {"query": "   "}))["is_error"] is True
    assert (await runtime.call_tool("web_fetch", {"url": "ftp://x"}))["is_error"] is True
    assert (await runtime.call_tool("web_nothing", {}))["is_error"] is True
