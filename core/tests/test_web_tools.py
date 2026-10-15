"""Web tool coverage: parsers (offline) + agent-facing calls with a fake fetcher."""

from __future__ import annotations

import pytest

from atlas.tools import search_api
from atlas.tools.web import (
    WEB_TOOLS,
    WebRuntime,
    extract_text,
    parse_ddg_results,
)


@pytest.fixture(autouse=True)
def _no_search_api_keys(monkeypatch) -> None:
    # A real Bocha/Tavily key in this machine's credential store must not turn
    # these scraper tests into paid live calls.
    monkeypatch.setattr(search_api, "api_key", lambda provider: (None, None))

DDG_FIXTURE = """
<html><head><style>.x{color:red}</style></head><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdbos.dev%2Fdocs">
    DBOS Transact — durable execution
  </a>
  <a class="result__snippet" href="/y.js">Lightweight durable workflow in Python.</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.com/guide">A plain external link</a>
</div>
</body></html>
"""


def test_extract_text_strips_scripts_and_styles() -> None:
    text = extract_text(
        "<html><head><style>p{}</style><script>evil()</script></head>"
        "<body><h1>Hello   Atlas</h1><p>  body\ntext  </p></body></html>",
    )
    assert text == "Hello Atlas body text"


def test_parse_ddg_results_resolves_uddg_and_absolute_links() -> None:
    results = parse_ddg_results(DDG_FIXTURE)
    urls = [item["url"] for item in results]
    assert urls[0] == "https://dbos.dev/docs"
    assert "durable execution" in results[0]["title"]
    assert urls[1] == "https://example.com/guide"


def test_web_tools_surface() -> None:
    assert {item["function"]["name"] for item in WEB_TOOLS} == {"web_search", "web_fetch"}


async def test_web_search_and_fetch_with_fake_fetcher() -> None:
    runtime = WebRuntime()
    fetched: list[str] = []

    async def fake_get(url: str) -> str:
        fetched.append(url)
        if "duckduckgo" in url:
            return DDG_FIXTURE
        return "<html><body><p>page body content</p></body></html>"

    runtime._get = fake_get  # type: ignore[method-assign]

    search = await runtime.call_tool("web_search", {"query": "dbos sqlite"})
    assert search["is_error"] is False
    assert search["data"]["results"][0]["url"] == "https://dbos.dev/docs"

    fetch = await runtime.call_tool("web_fetch", {"url": "https://example.com/page"})
    assert "page body content" in fetch["data"]["text"]

    empty = await runtime.call_tool("web_search", {"query": "   "})
    assert empty["is_error"] is True

    bad = await runtime.call_tool("web_fetch", {"url": "ftp://x"})
    assert bad["is_error"] is True

    unknown = await runtime.call_tool("web_nothing", {})
    assert unknown["is_error"] is True
    assert "duckduckgo" in fetched[0]
    assert search["data"]["engine"] == "duckduckgo"


BING_FIXTURE = """
<html><body><ol id="b_results">
<li class="b_ad"><h2><a href="https://www.bing.com/aclick?ld=x">Ad</a></h2></li>
<li class="b_algo"><div class="b_title"><h2>
  <a href="https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly9naXRodWIuY29tL3N0dWRpby1kb3RzLWFpL2RvdHMubGxtMQ&ntb=1">
  studio-dots-ai/<strong>dots.llm1</strong></a></h2></div>
  <div class="b_caption"><p>A large-scale <strong>MoE</strong> model.</p></div>
  <ul><li>nested list item</li></ul>
</li>
<li class="b_algo"><h2><a href="https://example.com/plain">Plain result</a></h2></li>
</ol></body></html>
"""


def test_parse_bing_results_unwraps_ck_links_and_skips_ads() -> None:
    from atlas.tools.web import parse_bing_results

    results = parse_bing_results(BING_FIXTURE)
    assert [item["url"] for item in results] == [
        "https://github.com/studio-dots-ai/dots.llm1",
        "https://example.com/plain",
    ]
    assert results[0]["title"] == "studio-dots-ai/dots.llm1"
    assert results[0]["snippet"] == "A large-scale MoE model."


async def test_search_falls_back_to_bing_and_reports_every_engine_failure() -> None:
    import httpx

    runtime = WebRuntime()

    async def ddg_walled(url: str) -> str:
        if "duckduckgo" in url:
            raise RuntimeError("HTTP 202 from html.duckduckgo.com")
        return BING_FIXTURE

    runtime._get = ddg_walled  # type: ignore[method-assign]
    ok = await runtime.call_tool("web_search", {"query": "dots llm"})
    assert ok["data"]["engine"] == "bing"
    assert ok["data"]["results"][0]["url"].startswith("https://github.com/")

    async def all_down(url: str) -> str:
        raise httpx.ConnectError("", request=httpx.Request("GET", url))

    runtime._get = all_down  # type: ignore[method-assign]
    bad = await runtime.call_tool("web_search", {"query": "dots llm"})
    assert bad["is_error"] is True
    error = bad["data"]["error"]
    assert "bing: ConnectError (www.bing.com)" in error
    assert "duckduckgo: ConnectError (html.duckduckgo.com)" in error


async def test_get_tries_system_proxy_then_direct(monkeypatch) -> None:
    import httpx

    from atlas.tools import web

    monkeypatch.setattr(web, "system_proxy", lambda: "http://127.0.0.1:7897")
    routes: list[str | None] = []

    async def flaky_proxy(self, url: str, proxy: str | None) -> str:
        routes.append(proxy)
        if proxy:
            raise httpx.ConnectError("", request=httpx.Request("GET", url))
        return "direct body"

    monkeypatch.setattr(web.WebRuntime, "_get_once", flaky_proxy)
    assert await WebRuntime()._get("https://example.com") == "direct body"
    assert routes == ["http://127.0.0.1:7897", "http://127.0.0.1:7897", None]


def test_system_proxy_prefers_env(monkeypatch) -> None:
    from atlas.tools import web

    for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "127.0.0.1:8080")
    assert web.system_proxy() == "http://127.0.0.1:8080"


async def test_network_failure_returns_structured_error() -> None:
    runtime = WebRuntime()

    async def failing_get(url: str) -> str:
        raise RuntimeError("network down")

    runtime._get = failing_get  # type: ignore[method-assign]
    result = await runtime.call_tool("web_search", {"query": "q"})
    assert result["is_error"] is True
    assert "network down" in result["data"]["error"]
