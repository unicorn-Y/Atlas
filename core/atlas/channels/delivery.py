"""Durable outbound delivery queue (r1 §5.2 semantics, Atlas-sized).

Table ``outbound_messages`` keyed by a unique ``idempotency_key`` (sha256 of the
logical message unless supplied). Failed sends retry with backoff
``[30s, 1m, 5m, 15m, 1h]`` (capped at 1h) and dead-letter after the budget is
exhausted; ``sending`` rows with an expired lease are reclaimable after a crash.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RETRY_DELAYS_SECONDS = (30.0, 60.0, 300.0, 900.0, 3600.0)
CLAIM_LEASE_SECONDS = 120.0


def idempotency_key(
    channel: str,
    chat_id: str,
    content: str,
    *,
    account: str = "",
    reply_to: str = "",
    extra: str = "",
) -> str:
    """Stable sha256 key for one logical outbound message."""
    material = "\x1f".join([channel, account, chat_id, reply_to, content, extra])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class OutboundRecord:
    id: int
    idempotency_key: str
    channel: str
    account: str
    chat_id: str
    content: str
    reply_to: str
    attachments: list[dict[str, Any]]
    metadata: dict[str, Any]
    attempts: int
    status: str
    next_retry_at: float
    last_error: str


class DeliveryQueue:
    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        from hermes_state_wal import apply_wal_with_fallback

        apply_wal_with_fallback(self._db, db_label="Atlas channel delivery")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS outbound_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    channel TEXT NOT NULL,
                    account TEXT NOT NULL DEFAULT '',
                    chat_id TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    reply_to TEXT NOT NULL DEFAULT '',
                    attachments TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at REAL NOT NULL DEFAULT 0,
                    claimed_at REAL,
                    claimed_by TEXT DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def close(self) -> None:
        self._db.close()

    # -- enqueue --------------------------------------------------------------

    def enqueue(
        self,
        channel: str,
        chat_id: str,
        content: str,
        *,
        account: str = "",
        reply_to: str = "",
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        key: str | None = None,
        now: float | None = None,
    ) -> str:
        """Queue one message; returns the idempotency key (existing one wins)."""
        now = time.time() if now is None else now
        key = key or idempotency_key(
            channel, chat_id, content, account=account, reply_to=reply_to
        )
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO outbound_messages"
                "(idempotency_key, channel, account, chat_id, content, reply_to,"
                " attachments, metadata, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    key, channel, account, chat_id, content, reply_to,
                    json.dumps(attachments or [], ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now, now,
                ),
            )
        return key

    def get(self, key: str) -> OutboundRecord | None:
        row = self._db.execute(
            "SELECT id, idempotency_key, channel, account, chat_id, content, reply_to,"
            " attachments, metadata, attempts, status, next_retry_at, last_error"
            " FROM outbound_messages WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        return self._record(row) if row else None

    # -- claim / settle --------------------------------------------------------

    def claim_due(
        self,
        limit: int = 8,
        *,
        worker_id: str = "gateway",
        lease_seconds: float = CLAIM_LEASE_SECONDS,
        channel: str | None = None,
        now: float | None = None,
    ) -> list[OutboundRecord]:
        """Claim pending rows whose ``next_retry_at`` has come (or stale leases)."""
        now = time.time() if now is None else now
        where = ("AND channel=?" if channel is not None else "")
        params: list[Any] = [now, now - lease_seconds]
        if channel is not None:
            params.append(channel)
        params.append(limit)
        rows = self._db.execute(
            "SELECT id FROM outbound_messages WHERE status IN ('pending','sending')"
            " AND next_retry_at <= ? AND (status='pending' OR claimed_at <= ?)"
            f" {where} ORDER BY id LIMIT ?",
            params,
        ).fetchall()
        claimed: list[OutboundRecord] = []
        for (row_id,) in rows:
            with self._db:
                cursor = self._db.execute(
                    "UPDATE outbound_messages SET status='sending', claimed_at=?,"
                    " claimed_by=?, attempts=attempts+1, updated_at=?"
                    " WHERE id=? AND (status='pending' OR claimed_at <= ?)",
                    (now, worker_id, now, row_id, now - lease_seconds),
                )
                if cursor.rowcount != 1:
                    continue
                row = self._db.execute(
                    "SELECT id, idempotency_key, channel, account, chat_id, content,"
                    " reply_to, attachments, metadata, attempts, status, next_retry_at,"
                    " last_error FROM outbound_messages WHERE id=?",
                    (row_id,),
                ).fetchone()
            if row is not None:
                claimed.append(self._record(row))  # type: ignore[arg-type]
        return claimed

    def mark_delivered(
        self, record_id: int, message_id: str = "", *, now: float | None = None
    ) -> bool:
        now = time.time() if now is None else now
        with self._db:
            cursor = self._db.execute(
                "UPDATE outbound_messages SET status='delivered', claimed_at=NULL,"
                " last_error='', metadata=json_set(COALESCE(metadata,'{}'), '$.message_id', ?),"
                " updated_at=? WHERE id=?",
                (message_id, now, record_id),
            )
            return cursor.rowcount == 1

    def fail(
        self,
        record_id: int,
        error: str,
        *,
        retryable: bool = True,
        now: float | None = None,
    ) -> str:
        """Record a send failure → ``"retry"`` with backoff or ``"dead"``."""
        now = time.time() if now is None else now
        with self._db:
            row = self._db.execute(
                "SELECT attempts FROM outbound_messages WHERE id=?", (record_id,)
            ).fetchone()
            if row is None:
                return "gone"
            attempts = int(row[0])
            if not retryable:
                self._db.execute(
                    "UPDATE outbound_messages SET status='dead', last_error=?,"
                    " claimed_at=NULL, updated_at=? WHERE id=?",
                    (error, now, record_id),
                )
                return "dead"
            index = min(attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)
            if attempts > len(RETRY_DELAYS_SECONDS):
                self._db.execute(
                    "UPDATE outbound_messages SET status='dead', last_error=?,"
                    " claimed_at=NULL, updated_at=? WHERE id=?",
                    (error, now, record_id),
                )
                return "dead"
            self._db.execute(
                "UPDATE outbound_messages SET status='pending', last_error=?,"
                " next_retry_at=?, claimed_at=NULL, claimed_by='', updated_at=? WHERE id=?",
                (error, now + RETRY_DELAYS_SECONDS[index], now, record_id),
            )
            return "retry"

    def mark_dead(self, record_id: int, error: str = "", *, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._db:
            cursor = self._db.execute(
                "UPDATE outbound_messages SET status='dead', last_error=?,"
                " claimed_at=NULL, updated_at=? WHERE id=?",
                (error, now, record_id),
            )
            return cursor.rowcount == 1

    # -- introspection -----------------------------------------------------------

    def list_pending(self, channel: str | None = None) -> list[OutboundRecord]:
        where, params = "", []
        if channel is not None:
            where, params = "AND channel=?", [channel]
        rows = self._db.execute(
            "SELECT id, idempotency_key, channel, account, chat_id, content, reply_to,"
            " attachments, metadata, attempts, status, next_retry_at, last_error"
            f" FROM outbound_messages WHERE status IN ('pending','sending') {where}"
            " ORDER BY id",
            params,
        ).fetchall()
        return [self._record(row) for row in rows]  # type: ignore[misc]

    def counts(self, channel: str | None = None) -> dict[str, int]:
        where, params = "", []
        if channel is not None:
            where, params = "WHERE channel=?", [channel]
        rows = self._db.execute(
            f"SELECT status, COUNT(*) FROM outbound_messages {where} GROUP BY status", params
        ).fetchall()
        return {str(status): int(count) for status, count in rows}

    @staticmethod
    def _record(row: tuple) -> OutboundRecord:
        return OutboundRecord(
            id=int(row[0]),
            idempotency_key=str(row[1]),
            channel=str(row[2]),
            account=str(row[3]),
            chat_id=str(row[4]),
            content=str(row[5]),
            reply_to=str(row[6]),
            attachments=json.loads(row[7] or "[]"),
            metadata=json.loads(row[8] or "{}"),
            attempts=int(row[9]),
            status=str(row[10]),
            next_retry_at=float(row[11]),
            last_error=str(row[12] or ""),
        )


__all__ = [
    "RETRY_DELAYS_SECONDS",
    "CLAIM_LEASE_SECONDS",
    "DeliveryQueue",
    "OutboundRecord",
    "idempotency_key",
]
