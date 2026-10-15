# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: plugins/web/ddgs/provider.py (MIT)
"""DuckDuckGo-and-friends metasearch via the optional ``ddgs`` package (no key, search only).

Translated from Hermes ``plugins/web/ddgs/provider.py`` (NousResearch/hermes-agent@c9e076b).
``ddgs``/``primp`` can block inside native code while holding the GIL, so a thread timeout can
never fire; every search runs in a disposable child process (``_ddgs_worker``) that the
parent kills at the deadline. Atlas uses asyncio subprocesses instead of Hermes's
thread-polled Popen.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sys
from typing import Any

from atlas.websearch.common import search_fail, search_ok
from atlas.websearch.providers.base import WebProvider
from atlas.websearch.settings import WebSettings

logger = logging.getLogger("atlas.websearch")

SEARCH_TIMEOUT_SECS = 30.0


class DDGSProvider(WebProvider):
    name, display_name = "ddgs", "DuckDuckGo (ddgs)"
    needs_key = False

    def available(self, settings: WebSettings) -> bool:
        return importlib.util.find_spec("ddgs") is not None

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        if not self.available(settings):
            return search_fail("ddgs package is not installed (pip install ddgs)")
        request = json.dumps({"query": query, "limit": max(1, int(limit))})
        flags: dict[str, Any] = (
            {"creationflags": 0x00000200 | 0x08000000}  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            if sys.platform == "win32" else {"start_new_session": True}
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "atlas.websearch.providers._ddgs_worker",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env=dict(os.environ), **flags,
            )
        except OSError as exc:
            return search_fail(f"DuckDuckGo search failed to start: {exc}")
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(request.encode("utf-8")), SEARCH_TIMEOUT_SECS)
        except (TimeoutError, asyncio.CancelledError) as exc:
            await _kill(proc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            return search_fail(f"DuckDuckGo search timed out after {SEARCH_TIMEOUT_SECS:.0f}s (likely rate-limited)")
        try:
            envelope = json.loads(stdout.decode("utf-8", errors="replace").strip() or "{}")
        except json.JSONDecodeError:
            return search_fail("DuckDuckGo search returned an invalid response")
        if not envelope.get("ok"):
            return search_fail(f"DuckDuckGo search failed: {envelope.get('error') or 'worker exited without a result'}")
        return search_ok(list(envelope.get("results") or [])[:limit])


async def _kill(proc: asyncio.subprocess.Process) -> None:
    for step in (proc.terminate, proc.kill):
        if proc.returncode is not None:
            return
        try:
            step()
            await asyncio.wait_for(proc.wait(), 1.0)
        except (TimeoutError, ProcessLookupError):
            continue
        except OSError as exc:
            logger.debug("ddgs worker reap error: %s", exc)
            return
