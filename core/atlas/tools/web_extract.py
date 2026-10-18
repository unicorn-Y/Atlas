"""Bounded web page and caption extraction with redirect-time SSRF checks."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from atlas.tools.ssrf_transport import create_ssrf_safe_async_client, is_public_address

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_TEXT_LENGTH = 60_000
# trafilatura and HTMLParser are pure Python and CPU-bound: a 10 MB page holds the
# interpreter for seconds. Running that inline froze the whole asyncio event loop, so
# the desktop health probe timed out and Electron taskkilled a perfectly healthy
# backend. Both stages now run in a worker thread and each one is bounded.
EXTRACT_TIMEOUT_SECONDS = 15.0
# Above this size trafilatura is measured to take tens of seconds (24 s at 9.9 MB), so we
# go straight to the fast path rather than waste the budget on an attempt we know fails.
CHEAP_PATH_BYTES = 2 * 1024 * 1024


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer", "header", "aside", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "header", "aside", "noscript", "svg"}:
            self.skip = max(0, self.skip - 1)
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "br", "article", "section"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _extract_main_text(html: str) -> str:
    """CPU-bound: caller must run this in a thread, never on the event loop."""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
    except ImportError:
        text = ""
    # trafilatura finds nothing on short or unusual pages; fall back to plain text extraction.
    if not text.strip():
        parser = _TextParser()
        parser.feed(html)
        text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text


def _cheap_text(html: str) -> str:
    """Regex tag stripping: C-level, ~150x faster than trafilatura on huge pages."""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


async def _extract_with_fallback(html: str) -> tuple[str, str]:
    """Return (text, how). Degradation must be visible, never a silent empty string.

    trafilatura is accurate but slow — 24 s on a 9.9 MB page. Dropping straight to ""
    when it overruns would mean a research run silently loses the page it did fetch,
    so instead we fall back to regex stripping (0.15 s, and it keeps more text).
    Every CPU-bound stage runs in a worker thread: the whole point is that this
    coroutine must never pin the event loop.
    """
    async def cheap() -> str:
        return await asyncio.to_thread(_cheap_text, html)

    if len(html) > CHEAP_PATH_BYTES:
        # Known-slow input: skip the doomed attempt instead of burning the whole budget.
        return await cheap(), "cheap_large_page"
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_extract_main_text, html), timeout=EXTRACT_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, TimeoutError):
        return await cheap(), "cheap_timeout"
    if text.strip():
        return text, "full"
    return await cheap(), "cheap_empty"


def _validate_url(url: str, allow_local: bool) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持 http 或 https 网页地址。")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("网址不能包含登录凭据。")
    host = parsed.hostname.rstrip(".").casefold()
    local_exception = allow_local and host in {"localhost", "127.0.0.1"}
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            records = socket.getaddrinfo(
                host, parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValueError("无法解析这个网址。") from exc
        addresses = [ipaddress.ip_address(record[4][0]) for record in records]
    if not local_exception and any(not is_public_address(address) for address in addresses):
        raise ValueError("出于安全考虑，不能读取内网或本机地址。")
    return url


async def _video_captions(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    if hostname == "youtube.com" or hostname.endswith(".youtube.com") or hostname == "youtu.be":
        video_id = parsed.path.rsplit("/", 1)[-1] if parsed.hostname == "youtu.be" else dict(
            item.split("=", 1) for item in parsed.query.split("&") if "=" in item
        ).get("v", "")
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            transcript = await asyncio.to_thread(
                YouTubeTranscriptApi().fetch, video_id,
            )
            return "\n".join(str(item.text) for item in transcript), ""
        except Exception:
            return "", "这个视频没有可读取的字幕。"
    return "", "这个视频没有可读取的字幕。"


async def _bilibili_captions(
    url: str, *, client_factory=None,
) -> tuple[str, str]:
    try:
        factory = client_factory or create_ssrf_safe_async_client
        async with factory(
            timeout=httpx.Timeout(20.0), follow_redirects=False,
        ) as client:
            async def fetch_bounded(target: str) -> tuple[str, bytes]:
                current = target
                response = None
                for _ in range(6):
                    await asyncio.wait_for(
                        asyncio.to_thread(_validate_url, current, False), timeout=3.0,
                    )
                    response = await client.get(
                        current, headers={"User-Agent": "Mozilla/5.0 Atlas/1.0"},
                    )
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    location = response.headers.get("location")
                    if not location:
                        break
                    current = urljoin(current, location)
                else:
                    raise ValueError("网页跳转次数过多。")
                if response is None:
                    raise ValueError("网页没有返回内容。")
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise ValueError("视频字幕内容超过 10 MB。")
                return current, bytes(data)

            _page_url, page = await fetch_bounded(url)
            html = page.decode("utf-8", errors="replace")
            marker = re.search(r"window\.__INITIAL_STATE__\s*=", html)
            state: dict[str, object] = {}
            if marker:
                try:
                    parsed, _end = json.JSONDecoder().raw_decode(html[marker.end():].lstrip())
                    if isinstance(parsed, dict):
                        state = parsed
                except json.JSONDecodeError:
                    pass
            video = state.get("videoData")
            video = video if isinstance(video, dict) else {}
            subtitle = video.get("subtitle")
            subtitle = subtitle if isinstance(subtitle, dict) else {}
            entries = subtitle.get("list")
            entries = entries if isinstance(entries, list) else []
            if not entries and video.get("cid") and video.get("bvid"):
                query = f"bvid={video['bvid']}&cid={int(video['cid'])}"
                _api_url, payload = await fetch_bounded(
                    f"https://api.bilibili.com/x/player/v2?{query}",
                )
                api = json.loads(payload.decode("utf-8", errors="replace"))
                api_data = api.get("data") if isinstance(api, dict) else {}
                api_subtitle = api_data.get("subtitle") if isinstance(api_data, dict) else {}
                entries = api_subtitle.get("subtitles", []) if isinstance(api_subtitle, dict) else []
            if not entries:
                return "", "这个视频没有可读取的字幕。"
            entry = next((item for item in entries if isinstance(item, dict)
                          and str(item.get("lan", "")).casefold().startswith("zh")), entries[0])
            if not isinstance(entry, dict) or not entry.get("subtitle_url"):
                return "", "这个视频没有可读取的字幕。"
            caption_url = urljoin("https:", str(entry["subtitle_url"]))
            _caption_url, payload = await fetch_bounded(caption_url)
            caption = json.loads(payload.decode("utf-8", errors="replace"))
            body = caption.get("body", []) if isinstance(caption, dict) else []
            text = "\n".join(
                str(item.get("content", "")) for item in body if isinstance(item, dict)
            )
            return (text, "") if text else ("", "这个视频没有可读取的字幕。")
    except asyncio.CancelledError:
        raise
    except Exception:
        return "", "这个视频没有可读取的字幕。"


async def extract_web(url: str, *, allow_local: bool = False,
                      client_factory=None) -> dict[str, object]:
    checked = await asyncio.wait_for(
        asyncio.to_thread(_validate_url, url, allow_local), timeout=3.0,
    )
    host = (urlparse(checked).hostname or "").casefold()
    is_bilibili = host == "bilibili.com" or host.endswith(".bilibili.com")
    if (host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be"
            or is_bilibili):
        if is_bilibili:
            text, note = await asyncio.wait_for(
                _bilibili_captions(checked, client_factory=client_factory), timeout=20.0,
            )
        else:
            text, note = await _video_captions(checked)
        if note:
            text = note
        clipped = text[:MAX_TEXT_LENGTH]
        return {"url": checked, "title": "视频字幕", "kind": "video", "text": clipped,
                "length": len(clipped), "truncated": len(text) > MAX_TEXT_LENGTH}

    async def fetch_page() -> dict[str, object]:
        timeout = httpx.Timeout(20.0)
        factory = client_factory or create_ssrf_safe_async_client
        client_options = {"timeout": timeout, "follow_redirects": False}
        if client_factory is None:
            client_options["allow_local"] = allow_local
        async with factory(**client_options) as client:
            current = checked
            response = None
            for _ in range(6):
                await asyncio.wait_for(
                    asyncio.to_thread(_validate_url, current, allow_local), timeout=3.0,
                )
                # Streamed: client.get() would buffer the whole body before the size cap applies.
                response = await client.send(
                    client.build_request("GET", current, headers={"User-Agent": "Atlas/1.0"}), stream=True,
                )
                location = response.headers.get("location")
                if response.status_code not in {301, 302, 303, 307, 308} or not location:
                    break
                await response.aclose()
                current = urljoin(current, location)
            else:
                raise ValueError("网页跳转次数过多。")
            if response is None:
                raise ValueError("网页没有返回内容。")
            body = bytearray()
            try:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ValueError("网页内容超过 10 MB，已停止读取。")
            finally:
                await response.aclose()
            html = bytes(body).decode(response.encoding or "utf-8", errors="replace")
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else current
            # Off the event loop: see EXTRACT_TIMEOUT_SECONDS. wait_for keeps a pathological
            # page from pinning a worker thread forever.
            text, degraded = await _extract_with_fallback(html)
            clipped = text[:MAX_TEXT_LENGTH]
            return {"url": current, "title": title[:500], "kind": "page", "text": clipped,
                    "length": len(clipped), "truncated": len(text) > MAX_TEXT_LENGTH,
                    "extraction": degraded}

    return await asyncio.wait_for(fetch_page(), timeout=20.0)
