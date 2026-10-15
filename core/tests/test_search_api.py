"""Keyed search APIs (Bocha, Tavily): parsing, error text, engine order, key settings."""

from __future__ import annotations

import json

import httpx
import pytest

from atlas.tools import search_api, web


class _MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


@pytest.fixture
def store(monkeypatch) -> _MemoryStore:
    memory = _MemoryStore()
    monkeypatch.setattr(search_api, "_credential_store", lambda: memory)
    for provider in search_api.PROVIDERS:
        monkeypatch.delenv(provider.env_var, raising=False)
    return memory


def _mock_http(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(*args, **kwargs):
        kwargs.pop("proxy", None)
        return real(*args, transport=httpx.MockTransport(wrapped), **kwargs)

    monkeypatch.setattr(search_api.httpx, "AsyncClient", factory)
    return seen


BOCHA_OK = {"code": 200, "msg": None, "data": {"webPages": {"value": [
    {"name": "dots.llm1", "url": "https://github.com/rednote-hilab/dots.llm1",
     "snippet": "short", "summary": "小红书开源的 MoE 大模型", "datePublished": "2025-06-06"},
    {"name": "", "url": "https://empty-title.example"},
]}}}


async def test_bocha_parses_summary_and_sends_bearer_key(monkeypatch) -> None:
    seen = _mock_http(monkeypatch, lambda request: httpx.Response(200, json=BOCHA_OK))
    results = await search_api.bocha_search("sk-bocha", "dots llm", 5, proxy=None)
    assert results == [{"title": "dots.llm1", "url": "https://github.com/rednote-hilab/dots.llm1",
                        "snippet": "小红书开源的 MoE 大模型", "published": "2025-06-06"}]
    assert seen[0].headers["Authorization"] == "Bearer sk-bocha"
    assert json.loads(seen[0].content)["query"] == "dots llm"


async def test_bad_key_error_is_readable(monkeypatch) -> None:
    _mock_http(monkeypatch, lambda request: httpx.Response(401, json={"code": 401, "msg": "Invalid API KEY"}))
    with pytest.raises(search_api.SearchAPIError, match="HTTP 401: Invalid API KEY"):
        await search_api.bocha_search("bad", "q", 5, proxy=None)


async def test_tavily_passes_domains_and_parses_content(monkeypatch) -> None:
    body = {"results": [{"title": "HTTPX", "url": "https://www.python-httpx.org/", "content": "A client"}]}
    seen = _mock_http(monkeypatch, lambda request: httpx.Response(200, json=body))
    results = await search_api.tavily_search("tvly-x", "httpx", 3, proxy=None,
                                             allowed=["python-httpx.org"])
    assert results == [{"title": "HTTPX", "url": "https://www.python-httpx.org/", "snippet": "A client"}]
    assert json.loads(seen[0].content)["include_domains"] == ["python-httpx.org"]


async def test_engine_order_bocha_then_tavily_then_scrapers(monkeypatch, store) -> None:
    store.set("atlas.search.bocha_api_key", "sk-bocha")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-env")
    monkeypatch.setattr(web, "system_proxy", lambda: None)
    calls: list[str] = []

    async def bocha_down(key, query, count, *, proxy):
        calls.append("bocha")
        raise search_api.SearchAPIError("HTTP 403: 余额不足")

    async def tavily_ok(key, query, count, *, proxy, allowed=(), blocked=()):
        calls.append(f"tavily:{key}")
        return [{"title": "t", "url": "https://t.example"}]

    monkeypatch.setattr(search_api, "bocha_search", bocha_down)
    monkeypatch.setattr(search_api, "tavily_search", tavily_ok)
    runtime = web.WebRuntime()

    async def no_scrape(url: str) -> str:
        raise AssertionError("scrapers must not run when an API answered")

    runtime._get = no_scrape  # type: ignore[method-assign]
    result = await runtime.call_tool("web_search", {"query": "q"})
    assert calls == ["bocha", "tavily:tvly-env"]
    assert result["data"]["engine"] == "tavily"
    assert result["data"]["engine_errors"] == ["bocha: SearchAPIError: HTTP 403: 余额不足"]


async def test_without_keys_scrapers_answer(monkeypatch, store) -> None:
    runtime = web.WebRuntime()

    async def ddg(url: str) -> str:
        return '<a href="https://example.com/x">Example result</a>'

    runtime._get = ddg  # type: ignore[method-assign]
    result = await runtime.call_tool("web_search", {"query": "q"})
    assert result["data"]["engine"] == "duckduckgo"
    assert "engine_errors" not in result["data"]


def test_settings_store_key_and_never_return_it(store) -> None:
    from fastapi import HTTPException

    from atlas.api import search_settings_router as router

    before = router.get_search_settings()
    assert [p["configured"] for p in before["providers"]] == [False, False]
    assert before["order"] == ["bocha", "tavily", "duckduckgo", "bing"]

    after = router.update_search_settings(router.SearchKeyUpdate(provider="bocha", api_key=" sk-1234567890abcd "))
    assert store.values["atlas.search.bocha_api_key"] == "sk-1234567890abcd"
    bocha = after["providers"][0]
    assert bocha["configured"] is True and bocha["source"] == "keyring" and bocha["hint"] == "…abcd"
    assert "sk-1234567890abcd" not in json.dumps(after)

    cleared = router.update_search_settings(router.SearchKeyUpdate(provider="bocha", clear=True))
    assert cleared["providers"][0]["configured"] is False
    with pytest.raises(HTTPException):
        router.update_search_settings(router.SearchKeyUpdate(provider="nope", api_key="x"))
    with pytest.raises(HTTPException):
        router.update_search_settings(router.SearchKeyUpdate(provider="tavily", api_key="has space"))
