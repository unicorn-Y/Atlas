# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: tools/web_result_cache.py (MIT)
"""Search memo + extract cache + head/tail truncation for web results.

Translated from Hermes ``tools/web_result_cache.py`` and ``tools/web_tools_truncate.py``
(NousResearch/hermes-agent@c9e076b). Atlas changes: the memo is asyncio single-flight (Atlas
tools run on one event loop), the disk cache lives under ``<data>/data/cache/web``, and the
truncation footer points at Atlas's ``read_file``.

* Search memo — in-memory TTL, keyed on (route, normalized query, limit bucket); concurrent
  identical searches share one vendor call. Only successful, non-rescued answers are stored.
* Extract cache — disk-backed, one file per URL plus a JSON index, TTL-bounded.
* Truncation — pages over the char budget become a 75% head / 25% tail window cut on line
  boundaries; the complete text is saved to disk and the footer says how to page it.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("atlas.websearch")

_LIMIT_BUCKETS = (10, 20, 50, 100)
_INDEX_FILENAME = "extract-index.json"
_INDEX_MAX_ENTRIES = 500
MAX_STORED_TEXT_CHARS = 2_000_000


def bucket_limit(limit: int) -> int:
    return next((b for b in _LIMIT_BUCKETS if limit <= b), _LIMIT_BUCKETS[-1])


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


class SearchMemo:
    def __init__(self) -> None:
        self._store: dict[tuple, tuple[float, dict]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}

    @staticmethod
    def key(route: str, query: str, limit: int) -> tuple:
        return (route, normalize_query(query), bucket_limit(limit))

    def lookup(self, key: tuple) -> dict | None:
        entry = self._store.get(key)
        if entry is None or time.monotonic() >= entry[0]:
            self._store.pop(key, None)
            return None
        return _copy(entry[1])

    def store(self, key: tuple, response: dict, ttl_seconds: float) -> None:
        if not response.get("success"):
            return
        now = time.monotonic()
        for k in [k for k, (exp, _) in self._store.items() if now >= exp]:
            del self._store[k]
        self._store[key] = (now + ttl_seconds, _copy(response))

    def lock(self, key: tuple) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            if len(self._locks) > 256:  # never drop a held lock: that would allow a duplicate paid call
                self._locks = {k: v for k, v in self._locks.items() if v.locked()}
            lock = self._locks[key] = asyncio.Lock()
        return lock

    def clear(self) -> None:
        self._store.clear()
        self._locks.clear()


search_memo = SearchMemo()


def slice_rows(response: dict, limit: int) -> dict:
    rows = (response.get("data") or {}).get("web")
    if isinstance(rows, list) and len(rows) > limit:
        response = _copy(response)
        response["data"]["web"] = response["data"]["web"][:limit]
    return response


# --- disk cache -----------------------------------------------------------------

_index_lock = threading.Lock()


def cache_dir() -> Path | None:
    try:
        from atlas.config import DATA_ROOT

        path = Path(DATA_ROOT) / "data" / "cache" / "web"
        path.mkdir(parents=True, exist_ok=True)
        return path
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _host_slug(url: str) -> str:
    host = (urlparse(url).hostname or "page").replace(":", "_")
    return re.sub(r"[^A-Za-z0-9._-]", "-", host)[:60].strip("-") or "page"


def _digest(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _is_local_url(url: str) -> bool:
    """Loopback / LAN pages are the user's own dev servers — never cached."""
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _load_index(root: Path) -> dict:
    try:
        data = json.loads((root / _INDEX_FILENAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def _save_index(root: Path, index: dict) -> None:
    if len(index) > _INDEX_MAX_ENTRIES:
        newest = sorted(index.items(), key=lambda kv: kv[1].get("fetched_at", 0), reverse=True)
        index = dict(newest[:_INDEX_MAX_ENTRIES])
    tmp = root / (_INDEX_FILENAME + ".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    tmp.replace(root / _INDEX_FILENAME)


def extract_cache_get(url: str, ttl_seconds: float) -> dict | None:
    root = cache_dir()
    if root is None or _is_local_url(url):
        return None
    with _index_lock:
        entry = _load_index(root).get(_digest(url))
    if not entry or time.time() - float(entry.get("fetched_at", 0)) >= ttl_seconds:
        return None
    try:
        path = Path(entry["file"])
        if root.resolve() not in path.resolve().parents:  # tampered index must not read outside the cache
            return None
        content = path.read_text(encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return {"url": url, "title": entry.get("title", ""), "content": content,
            "metadata": {"served_by": entry.get("served_by", ""), "cached": True}}


def extract_cache_put(url: str, page: dict) -> None:
    content = page.get("content") or ""
    root = cache_dir()
    if root is None or not content or len(content) > MAX_STORED_TEXT_CHARS or _is_local_url(url):
        return
    try:
        path = root / f"{_host_slug(url)}-{_digest(url)}.cache.md"
        path.write_text(content, encoding="utf-8")
        with _index_lock:
            index = _load_index(root)
            index[_digest(url)] = {"url": url, "file": str(path), "title": page.get("title", ""),
                                   "served_by": (page.get("metadata") or {}).get("served_by", ""),
                                   "fetched_at": time.time()}
            _save_index(root, index)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.debug("web extract cache write failed for %s: %s", url, exc)


# --- truncation -------------------------------------------------------------------

def strip_base64_images(text: str) -> str:
    """Inline base64 images are token bombs: replace them with ``[IMAGE: alt]`` placeholders."""
    out = re.sub(r"!\[(?P<alt>[^\]]*)\]\(\s*data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)",
                 lambda m: f"[IMAGE: {m.group('alt').strip()}]" if m.group("alt").strip() else "[IMAGE]", text)
    out = re.sub(r"\(\s*data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)", "[IMAGE]", out)
    return re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[IMAGE]", out)


def _store_full_text(url: str, content: str) -> str | None:
    root = cache_dir()
    if root is None:
        return None
    try:
        path = root / f"{_host_slug(url)}-{_digest(url)}.full.md"
        if len(content) > MAX_STORED_TEXT_CHARS:
            content = content[:MAX_STORED_TEXT_CHARS] + f"\n\n[... stored copy cut at {MAX_STORED_TEXT_CHARS:,} chars ...]"
        path.write_text(content, encoding="utf-8")
        return str(path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.debug("web full-text store failed for %s: %s", url, exc)
        return None


def truncate(content: str, url: str, char_limit: int) -> tuple[str, bool]:
    """(model_text, truncated). Over-budget pages keep a head+tail window and a footer naming the
    saved full text and the ``read_file`` call that pages the omitted middle."""
    if len(content) <= char_limit:
        return content, False
    head_budget = int(char_limit * 0.75)
    tail_budget = char_limit - head_budget
    head, tail = content[:head_budget], content[-tail_budget:]
    if (nl := head.rfind("\n")) > head_budget * 0.5:
        head = head[:nl]
    if 0 <= (nl := tail.find("\n")) < tail_budget * 0.5:
        tail = tail[nl + 1:]
    footer = ["", "──────── [TRUNCATED] ────────",
              f"Showing {len(head):,} chars (head) + {len(tail):,} chars (tail) of {len(content):,} total."]
    if stored := _store_full_text(url, content):
        footer += [f"Full text saved to: {stored}",
                   f'Read the omitted middle with read_file path="{stored}" offset={head.count(chr(10)) + 2} limit=200.']
    else:
        footer.append("Full text could not be saved; fetch a more specific URL or use the browser.")
    return head + "\n\n[... middle omitted — see footer ...]\n\n" + tail + "\n" + "\n".join(footer), True
