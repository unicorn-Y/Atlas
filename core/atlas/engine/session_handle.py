"""Unified handle-style session persistence (DSH S5 parity).

DeepSeek-Harness's ``session-persistence`` exposes one durable handle with the
``read / append / flush / close`` lifecycle guarded by a cross-process kernel
lease, so a session has a single writer at a time. Atlas already owns every
underlying primitive: the cross-process turn lease
(``SessionDB.try_acquire_session_turn_lease`` — holders are fenced by PID
liveness, not just expiry), the in-transaction write fence
(``_check_transcript_write_guards`` raises :class:`SessionTurnLeaseLostError`),
the deferred token-counter drain (``flush_token_counts``), and the append-only
``session_events`` log. What was missing is the single handle object that
composes them and one production caller that holds the lease for the duration
of a run (:func:`hold_turn_lease`, wired into ``Agent.execute_run``).

This module only composes existing primitives; it introduces no new storage
and no new table. ``append_message`` keeps the SessionDB write semantics.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Mapping

import structlog

log = structlog.get_logger(__name__)

DEFAULT_LEASE_TTL_SECONDS = 300.0


class SessionHandleUnavailable(RuntimeError):
    """Raised fail-closed when another live process still owns the turn lease."""


@dataclass
class SessionHandle:
    """One conversation's durable write handle: read/append/flush/close.

    The handle borrows an already-open :class:`SessionDB`; ``open`` (or
    :func:`open_session_handle`) owns acquisition and release of the
    cross-process turn lease. Appends carry ``turn_lease_holder`` so the write
    transaction itself refuses when the lease was lost mid-turn — the same
    fence the kernel-level writers rely on.
    """

    db: Any
    session_id: str
    holder: str
    ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS
    _closed: bool = field(default=False, repr=False)

    # -- lifecycle -----------------------------------------------------------

    @classmethod
    def acquire(
        cls, db: Any, session_id: str, holder: str, *,
        ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
    ) -> "SessionHandle | None":
        """Return a handle that owns the cross-process turn lease, or None.

        None means another live holder owns the lease (single-writer admission
        failed); no exception is raised so callers can branch explicitly.
        """
        if not session_id or not holder:
            raise ValueError("SessionHandle.acquire requires session_id and holder")
        if not db.try_acquire_session_turn_lease(session_id, holder, ttl_seconds=ttl_seconds):
            return None
        return cls(db=db, session_id=str(session_id), holder=str(holder), ttl_seconds=ttl_seconds)

    @classmethod
    def open(
        cls, db: Any, session_id: str, holder: str, *,
        ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
    ) -> "SessionHandle":
        """Fail-closed acquisition: raise when the lease is owned elsewhere."""
        handle = cls.acquire(db, session_id, holder, ttl_seconds=ttl_seconds)
        if handle is None:
            raise SessionHandleUnavailable(
                f"Session {session_id!r} is held by another writer (turn lease)")
        return handle

    def refresh(self) -> bool:
        """Extend the lease only while this handle still owns it."""
        if self._closed:
            return False
        return bool(self.db.refresh_session_turn_lease(
            self.session_id, self.holder, ttl_seconds=self.ttl_seconds))

    def lease_expires_at(self) -> float | None:
        return self.db.session_turn_lease_expires_at(self.session_id, self.holder)

    def close(self) -> None:
        """Release the lease iff still owned; idempotent. Does not close the DB."""
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self.db.release_session_turn_lease(self.session_id, self.holder)

    def __enter__(self) -> "SessionHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- durable surface -----------------------------------------------------

    def read_events(self, *, after_seq: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        """Read the append-only session event log (the canonical durable record)."""
        return self.db.list_session_events(self.session_id, after_seq=after_seq, limit=limit)

    def append_event(self, event_type: str, payload: Mapping[str, Any]) -> int:
        """Append one immutable lifecycle event while still owning the lease."""
        return self.db.append_session_event(self.session_id, event_type, dict(payload))

    def append_message(self, role: str, content: Any, metadata: dict[str, Any] | None = None) -> int:
        """Append one transcript message fenced by the turn lease.

        The fence is enforced inside the write transaction: if the lease was
        lost (expired and taken over, or force-released), the write raises
        :class:`SessionTurnLeaseLostError` instead of silently diverging.
        """
        fields = dict(metadata or {})
        formal = (
            "tool_name", "tool_calls", "tool_call_id", "token_count", "finish_reason",
            "reasoning", "reasoning_content", "reasoning_details", "codex_reasoning_items",
            "codex_message_items", "platform_message_id", "observed", "effect_disposition",
            "_compressed_summary", "timestamp", "api_content", "display_kind",
        )
        kwargs = {key: fields.pop(key) for key in formal if key in fields}
        return self.db.append_message(
            self.session_id, role, content=content, display_metadata=fields or None,
            turn_lease_holder=self.holder, turn_lease_ttl_seconds=self.ttl_seconds,
            **kwargs,
        )

    def flush(self) -> bool:
        """Drain deferred token counters so reads observe committed totals."""
        return bool(self.db.flush_token_counts())


def turn_lease_holder(run_id: str | None = None) -> str:
    """Holder string with a verifiable local-process owner (PID + namespace)."""
    from atlas.engine.state.atlas_state_pidns import holder_namespace_token

    token = str(run_id or uuid.uuid4().hex)
    return f"pid={os.getpid()}{holder_namespace_token()}:run={token}"


@contextlib.contextmanager
def open_session_handle(
    home: str | Path, session_id: str, holder: str, *,
    ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
    ensure: bool = True,
) -> Iterator[SessionHandle]:
    """Open a SessionDB on *home* and yield a fail-closed handle; release on exit.

    The database connection is owned by this context manager and closed after
    the lease is released, so one ``with`` block covers the whole lifecycle.
    """
    from atlas.engine.session_sync import _open_db

    with _open_db(home) as db:
        if ensure and db.get_session(session_id) is None:
            db.ensure_session(session_id, "api_server")
        handle = SessionHandle.open(db, session_id, holder, ttl_seconds=ttl_seconds)
        try:
            yield handle
        finally:
            handle.close()


def acquire_run_turn_lease(conversation_id: str, run_id: str | None = None, *,
                           ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
                           home: str | Path | None = None) -> Any | None:
    """Best-effort lease acquisition for one run; None on contention or failure.

    Fail-open by design: the runtime manager already serializes runs per
    conversation, so the lease here adds cross-process single-writer
    visibility (and fences destructive mutations that opt in) without turning
    a transient DB hiccup into a failed user turn. The caller MUST pass the
    returned handle to :func:`release_run_turn_lease`.
    """
    if not conversation_id:
        return None
    try:
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import _open_db

        db_home = Path(home) if home is not None else Path(DATA_ROOT) / "engine"
        opened = _open_db(db_home)
        db = opened.__enter__()
        try:
            handle = SessionHandle.acquire(
                db, conversation_id, turn_lease_holder(run_id), ttl_seconds=ttl_seconds)
        except Exception:
            opened.__exit__(None, None, None)
            raise
        if handle is None:
            opened.__exit__(None, None, None)
            return None
        handle._db_cm = opened  # type: ignore[attr-defined]
        return handle
    except Exception:
        log.debug("session_handle.run_lease_acquire_failed", exc_info=True)
        return None


def release_run_turn_lease(handle: Any | None) -> None:
    """Release a handle from :func:`acquire_run_turn_lease` and close its DB."""
    if handle is None:
        return
    with contextlib.suppress(Exception):
        handle.close()
    with contextlib.suppress(Exception):
        handle._db_cm.__exit__(None, None, None)  # type: ignore[attr-defined]


async def _refresh_loop(handle: Any, interval: float) -> None:
    """Keep the held lease alive until the run ends; a failed refresh is fatal to it."""
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(handle.refresh)
        except Exception:  # pragma: no cover - DB gone; lease will expire naturally
            return


@asynccontextmanager
async def hold_turn_lease(request: Any, *,
                          ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
                          refresh_interval: float | None = None) -> AsyncIterator[Any]:
    """Hold the conversation's turn lease for the duration of one agent run.

    Best-effort: when the lease is unavailable or the store is unreachable the
    run proceeds exactly as before (``None`` is yielded). While held, a
    background task refreshes the lease so long turns keep single-writer
    visibility, and the lease is always released in ``finally``.
    """
    conversation_id = str(getattr(request, "conversation_id", "") or "")
    ephemeral = bool(getattr(request, "ephemeral", False))
    handle = None
    refresher: asyncio.Task | None = None
    if conversation_id and not ephemeral:
        handle = await asyncio.to_thread(
            acquire_run_turn_lease, conversation_id,
            str(getattr(request, "run_id", "") or "") or None, ttl_seconds=ttl_seconds)
        if handle is not None:
            interval = max(0.05, ttl_seconds / 5.0) if refresh_interval is None else refresh_interval
            refresher = asyncio.create_task(_refresh_loop(handle, interval))
    try:
        yield handle
    finally:
        if refresher is not None:
            refresher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refresher
        await asyncio.to_thread(release_run_turn_lease, handle)
