"""Web tool coverage: parsers (offline) + agent-facing calls with a fake fetcher."""

from __future__ import annotations

from atlas.tools.web import (
    WEB_TOOLS,
    WebRuntime,
    extract_text,
    parse_ddg_results,
)

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


async def test_network_failure_returns_structured_error() -> None:
    runtime = WebRuntime()

    async def failing_get(url: str) -> str:
        raise RuntimeError("network down")

    runtime._get = failing_get  # type: ignore[method-assign]
    result = await runtime.call_tool("web_search", {"query": "q"})
    assert result["is_error"] is True
    assert "network down" in result["data"]["error"]
