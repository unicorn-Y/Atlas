"""Startup component states for /api/health (H8 §10.2).

The lifespan split (S2) keeps only the critical path before ``yield``; every
deferred component registers here as ``starting`` and flips to ``ready`` or
``failed`` from the deferred startup task. ``wait_ready()`` lets request paths
that genuinely need a deferred component await it (bounded); everything else
keeps working while components start (S3's degraded-run contract).
"""

from __future__ import annotations

import asyncio
import time

import structlog

log = structlog.get_logger(__name__)

# The deferred components (S2): every name is marked "starting" on the
# critical path, before uvicorn binds, so /api/health can always report them.
COMPONENT_NAMES: tuple[str, ...] = (
    "dbos", "mcp", "skills", "plugins", "engine_registrations",
    "channels", "automation", "scheduler", "telegram", "extensions",
)

VALID_STATES = frozenset({"starting", "ready", "failed"})


class StartupComponents:
    """Per-component lifecycle state: starting → ready | failed."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._events: dict[str, asyncio.Event] = {}

    def mark(self, name: str, state: str) -> None:
        if state not in VALID_STATES:
            raise ValueError(f"invalid startup component state: {state!r}")
        self._states[name] = state
        if state != "starting":
            # Only a settled state releases wait_ready(): a component marked
            # "starting" keeps its waiters parked (S3's bounded wait must
            # actually wait, and a later ready/failed mark wakes them).
            self._events.setdefault(name, asyncio.Event()).set()
        (log.error if state == "failed" else log.info)(
            "startup.component", component=name, state=state,
        )

    def state(self, name: str) -> str | None:
        """Current state of one component, or None when never registered."""
        return self._states.get(name)

    def snapshot(self) -> dict[str, str]:
        return dict(self._states)

    async def wait_ready(self, name: str, timeout: float = 30.0) -> bool:
        event = self._events.setdefault(name, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return self._states.get(name) == "ready"

    async def wait_all_ready(self, timeout: float = 30.0) -> bool:
        """Wait until every known component settled; True only if all ready.

        Test-harness helper (and any caller that wants the "fully started"
        quiescent point): components never registered count as not ready.
        """
        async def _settle_all() -> None:
            await asyncio.gather(
                *(self.wait_ready(name, timeout=timeout) for name in COMPONENT_NAMES)
            )

        try:
            await asyncio.wait_for(_settle_all(), timeout)
        except asyncio.TimeoutError:
            return False
        return all(self._states.get(name) == "ready" for name in COMPONENT_NAMES)

    def wait_all_ready_sync(self, timeout: float = 30.0, poll: float = 0.05) -> bool:
        """Blocking variant of :meth:`wait_all_ready` for sync callers (e.g.
        TestClient fixtures, whose app loop runs on a portal thread)."""
        deadline = time.monotonic() + timeout
        while True:
            states = self.snapshot()
            if states and all(state == "ready" for state in states.values()):
                return True
            if any(state == "failed" for state in states.values()):
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll)
