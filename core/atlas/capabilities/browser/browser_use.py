"""Browser Use browser session bridge for deterministic local/browser tasks."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


class BrowserUseAdapter:
    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}
        self.authenticated: bool | None = None
        self.smoke_verified = False
        self.last_error: str | None = None

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

    async def task(
        self,
        goal: str,
        *,
        start_url: str | None = None,
        model: str | None = None,
        session_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a Browser Use Agent task with Atlas' configured model gateway."""
        from browser_use import Agent, BrowserSession
        from browser_use.llm import ChatOpenAI

        from atlas.config import get_config

        config = get_config()
        api_key = config.gateway_api_key
        if not api_key:
            self.authenticated = False
            self.last_error = "Atlas model gateway credentials are not configured"
            raise RuntimeError("Browser Use requires an Atlas model gateway API key")
        options = session_options or {}
        host = urlsplit(start_url).hostname if start_url else None
        session = BrowserSession(
            cdp_url=options.get("cdp_url"),
            headless=bool(options.get("headless", not bool(options.get("cdp_url")))),
            allowed_domains=options.get("allowed_domains", [host] if host else None),
        )
        await session.start()
        if start_url:
            await session.navigate_to(start_url)
        session_id = str(session.id)
        self._sessions[session_id] = session
        prompt = f"{goal}\nStart URL: {start_url}" if start_url else goal
        try:
            agent = Agent(
                task=prompt,
                llm=ChatOpenAI(
                    model=model or "gpt-4o-mini",
                    base_url=config.gateway_base_url,
                    api_key=api_key,
                ),
                browser_session=session,
                max_failures=int(options.get("max_failures", 3)),
            )
            result = await agent.run(max_steps=int(options.get("max_steps", 20)))
            final_result = result.final_result() if hasattr(result, "final_result") else str(result)
            errors = result.errors() if hasattr(result, "errors") else []
            error_text = " ".join(error for error in errors if error)
            auth_errors = ("token_rejected", "invalid token", "401", "403")
            if any(term in error_text.lower() for term in auth_errors):
                self.authenticated = False
                self.last_error = "Atlas model gateway rejected Browser Use credentials"
            elif error_text:
                self.authenticated = None
                self.last_error = "Browser Use Agent task encountered an upstream error"
            else:
                self.authenticated = True
                self.last_error = None
            self.smoke_verified = bool(
                not error_text
                and (not hasattr(result, "is_done") or result.is_done())
                and (not hasattr(result, "is_successful") or result.is_successful() is not False)
            )
            if error_text:
                raise RuntimeError(self.last_error or "Browser Use Agent task failed")
            return {
                "session_id": session_id,
                "result": final_result,
                "smoke_verified": self.smoke_verified,
            }
        except BaseException as exc:
            if isinstance(exc, Exception) and self.last_error is None:
                message = str(exc).lower()
                auth_errors = ("token_rejected", "invalid token", "401", "403")
                if any(term in message for term in auth_errors):
                    self.authenticated = False
                    self.last_error = "Atlas model gateway rejected Browser Use credentials"
                else:
                    self.last_error = f"Browser Use Agent task failed ({type(exc).__name__})"
            self._sessions.pop(session_id, None)
            await session.kill()
            raise

    async def close(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.kill()
