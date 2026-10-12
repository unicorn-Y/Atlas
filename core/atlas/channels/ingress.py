"""Durable inbound queue — port of OpenClaw channel ingress semantics (r1 §2.5/§5.1).

SQLite table ``inbound_events`` is the durable buffer between adapters and the
dispatcher; a ``channel+account+event_id`` unique index makes enqueue idempotent.
Completed events leave a **tombstone** (TTL 20 min) so duplicates arriving after
a process restart are still rejected.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from atlas.channels.contract import Attachment, MessageEvent, MessageType

TOMBSTONE_TTL_SECONDS = 20 * 60
CLAIM_LEASE_SECONDS = 300.0
# r1 ingress retry policy: 1s ×2 capped at 3min, 8 attempts then dead.
INGRESS_BACKOFF_INITIAL = 1.0
INGRESS_BACKOFF_FACTOR = 2.0
INGRESS_BACKOFF_CAP = 180.0
INGRESS_MAX_ATTEMPTS = 8


def event_to_payload(event: MessageEvent) -> dict[str, Any]:
    data = asdict(event)
    data["kind"] = event.kind.value
    return data


def event_from_payload(data: dict[str, Any]) -> MessageEvent:
    data = dict(data)
    attachments = []
    for raw in data.get("attachments") or []:
        item = dict(raw)
        item["kind"] = MessageType(str(item.get("kind", "text")))
        attachments.append(Attachment(**item))
    return MessageEvent(
        channel=str(data.get("channel", "")),
        account=str(data.get("account", "")),
        event_id=str(data.get("event_id", "")),
        chat_id=str(data.get("chat_id", "")),
        sender_id=str(data.get("sender_id", "")),
        kind=MessageType(str(data.get("kind", "text"))),
        text=str(data.get("text", "")),
        thread_id=str(data.get("thread_id", "")),
        sender_name=str(data.get("sender_name", "")),
        is_group=bool(data.get("is_group", False)),
        is_mention=bool(data.get("is_mention", False)),
        reply_to_event_id=str(data.get("reply_to_event_id", "")),
        attachments=attachments,
        ts=float(data.get("ts", 0.0)),
        raw=dict(data.get("raw") or {}),
    )


@dataclass(slots=True)
class InboundRecord:
    id: int
    channel: str
    account: str
    event_id: str
    event: MessageEvent
    attempts: int
    claimed_by: str
    claimed_at: float
    created_at: float


class IngressQueue:
    """Durable inbound queue with claim/ack/fail and cross-restart dedupe."""

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        from hermes_state_wal import apply_wal_with_fallback

        apply_wal_with_fallback(self._db, db_label="Atlas channel ingress")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS inbound_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    account TEXT NOT NULL DEFAULT '',
                    event_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL DEFAULT 0,
                    claimed_at REAL,
                    claimed_by TEXT DEFAULT '',
                    created_at REAL NOT NULL
                )
                """
            )
            self._db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_inbound_dedupe "
                "ON inbound_events(channel, account, event_id)"
            )
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS inbound_tombstones (
                    channel TEXT NOT NULL,
                    account TEXT NOT NULL DEFAULT '',
                    event_id TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT 'done',
                    created_at REAL NOT NULL
                )
                """
            )
            self._db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_inbound_tombstone "
                "ON inbound_tombstones(channel, account, event_id)"
            )

    def close(self) -> None:
        self._db.close()

    # -- enqueue ------------------------------------------------------------

    def enqueue_inbound(self, event: MessageEvent, *, now: float | None = None) -> bool:
        """Insert one event; ``False`` when it is a duplicate (row or tombstone)."""
        now = time.time() if now is None else now
        self._prune_tombstones(now)
        if self.has_tombstone(event.channel, event.account, event.event_id):
            return False  # completed/failed before (e.g. before a restart)
        payload = json.dumps(event_to_payload(event), ensure_ascii=False)
        with self._db:
            try:
                self._db.execute(
                    "INSERT INTO inbound_events"
                    "(channel, account, event_id, payload, created_at) VALUES (?,?,?,?,?)",
                    (event.channel, event.account, event.event_id, payload, now),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def _prune_tombstones(self, now: float, ttl: float = TOMBSTONE_TTL_SECONDS) -> int:
        with self._db:
            cursor = self._db.execute(
                "DELETE FROM inbound_tombstones WHERE created_at < ?", (now - ttl,)
            )
            return cursor.rowcount

    def has_tombstone(self, channel: str, account: str, event_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM inbound_tombstones WHERE channel=? AND account=? AND event_id=?",
            (channel, account, event_id),
        ).fetchone()
        return row is not None

    def tombstone_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM inbound_tombstones").fetchone()[0])

    # -- claim / ack / fail --------------------------------------------------

    def claim_batch(
        self,
        limit: int = 1,
        *,
        worker_id: str = "gateway",
        lease_seconds: float = CLAIM_LEASE_SECONDS,
        now: float | None = None,
    ) -> list[InboundRecord]:
        """Claim up to ``limit`` runnable events (pending or lease-expired)."""
        now = time.time() if now is None else now
        claimed: list[InboundRecord] = []
        # A row exists = work pending; claim state is carried by claimed_at only
        # (unclaimed rows have claimed_at IS NULL, stale leases have an old ts).
        rows = self._db.execute(
            "SELECT id FROM inbound_events WHERE available_at <= ? AND"
            " (claimed_at IS NULL OR claimed_at <= ?) ORDER BY id LIMIT ?",
            (now, now - lease_seconds, limit),
        ).fetchall()
        for (row_id,) in rows:
            with self._db:
                cursor = self._db.execute(
                    "UPDATE inbound_events SET claimed_at=?, claimed_by=? WHERE id=? AND ("
                    "claimed_at IS NULL OR claimed_at <= ?)",
                    (now, worker_id, row_id, now - lease_seconds),
                )
                if cursor.rowcount != 1:
                    continue
                row = self._db.execute(
                    "SELECT id, channel, account, event_id, payload, attempts,"
                    " claimed_at, claimed_by, created_at FROM inbound_events WHERE id=?",
                    (row_id,),
                ).fetchone()
            if row is None:
                continue
            claimed.append(
                InboundRecord(
                    id=int(row[0]),
                    channel=str(row[1]),
                    account=str(row[2]),
                    event_id=str(row[3]),
                    event=event_from_payload(json.loads(row[4])),
                    attempts=int(row[5]),
                    claimed_by=str(row[7] or ""),
                    claimed_at=float(row[6] or 0.0),
                    created_at=float(row[8]),
                )
            )
        return claimed

    def ack(self, record_id: int, *, now: float | None = None) -> bool:
        """Complete one event: keep a dedupe tombstone, drop the queue row."""
        now = time.time() if now is None else now
        with self._db:
            row = self._db.execute(
                "SELECT channel, account, event_id FROM inbound_events WHERE id=?",
                (record_id,),
            ).fetchone()
            if row is None:
                return False
            self._db.execute(
                "INSERT OR REPLACE INTO inbound_tombstones"
                "(channel, account, event_id, reason, created_at) VALUES (?,?,?,?,?)",
                (row[0], row[1], row[2], "done", now),
            )
            self._db.execute("DELETE FROM inbound_events WHERE id=?", (record_id,))
            return True

    def ack_event(self, event: MessageEvent) -> bool:
        """Complete an admitted control reply while the ordinary drain is busy."""
        row = self._db.execute(
            "SELECT id FROM inbound_events WHERE channel=? AND account=? AND event_id=?",
            (event.channel, event.account, event.event_id),
        ).fetchone()
        return self.ack(int(row[0])) if row else False

    def fail(
        self,
        record_id: int,
        error: str,
        *,
        retryable: bool = True,
        max_attempts: int = INGRESS_MAX_ATTEMPTS,
        now: float | None = None,
    ) -> str:
        """Report a processing failure.

        Returns ``"retry"`` (requeued with ingress backoff), ``"dead"`` (tombstoned
        and removed after the attempt budget) or ``"gone"`` (row vanished).
        """
        now = time.time() if now is None else now
        with self._db:
            row = self._db.execute(
                "SELECT channel, account, event_id, attempts FROM inbound_events WHERE id=?",
                (record_id,),
            ).fetchone()
            if row is None:
                return "gone"
            channel, account, event_id, attempts = row[0], row[1], row[2], int(row[3]) + 1
            if not retryable or attempts >= max_attempts:
                self._db.execute(
                    "INSERT OR REPLACE INTO inbound_tombstones"
                    "(channel, account, event_id, reason, created_at) VALUES (?,?,?,?,?)",
                    (channel, account, event_id, "failed", now),
                )
                self._db.execute("DELETE FROM inbound_events WHERE id=?", (record_id,))
                return "dead"
            delay = min(
                INGRESS_BACKOFF_INITIAL * (INGRESS_BACKOFF_FACTOR ** (attempts - 1)),
                INGRESS_BACKOFF_CAP,
            )
            self._db.execute(
                "UPDATE inbound_events SET attempts=?, available_at=?, claimed_at=NULL,"
                " claimed_by='' WHERE id=?",
                (attempts, now + delay, record_id),
            )
            return "retry"

    # -- introspection -------------------------------------------------------

    def pending_count(self, channel: str | None = None) -> int:
        if channel is None:
            return int(self._db.execute("SELECT COUNT(*) FROM inbound_events").fetchone()[0])
        row = self._db.execute(
            "SELECT COUNT(*) FROM inbound_events WHERE channel=?", (channel,)
        ).fetchone()
        return int(row[0])

    def stats(self) -> dict[str, int]:
        return {
            "pending": self.pending_count(),
            "tombstones": self.tombstone_count(),
        }


__all__ = [
    "TOMBSTONE_TTL_SECONDS",
    "CLAIM_LEASE_SECONDS",
    "INGRESS_MAX_ATTEMPTS",
    "InboundRecord",
    "IngressQueue",
    "event_to_payload",
    "event_from_payload",
]
