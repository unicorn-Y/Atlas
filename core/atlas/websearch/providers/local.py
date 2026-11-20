"""Free providers that need no vendor account: the local page reader and the keyless ring.

``local`` fetches the page itself through Atlas's SSRF-guarded client and extracts the main text
with trafilatura (``atlas.tools.web_extract.extract_web``, which also reads YouTube / Bilibili
captions). It costs nothing and is tried first; JavaScript-only or bot-walled pages come back
empty and fall through to a vendor extractor.
"""

from __future__ import annotations

from typing import Any

from atlas.websearch import keyless
from atlas.websearch.common import VENDOR_ERRORS, document, page_error
from atlas.websearch.providers.base import WebProvider
from atlas.websearch.settings import WebSettings

# Below this much text a "successful" local read is usually a cookie wall, a JS shell or a
# login page; let a vendor renderer try.
MIN_LOCAL_TEXT = 200


def _looks_binary(text: str) -> bool:
    head = text[:2000]
    if head.lstrip().startswith(("%PDF", "PK\x03\x04")):
        return True
    return bool(head) and (head.count("�") + head.count("\x00")) / len(head) > 0.05


class LocalProvider(WebProvider):
    name, display_name = "local", "Local reader"
    needs_key = False
    can_search = False
    can_extract = True

    async def extract(self, urls: list[str], settings: WebSettings) -> list[dict[str, Any]]:
        from atlas.tools.web_extract import WebFetchPolicyError, extract_web

        out = []
        for url in urls:
            try:
                page = await extract_web(url)
            except WebFetchPolicyError as exc:
                out.append({"url": url, "title": "", "content": "",
                            "error": str(exc), "error_category": "policy"})
                continue
            except VENDOR_ERRORS as exc:
                out.append(page_error(url, f"local read failed: {exc}"))
                continue
            text = str(page.get("text") or "")
            if _looks_binary(text):
                # PDFs and other files: the local reader would hand back decoded bytes. Vendor
                # extractors (Exa / Parallel / Tavily) parse PDFs properly.
                out.append(page_error(url, "local reader cannot parse this file type (PDF/binary)"))
                continue
            if page.get("kind") != "video" and len(text.strip()) < MIN_LOCAL_TEXT:
                out.append(page_error(url, f"local read got only {len(text.strip())} chars (JS-rendered or blocked page)"))
                continue
            out.append(document(str(page.get("url") or url), str(page.get("title") or ""), text,
                                served_by="local", kind=page.get("kind"),
                                truncated=page.get("truncated"), status_code=page.get("status_code")))
        return out


class KeylessProvider(WebProvider):
    name, display_name = "keyless", "Free tier (Exa / Parallel / Keenable / Tavily)"
    needs_key = False
    can_extract = True

    def available(self, settings: WebSettings) -> bool:
        return settings.keyless

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        return await self.guard_search(lambda: keyless.search(query, limit))

    async def extract(self, urls: list[str], settings: WebSettings) -> list[dict[str, Any]]:
        return await self.guard_extract(urls, lambda: keyless.extract(urls))
