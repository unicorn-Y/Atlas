"""Browser Use browser session bridge for deterministic local/browser tasks."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


class BrowserUseAdapter:
    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}

    async def open(self, url: str, *, cdp_url: str | None = None) -> dict[str, Any]:
        from browser_use import BrowserSession

        host = urlsplit(url).hostname
        session = BrowserSession(
            cdp_url=cdp_url,
            headless=not bool(cdp_url),
            allowed_domains=[host] if host else None,
        )
        await session.start()
        await session.navigate_to(url)
        state = await session.get_state_as_text()
        session_id = str(session.id)
        self._sessions[session_id] = session
        return {"session_id": session_id, "state": str(state)[:4000]}

    async def close(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.kill()
