"""Web tools: offline parsers, routing and provider-chain failover (no network)."""

from __future__ import annotations

from typing import Any

import pytest

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_web_fetch_reports_final_status_and_effective_truncation(monkeypatch):
    import socket
    import httpx

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ])
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(
            202, text="<title>Accepted</title><article>" + ("body text " * 100) + "</article>",
        )

    def client_factory(**options):
        options.pop("allow_local", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **options)

    monkeypatch.setattr("atlas.tools.web_extract.create_ssrf_safe_async_client", client_factory)
    service = WebSearchService(WebSettings(
        extract_order=("local",), cache_enabled=False, extract_char_limit=200,
    ))
    result = await WebRuntime(service).call_tool(
        "web_fetch", {"url": "https://example.com/start", "max_chars": 200},
    )

    assert result["is_error"] is False
    assert result["data"]["url"] == "https://example.com/final"
    assert result["data"]["status_code"] == 202
    assert result["data"]["truncated"] is True
    assert requests == ["https://example.com/start", "https://example.com/final"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cross_origin_redirect_policy_error_stops_provider_fallback(monkeypatch):
    import socket
    import httpx

    from atlas.websearch.providers.base import WebProvider

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ])
    requested = []

    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://other.example/landing"})

    def client_factory(**options):
        options.pop("allow_local", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **options)

    monkeypatch.setattr("atlas.tools.web_extract.create_ssrf_safe_async_client", client_factory)

    class Fallback(WebProvider):
        name, display_name = "fixture-fallback", "fixture fallback"
        needs_key = False
        can_extract = True

        def __init__(self):
            self.calls = 0

        async def extract(self, urls, _settings):
            self.calls += 1
            return [{"url": url, "title": "fallback", "content": "fallback body"}
                    for url in urls]

    fallback = Fallback()
    monkeypatch.setitem(PROVIDERS, fallback.name, fallback)
    service = WebSearchService(WebSettings(
        extract_order=("local", fallback.name), cache_enabled=False,
    ))
    result = await WebRuntime(service).call_tool(
        "web_fetch", {"url": "https://example.com/start"},
    )

    assert result["is_error"] is True, result
    assert result["data"]["error_category"] == "policy"
    assert "跨源网页跳转已拒绝" in result["data"]["error"]
    assert fallback.calls == 0
    assert requested == ["https://example.com/start"]
