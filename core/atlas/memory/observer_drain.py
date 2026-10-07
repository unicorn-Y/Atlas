"""Drive durable Observer batches after their source captures receive HTTP ACKs."""

from __future__ import annotations

from collections import Counter
from typing import Any

import structlog

log = structlog.get_logger()


class MemoryObserverDrain:
    """Capture-tick worker logic; task scheduling remains owned by server lifespan."""

    def __init__(self, observer: Any, facade: Any) -> None:
        self.observer = observer
        self.facade = facade
        self.end_sessions: set[str] = set()
        self.active_session: str | None = None

    def note_session_started(self, session_id: str) -> None:
        session = str(session_id or "").strip()
        if not session:
            return
        if self.active_session and self.active_session != session:
            self.end_session(self.active_session)
        self.active_session = session

    def end_session(self, session_id: str) -> None:
        session = str(session_id or "").strip()
        if not session:
            return
        # Persist before this signal can be delayed behind any in-flight model call.
        self.observer.mark_session_ended(session)
        self.end_sessions.add(session)

    def end_active_session(self) -> None:
        if self.active_session:
            self.end_session(self.active_session)

    async def drain_once(self) -> None:
        """Resume ACKED source work; only release a batch on a complete HTTP ACK."""
        sessions = set(self.observer.pending_sessions())
        sessions.update(self.end_sessions)
        for session_id in sorted(sessions):
            ended = session_id in self.end_sessions
            stage = "resume"
            try:
                context = self.facade.default_context(runtime_session_id=session_id)
                batch = await self.observer.resume(
                    session_id, context=context, session_ended=ended,
                )
                if ended:
                    self.end_sessions.discard(session_id)
                while batch is not None:
                    stage = "observe_http_ack"
                    if batch.payload is not None:
                        ack = await self.facade.observe_batch(batch.payload)
                        expected = len(batch.payload.get("observations") or [])
                        receipts = ack.get("receipts") if isinstance(ack, dict) else None
                        expected_sources = Counter(
                            str(item.get("source_event_id") or "")
                            for item in batch.payload.get("observations") or []
                            if isinstance(item, dict)
                        )
                        receipt_sources = Counter(
                            str(item.get("source_event_id") or "")
                            for item in receipts or [] if isinstance(item, dict)
                        )
                        if (
                            not isinstance(ack, dict)
                            or int(ack.get("accepted", -1)) != expected
                            or not isinstance(receipts, list)
                            or len(receipts) != expected
                            or not expected_sources
                            or "" in expected_sources
                            or receipt_sources != expected_sources
                        ):
                            raise RuntimeError(
                                "MemoryOS observe response receipts did not match every derived source_event_id"
                            )
                    stage = "observer_outbox_ack"
                    batch = await self.observer.ack_batch(batch.batch_id)
            except Exception as exc:  # noqa: BLE001 — keep pending batch for the next capture tick
                log.exception(
                    "memory.observer_drain_failed", session_id=session_id,
                    stage=stage, error=str(exc),
                )
