"""Web access tools for the normal Agent: search + page fetch, no API key.

``web_search`` asks the keyed APIs in ``atlas.tools.search_api`` first (Bocha,
then Tavily, each only when a key is set), then scrapes DuckDuckGo's HTML
endpoint, with Bing as the last fallback.
Requests go through the system proxy first (env or Windows setting), then
directly: from mainland China DuckDuckGo fails the TLS handshake or answers
with a 202 bot wall unless proxied, and every "success" that is not a 200 is
treated as a failure so the next engine gets its turn.
Results are parsed with the stdlib HTML parser; the Bing result layout and the
``/ck/a?u=a1<b64>`` unwrapping are ported from ``ddgs`` (deedy5/ddgs,
``ddgs/engines/bing.py``). ``web_fetch`` downloads a page and returns readable
text (tags stripped, scripts/styles dropped). Both are plain httpx calls with
short timeouts; network failures return structured errors (exception type and
host, never an empty message) instead of raising into the agent loop.
"""

from __future__ import annotations

import asyncio
import base64
import html as html_module
import json
import logging
import os
import re
from html.parser import HTMLParser
from typing import Any, Sequence
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx

from atlas.tools import search_api
from atlas.tools.ssrf_transport import _resolved_connect_ips, create_ssrf_safe_async_client

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"
BING_URL = "https://www.bing.com/search?q={query}"


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
                href = unquote(match.group(1))
        elif href.startswith("/"):
            href = urljoin(base_url, href)
        if not href.startswith("http"):
            continue
        if re.match(r"https?://(www\.)?duckduckgo\.com/", href):
            continue  # DDG-internal redirects (ads / tracking), not results
        if any(item["url"] == href for item in results):
            continue  # title, snippet and url line of one result all link the same page
        results.append({"title": html_module.unescape(text), "url": href})
    return results


class _BingParser(HTMLParser):
    """Collect ``li.b_algo`` results: ``h2 > a`` title/href, first ``p`` as snippet."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._li_depth = 0  # >0 while inside a b_algo <li>
        self._item: dict[str, str] | None = None
        self._in_h2 = False
        self._in_title = False
        self._in_p = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "li":
            if self._li_depth:
                self._li_depth += 1
            elif "b_algo" in (attr.get("class") or "").split():
                self._li_depth = 1
                self._item = {"title": "", "url": "", "snippet": ""}
            return
        if self._item is None:
            return
        if tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2 and not self._item["url"]:
            self._item["url"] = attr.get("href") or ""
            self._in_title = True
        elif tag == "p" and not self._item["snippet"]:
            self._in_p = True

    def handle_endtag(self, tag: str) -> None:
        if self._item is None:
            return
        if tag == "li":
            self._li_depth -= 1
            if not self._li_depth:
                self.results.append(self._item)
                self._item = None
        elif tag == "h2":
            self._in_h2 = self._in_title = False
        elif tag == "a":
            self._in_title = False
        elif tag == "p":
            self._in_p = False

    def handle_data(self, data: str) -> None:
        if self._item is None:
            return
        if self._in_title:
            self._item["title"] += data
        elif self._in_p:
            self._item["snippet"] += data


def _unwrap_bing_url(raw_url: str) -> str | None:
    """Decode Bing's ``/ck/a?...&u=a1<urlsafe-b64>`` redirect to the real url."""
    values = parse_qs(urlparse(raw_url).query).get("u", [])
    if not values or len(values[0]) <= 2:
        return None
    part = values[0][2:]
    try:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None


def parse_bing_results(html: str) -> list[dict[str, str]]:
    """Parse Bing's HTML result page: title, url, snippet."""
    parser = _BingParser()
    try:
        parser.feed(html)
    except Exception:
        logger.debug("atlas.tools.web: ignored error", exc_info=True)
    results: list[dict[str, str]] = []
    for item in parser.results:
        url = item["url"]
        if re.match(r"https?://(www\.|cn\.)?bing\.com/aclick\?", url):
            continue  # ads
        if re.match(r"https?://(www\.|cn\.)?bing\.com/ck/a\?", url):
            url = _unwrap_bing_url(url) or url
        title = re.sub(r"\s+", " ", item["title"]).strip()
        if not url.startswith("http") or not title:
            continue
        result = {"title": title, "url": url}
        snippet = re.sub(r"\s+", " ", item["snippet"]).strip()
        if snippet:
            result["snippet"] = snippet
        results.append(result)
    return results


def _describe(exc: BaseException) -> str:
    """Never-empty error text: httpx connect errors often have ``str(exc) == ''``."""
    label = type(exc).__name__
    if isinstance(exc, httpx.HTTPError):
        try:
            label += f" ({exc.request.url.host})"
        except RuntimeError:
            pass  # no request attached
    text = str(exc).strip()
    return f"{label}: {text}" if text else label


class _NotOKError(RuntimeError):
    """A 2xx/3xx answer that carries no page, e.g. DuckDuckGo's 202 bot wall."""


def system_proxy() -> str | None:
    """The user's outbound proxy: ``HTTPS_PROXY``/``ALL_PROXY``, else the Windows one.

    ``urllib.request.getproxies()`` ignores the registry as soon as *any* proxy
    variable exists (a lone ``NO_PROXY`` is enough), which left web tools dialing
    blocked sites directly while Clash/v2rayN sat configured as the system proxy.
    """
    for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key, "").strip()
        if value:
            return value if "://" in value else f"http://{value}"
    if os.name != "nt":
        return None
    import urllib.request

    try:
        registry = urllib.request.getproxies_registry()  # empty unless ProxyEnable=1
    except OSError:
        return None
    value = (registry.get("https") or registry.get("http") or "").strip()
    return value or None


async def _guard_request(request: httpx.Request) -> None:
    host = request.url.host
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    await asyncio.to_thread(_resolved_connect_ips, host, port, False)


def _host_of(url: str) -> str:
    """Lowercased hostname of a URL, empty when unparseable."""
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://([^/?#]+)", url)
    authority = match.group(1) if match else ""
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    host = authority.split(":", 1)[0].strip().casefold()
    return host[4:] if host.startswith("www.") else host


def _domain_matches(host: str, allowed: Sequence[str]) -> bool:
    for entry in allowed:
        pattern = str(entry or "").strip().casefold()
        if pattern.startswith("*."):
            pattern = pattern[2:]
        if not pattern:
            continue
        if host == pattern or host.endswith("." + pattern):
            return True
    return False


class WebRuntime:
    """Stateless web tools exposed to the Agent."""

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        try:
            if name == "web_search":
                data = await self.web_search(
                    str(args.get("query", "")), int(args.get("max_results", 5)),
                    allowed_domains=args.get("allowed_domains"),
                    blocked_domains=args.get("blocked_domains"),
                    mode=str(args.get("mode") or "balanced"),
                )
            elif name == "web_fetch":
                data = await self.web_fetch(
                    str(args.get("url", "")), int(args.get("max_chars", 8000)),
                )
            else:
                return self._error(f"Unknown web tool: {name}")
        except Exception as exc:
            return self._error(f"{name} failed: {_describe(exc)}")
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

        def _list(value: Any) -> list[str]:
            return [str(item).strip() for item in (value or [])
                    if isinstance(item, str) and str(item).strip()]

        allowed = _list(allowed_domains)
        blocked = _list(blocked_domains)
        search_mode = str(mode or "balanced").strip().casefold()
        if search_mode not in {"balanced", "strict", "long"}:
            search_mode = "balanced"
        api_query = query.strip()
        if allowed:
            query = f"{query} " + " ".join(f"site:{item}" for item in allowed)
        else:
            for item in blocked:
                query = f"{query} -site:{item}"
        results, engine, api_errors = await self._search_engines(
            query.strip(), api_query=api_query, count=max(1, max_results),
            allowed=allowed, blocked=blocked,
        )
        if allowed or blocked:
            filtered: list[dict[str, str]] = []
            for item in results:
                host = _host_of(str(item.get("url") or ""))
                if allowed and not _domain_matches(host, allowed):
                    continue
                if blocked and _domain_matches(host, blocked):
                    continue
                filtered.append(item)
            results = filtered
        data: dict[str, Any] = {
            "query": query, "mode": search_mode, "engine": engine,
            "allowed_domains": allowed, "blocked_domains": blocked,
            "results": results[: max(1, max_results)],
        }
        if engine == "bing":
            data["note"] = ("Keyed search APIs and DuckDuckGo did not answer; these are Bing "
                            "fallback results, which from mainland networks are often unrelated "
                            "to the query. Check relevance before relying on them.")
        if api_errors:
            data["engine_errors"] = api_errors
        return data

    async def _search_engines(self, query: str, *, api_query: str = "", count: int = 5,
                              allowed: Sequence[str] = (),
                              blocked: Sequence[str] = (),
                              ) -> tuple[list[dict[str, str]], str, list[str]]:
        """Bocha, Tavily (each only with a key), DuckDuckGo, then Bing.

        The first engine with results wins. Bing is the last resort: reachable from
        everywhere, but from mainland IPs it is redirected to cn.bing.com, which
        serves scrapers unrelated results.

        An engine that errors or yields nothing falls through; keyed-API errors
        (bad key, quota) are kept in ``engine_errors`` so the user can see a key
        needs attention even when a later engine answered. When every engine
        *errored* the errors are raised together; a reachable engine that found
        nothing returns an empty list.
        """
        proxy = system_proxy()
        api_query = api_query or query
        engines: list[tuple[str, Any]] = []
        for provider in search_api.PROVIDERS:
            key, _source = search_api.api_key(provider)
            if not key:
                continue
            if provider.id == "bocha":
                engines.append(("bocha", lambda key=key: search_api.bocha_search(
                    key, api_query, count, proxy=proxy)))
            elif provider.id == "tavily":
                engines.append(("tavily", lambda key=key: search_api.tavily_search(
                    key, api_query, count, proxy=proxy, allowed=allowed, blocked=blocked)))
        for engine, template, parse in (
            ("duckduckgo", SEARCH_URL, parse_ddg_results),
            ("bing", BING_URL, parse_bing_results),
        ):
            async def scrape(template: str = template, parse: Any = parse) -> list[dict[str, str]]:
                return parse(await self._get(template.format(query=quote_plus(query))))
            engines.append((engine, scrape))

        errors: list[str] = []
        api_errors: list[str] = []
        for engine, run in engines:
            try:
                results = await run()
            except Exception as exc:  # noqa: BLE001 — any engine failure falls through to the next
                errors.append(f"{engine}: {_describe(exc)}")
                if engine in search_api.PROVIDERS_BY_ID:
                    api_errors.append(errors[-1])
                continue
            if results:
                return results, engine, api_errors
        if len(errors) == len(engines):
            raise RuntimeError("all search engines failed; " + "; ".join(errors))
        return [], "", api_errors

    async def web_fetch(self, url: str, max_chars: int = 8000) -> dict[str, Any]:
        if not re.match(r"^https?://", url):
            raise ValueError("url must start with http:// or https://")
        response = await self._get(url)
        text = extract_text(response)
        return {"url": url, "text": text[: max(200, max_chars)], "length": len(text)}

    async def _get(self, url: str) -> str:
        """GET through the system proxy first (when one is set), then directly.

        Each route retries one transport error or non-200 answer (proxy nodes and
        TUN drop TLS handshakes intermittently; DuckDuckGo's 202 wall is often
        transient). SSRF blocks and 4xx/5xx statuses are final. When every route
        fails, the last error is raised.
        """
        proxy = system_proxy()
        last: Exception | None = None
        for route in ((proxy, None) if proxy else (None,)):
            for _attempt in (1, 2):
                try:
                    return await self._get_once(url, route)
                except (httpx.TransportError, _NotOKError) as exc:
                    last = exc
        assert last is not None
        raise last

    async def _get_once(self, url: str, proxy: str | None) -> str:
        options: dict[str, Any] = {
            "follow_redirects": True, "timeout": 15.0, "trust_env": False,
            "headers": {"User-Agent": USER_AGENT},
        }
        if proxy:
            # The proxy dials the target, so the SSRF check runs before every hop
            # (redirects included): the hostname must resolve to a public address.
            client = httpx.AsyncClient(proxy=proxy, event_hooks={"request": [_guard_request]},
                                       **options)
        else:
            # Every hop, including redirects, passes the connect-time DNS guard in
            # atlas.tools.ssrf_transport: a hostname answered with a private or
            # loopback address is blocked before a socket opens.
            client = create_ssrf_safe_async_client(**options)
        async with client:
            response = await client.get(url)
            response.raise_for_status()
            if response.status_code != 200:
                # e.g. DuckDuckGo's 202 bot wall: "success" with no results.
                raise _NotOKError(f"HTTP {response.status_code} from {response.url.host}")
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
            "description": ("Search the public web (Bocha / Tavily when keyed, else DuckDuckGo, "
                            "Bing fallback) and return result links with snippets. The "
                            "`engine` field says which answered."),
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                "allowed_domains": {"type": "array", "items": {"type": "string"},
                    "description": "Restrict results to these hosts and their subdomains."},
                "blocked_domains": {"type": "array", "items": {"type": "string"},
                    "description": "Drop results served by these hosts and their subdomains."},
                "mode": {"type": "string", "enum": ["balanced", "strict", "long"]},
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
