"""X2 shared context: run-scoped channels for events, approvals and human handoff.

Every X2 bridge (computer / browser / vault / recordings) receives an
:class:`X2Context` through :func:`current_context` so tool handlers can emit
frontend events, request foreground confirmation and block on human handoff
without touching the agent loop.  The dispatcher sets the context for the
duration of each tool call.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import logging

logger = logging.getLogger(__name__)

# ---- event names (wire contract with frontend runtimeEvents.ts) -----------
EVENT_FOREGROUND_REQUIRED = "computer.foreground_required"
EVENT_FOREGROUND_RESUMED = "computer.foreground_resumed"
EVENT_HANDOFF_REQUIRED = "browser.handoff_required"
EVENT_HANDOFF_RESOLVED = "browser.handoff_resolved"
EVENT_PANEL_SYNC = "browser.panel.sync"
EVENT_COMPUTER_STEP = "computer.step"
EVENT_COMPUTER_FRAME = "computer.frame"
EVENT_BROWSER_STEP = "browser.step"

# input.response option values used by the handoff / foreground cards
HANDOFF_OPEN_PANEL = "open_panel"
HANDOFF_DONE = "done"
HANDOFF_GIVE_UP = "give_up"


@dataclass
class X2Context:
    """Run-scoped services handed to X2 tool handlers."""

    run_id: str | None = None
    session_id: str | None = None
    emit: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
    approval_callback: Callable[[str, str, dict[str, Any]], Any] | None = None
    # wait_input(prompt, options) -> user choice string; used to block a run
    # until the human resolves a handoff / foreground confirmation card.
    wait_input: Callable[[str, list[str]], Awaitable[str]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    async def emit_event(self, event: str, data: dict[str, Any] | None = None) -> None:
        if self.emit is None:
            return
        try:
            await self.emit(event, data or {})
        except Exception:  # noqa: BLE001 - event emission must never break a tool call
            logger.debug("atlas.tools.x2.context: ignored error", exc_info=True)

    async def confirm_foreground(self, reason: str, target: str = "") -> bool:
        """Ask the user via a foreground confirmation card.  Returns True when approved.

        Falls back to approved=True when no UI channel is wired (headless/tests).
        """
        if self.wait_input is None:
            return True
        await self.emit_event(EVENT_FOREGROUND_REQUIRED, {
            "reason": reason,
            "target": target,
            "run_id": self.run_id,
        })
        choice = await self.wait_input(
            f"需要切到前台操作（{reason}）。是否允许 Atlas 接管鼠标键盘？",
            ["allow", "deny"],
        )
        allowed = choice not in {"deny", "give_up", HANDOFF_GIVE_UP, ""}
        await self.emit_event(
            EVENT_FOREGROUND_RESUMED if allowed else "computer.foreground_denied",
            {"reason": reason},
        )
        return allowed

    async def request_handoff(self, reason: str, url: str = "") -> str:
        """Emit a handoff card and block until the human resolves it.

        Returns one of HANDOFF_OPEN_PANEL / HANDOFF_DONE / HANDOFF_GIVE_UP.
        """
        await self.emit_event(EVENT_HANDOFF_REQUIRED, {
            "reason": reason,
            "url": url,
            "run_id": self.run_id,
        })
        if self.wait_input is None:
            # No UI channel: surface the reason and let the caller decide.
            return HANDOFF_GIVE_UP
        choice = await self.wait_input(
            f"需要人工处理：{reason}" + (f"（{url}）" if url else ""),
            [HANDOFF_OPEN_PANEL, HANDOFF_DONE, HANDOFF_GIVE_UP],
        )
        await self.emit_event(EVENT_HANDOFF_RESOLVED, {"choice": choice, "url": url})
        return choice or HANDOFF_DONE


_context: ContextVar[X2Context | None] = ContextVar("atlas_x2_context", default=None)


def set_context(ctx: X2Context | None) -> Any:
    return _context.set(ctx)


def reset_context(token: Any) -> None:
    _context.reset(token)


def current_context() -> X2Context:
    """Context for the running tool call; a detached default when unset."""
    ctx = _context.get()
    return ctx if ctx is not None else X2Context()
