"""Bounded web page and caption extraction with redirect-time SSRF checks."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_TEXT_LENGTH = 60_000


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


def _validate_url(url: str, allow_local: bool) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持 http 或 https 网页地址。")
    host = parsed.hostname.rstrip(".").casefold()
    local_exception = allow_local and host in {"localhost", "127.0.0.1"}
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            records = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                         type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError("无法解析这个网址。") from exc
        addresses = [ipaddress.ip_address(record[4][0]) for record in records]
    if not local_exception and any(not address.is_global for address in addresses):
        raise ValueError("出于安全考虑，不能读取内网或本机地址。")
    return url


async def _video_captions(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if "youtube.com" in (parsed.hostname or "") or parsed.hostname == "youtu.be":
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


async def extract_web(url: str, *, allow_local: bool = False,
                      client_factory=httpx.AsyncClient) -> dict[str, object]:
    checked = _validate_url(url, allow_local)
    host = (urlparse(checked).hostname or "").casefold()
    if host.endswith("youtube.com") or host == "youtu.be" or host.endswith("bilibili.com"):
        text, note = await _video_captions(checked)
        if note:
            text = note
        clipped = text[:MAX_TEXT_LENGTH]
        return {"url": checked, "title": "视频字幕", "kind": "video", "text": clipped,
                "length": len(clipped), "truncated": len(text) > MAX_TEXT_LENGTH}

    timeout = httpx.Timeout(20.0)
    async with client_factory(timeout=timeout, follow_redirects=False) as client:
        current = checked
        response = None
        for _ in range(6):
            _validate_url(current, allow_local)
            response = await client.get(current, headers={"User-Agent": "Atlas/1.0"})
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
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("网页内容超过 10 MB，已停止读取。")
        html = bytes(body).decode(response.encoding or "utf-8", errors="replace")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else current
        try:
            import trafilatura
            text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
        except ImportError:
            parser = _TextParser()
            parser.feed(html)
            text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
            text = re.sub(r"\n\s*\n+", "\n", text).strip()
        clipped = text[:MAX_TEXT_LENGTH]
        return {"url": current, "title": title[:500], "kind": "page", "text": clipped,
                "length": len(clipped), "truncated": len(text) > MAX_TEXT_LENGTH}
