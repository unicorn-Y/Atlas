"""OperationalOutbox — Atlas 侧耐久观察队列（UM02 / T02.1）.

契约来源：docs/plan/UNIFIED-MEMORY/01_contracts.md §2/§3/§8 与
02_wave_tasks.md T02.1。

设计要点：
  * **独立 sqlite 文件**（``memory.unified.outbox_path``，默认
    ``<ATLAS_DATA_DIR>/outbox/unified_outbox.sqlite3``）—— 不碰 MemoryStore
    主库 schema；第一次接收观察即持久化，进程在任何时刻退出都可恢复。
  * 状态机：NEW → SENDING → ACKED；SENDING 失败 → RETRYABLE（退避重试，
    **重试不改 source_event_id**）；永久性拒绝（409/423/422/401/403/501）→
    BLOCKED（记录错误，不重试）。``recover_leases()`` 在启动 / flush 前把
    超时 SENDING 回收为 RETRYABLE。
  * **队列不是可查询知识库** —— 本模块不提供任何召回路径；只有 flush /
    状态统计读取它。源事件 ACK 前唯一原文保留在 payload_json（§8：源事件
    ACK 前不得丢弃唯一原始内容）。
  * 同 source_event_id 二次 enqueue：同内容 → 幂等（返回已存在行）；
    不同内容 → :class:`OutboxConflict`（本地校验；服务端 409 双保险）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from atlas.memory.capture import (
    MAX_CONTENT_BYTES,
    observation_content_hash,
)

CONTRACT_VERSION = "UM-WIN-1.0"

STATE_NEW = "NEW"
STATE_SENDING = "SENDING"
STATE_ACKED = "ACKED"
STATE_RETRYABLE = "RETRYABLE"
STATE_BLOCKED = "BLOCKED"
PENDING_STATES = (STATE_NEW, STATE_RETRYABLE)
ALL_STATES = (STATE_NEW, STATE_SENDING, STATE_ACKED, STATE_RETRYABLE, STATE_BLOCKED)

DEFAULT_LEASE_SECONDS = 60.0
DEFAULT_BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 300.0
MAX_ERROR_CHARS = 500

DEFAULT_OUTBOX_FILENAME = "unified_outbox.sqlite3"


class OutboxConflict(Exception):
    """同 source_event_id 但内容不同 —— 第一次接收即持久化的身份被拒。"""

    def __init__(self, source_event_id: str, existing_hash: str,
                 incoming_hash: str) -> None:
        super().__init__(
            f"outbox conflict: {source_event_id} already stored with "
            f"{existing_hash}; refusing {incoming_hash} (retry must not change content)")
        self.source_event_id = source_event_id
        self.existing_hash = existing_hash
        self.incoming_hash = incoming_hash


def default_outbox_path() -> Path:
    """默认落点：``<ATLAS_DATA_DIR>/outbox/unified_outbox.sqlite3``。"""
    root = os.environ.get("ATLAS_DATA_DIR")
    return Path(root) / "outbox" / DEFAULT_OUTBOX_FILENAME if root else Path(
        "outbox") / DEFAULT_OUTBOX_FILENAME


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


class OperationalOutbox:
    """耐久 outbox（独立 sqlite 文件）。线程约束：单线程使用（flush 循环）。"""

    def __init__(self, path: str | Path | None = None, *,
                 lease_seconds: float = DEFAULT_LEASE_SECONDS,
                 clock: Any = time.time) -> None:
        self.path = Path(path) if path is not None else default_outbox_path()
        self._lease_seconds = float(lease_seconds)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=15)
        self._conn.row_factory = sqlite3.Row
        from hermes_state_wal import apply_wal_with_fallback

        apply_wal_with_fallback(self._conn, db_label="Atlas operational outbox")
        self._conn.execute("PRAGMA busy_timeout=15000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS outbox_events ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " source_event_id TEXT NOT NULL UNIQUE,"
            " payload_json TEXT NOT NULL,"
            " content_hash TEXT NOT NULL,"
            " state TEXT NOT NULL DEFAULT 'NEW' CHECK (state IN"
            "   ('NEW','SENDING','ACKED','RETRYABLE','BLOCKED')),"
            " attempts INTEGER NOT NULL DEFAULT 0,"
            " next_retry_at REAL,"
            " lease_expires_at REAL,"
            " last_error TEXT,"
            " created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL,"
            " acked_at TEXT)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_events_state"
            " ON outbox_events(state, next_retry_at)")
        # Observer-only operational metadata lives beside captured events. Queue
        # rows contain source IDs and fragment offsets only; original capture text
        # remains solely in outbox_events.payload_json.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS observer_sessions ("
            " session_id TEXT PRIMARY KEY,"
            " flush_requested INTEGER NOT NULL DEFAULT 0,"
            " updated_at TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS observer_queue ("
            " queue_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " session_id TEXT NOT NULL,"
            " source_event_id TEXT NOT NULL,"
            " part_index INTEGER NOT NULL DEFAULT 1,"
            " part_count INTEGER NOT NULL DEFAULT 1,"
            " source_view_json TEXT NOT NULL DEFAULT '{}',"
            " created_at TEXT NOT NULL,"
            " UNIQUE(session_id, source_event_id, part_index))"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_observer_queue_session"
            " ON observer_queue(session_id, queue_id)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS observer_source_watermarks ("
            " source_event_id TEXT PRIMARY KEY,"
            " session_id TEXT NOT NULL,"
            " status TEXT NOT NULL CHECK(status IN ('QUEUED','DELIVERED'))," 
            " updated_at TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_observer_watermark_session"
            " ON observer_source_watermarks(session_id, status)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS observer_batches ("
            " batch_id TEXT PRIMARY KEY,"
            " session_id TEXT NOT NULL,"
            " source_event_ids_json TEXT NOT NULL,"
            " queue_ids_json TEXT NOT NULL,"
            " payload_json TEXT NOT NULL,"
            " raw_output TEXT NOT NULL,"
            " model_id TEXT NOT NULL,"
            " input_tokens INTEGER NOT NULL DEFAULT 0,"
            " output_tokens INTEGER NOT NULL DEFAULT 0,"
            " status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','ACKED'))," 
            " created_at TEXT NOT NULL,"
            " acked_at TEXT)"
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_observer_batch_one_pending"
            " ON observer_batches(session_id) WHERE status = 'PENDING'"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS observer_daily_usage ("
            " usage_day TEXT PRIMARY KEY,"
            " spent_tokens INTEGER NOT NULL DEFAULT 0,"
            " reserved_tokens INTEGER NOT NULL DEFAULT 0)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS observer_token_reservations ("
            " reservation_id TEXT PRIMARY KEY,"
            " usage_day TEXT NOT NULL,"
            " token_count INTEGER NOT NULL)"
        )
        self._conn.commit()

    # ------------------------------------------------------------------ Observer durable state

    def observer_enqueue_sources(
        self, session_id: str, refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Queue references to ACKED capture rows without copying their source text.

        ``refs`` contains ``source_event_id``, ``part_index`` and ``part_count``;
        fragments are regenerated from the original capture payload after restart.
        """
        session = str(session_id or "").strip()
        if not session:
            raise ValueError("observer session_id is required")
        normalized: list[tuple[str, int, int, str]] = []
        for ref in refs:
            source_id = str(ref.get("source_event_id") or "").strip()
            part_index = int(ref.get("part_index", 1))
            part_count = int(ref.get("part_count", 1))
            if not source_id or part_count < 1 or not 1 <= part_index <= part_count:
                raise ValueError("invalid observer source reference")
            source_view = {key: ref.get(key) for key in (
                "speaker_role", "epistemic_kind", "source_kind", "source_object_id",
                "source_revision", "occurred_at", "source_timezone", "provenance",
            )}
            normalized.append((source_id, part_index, part_count,
                               json.dumps(source_view, ensure_ascii=False, sort_keys=True)))

        now = _utc_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            for source_id in dict.fromkeys(ref[0] for ref in normalized):
                row = self._conn.execute(
                    "SELECT state FROM outbox_events WHERE source_event_id = ?",
                    (source_id,),
                ).fetchone()
                if row is None or row["state"] != STATE_ACKED:
                    raise ValueError("observer source is not a captured ACKED outbox event")
            self._conn.execute(
                "INSERT INTO observer_sessions(session_id, flush_requested, updated_at)"
                " VALUES(?, 0, ?) ON CONFLICT(session_id) DO UPDATE SET updated_at=excluded.updated_at",
                (session, now),
            )
            for source_id, part_index, part_count, source_view_json in normalized:
                watermark = self._conn.execute(
                    "SELECT session_id,status FROM observer_source_watermarks"
                    " WHERE source_event_id=?", (source_id,),
                ).fetchone()
                if watermark is not None and str(watermark["session_id"]) != session:
                    raise ValueError("Observer source ID is already assigned to another session")
                if watermark is not None and watermark["status"] == "DELIVERED":
                    continue
                existing = self._conn.execute(
                    "SELECT part_count,source_view_json FROM observer_queue WHERE session_id=?"
                    " AND source_event_id=? LIMIT 1", (session, source_id),
                ).fetchone()
                if existing is not None and int(existing["part_count"]) != part_count:
                    raise ValueError("observer source fragment layout changed during retry")
                if existing is not None and str(existing["source_view_json"]) != source_view_json:
                    raise ValueError("observer source provenance changed during retry")
                self._conn.execute(
                    "INSERT OR IGNORE INTO observer_queue(session_id, source_event_id,"
                    " part_index, part_count, source_view_json, created_at) VALUES(?,?,?,?,?,?)",
                    (session, source_id, part_index, part_count, source_view_json, now),
                )
                self._conn.execute(
                    "INSERT INTO observer_source_watermarks(source_event_id,session_id,status,updated_at)"
                    " VALUES(?,?,'QUEUED',?) ON CONFLICT(source_event_id) DO UPDATE SET"
                    " status='QUEUED', updated_at=excluded.updated_at",
                    (source_id, session, now),
                )
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return self.observer_queue_sources(session)

    def observer_queue_sources(self, session_id: str) -> list[dict[str, Any]]:
        """Return ordered fragment references joined to their original ACKED payloads."""
        rows = self._conn.execute(
            "SELECT q.queue_id, q.session_id, q.source_event_id, q.part_index, q.part_count,"
            " q.source_view_json,"
            " e.payload_json, e.state FROM observer_queue q"
            " JOIN outbox_events e ON e.source_event_id=q.source_event_id"
            " WHERE q.session_id=? ORDER BY q.queue_id", (str(session_id),),
        ).fetchall()
        result = []
        for row in rows:
            if row["state"] != STATE_ACKED:
                continue
            data = dict(row)
            data["payload"] = json.loads(data.pop("payload_json"))
            data["source_view"] = json.loads(data.pop("source_view_json"))
            result.append(data)
        return result

    def observer_source(self, source_event_id: str) -> dict[str, Any] | None:
        """Get an original capture row only when its HTTP event was ACKED."""
        row = self._conn.execute(
            "SELECT * FROM outbox_events WHERE source_event_id=? AND state=?",
            (str(source_event_id), STATE_ACKED),
        ).fetchone()
        return self._row_as_dict(row) if row is not None else None

    def observer_pending_sessions(self) -> list[str]:
        sessions = {str(row["session_id"]) for row in self._conn.execute(
            "SELECT DISTINCT session_id FROM observer_queue"
        ).fetchall()}
        sessions.update(str(row["session_id"])
                        for row in self.observer_unprocessed_sources())
        return sorted(sessions)

    def observer_unprocessed_sources(
        self, session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Recover ACKED capture rows lost between capture ack and Observer enqueue."""
        rows = self._conn.execute(
            "SELECT e.* FROM outbox_events e LEFT JOIN observer_source_watermarks w"
            " ON w.source_event_id=e.source_event_id WHERE e.state=? AND w.source_event_id IS NULL"
            " ORDER BY e.id", (STATE_ACKED,),
        ).fetchall()
        pending: list[dict[str, Any]] = []
        for row in rows:
            data = self._row_as_dict(row)
            envelope = data.get("payload") or {}
            observation = envelope.get("observation") or {}
            if not observation or str(observation.get("source_kind") or "") == "DERIVED":
                continue
            context = envelope.get("context") or {}
            content = observation.get("content") or {}
            actual_session = str(
                context.get("runtime_session_id") or context.get("session_id")
                or content.get("session_id") or ""
            ).strip()
            if not actual_session or (session_id is not None and actual_session != str(session_id)):
                continue
            data["session_id"] = actual_session
            pending.append(data)
        return pending

    def observer_set_flush_requested(self, session_id: str, requested: bool = True) -> None:
        now = _utc_iso()
        self._conn.execute(
            "INSERT INTO observer_sessions(session_id, flush_requested, updated_at)"
            " VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET"
            " flush_requested=excluded.flush_requested, updated_at=excluded.updated_at",
            (str(session_id), int(bool(requested)), now),
        )
        self._conn.commit()

    def observer_mark_session_ended(self, session_id: str) -> None:
        """Persist an end marker synchronously before asynchronous drain begins."""
        session = str(session_id or "").strip()
        if not session:
            raise ValueError("observer session_id is required")
        self.observer_set_flush_requested(session, True)

    def observer_flush_requested(self, session_id: str) -> bool:
        row = self._conn.execute(
            "SELECT flush_requested FROM observer_sessions WHERE session_id=?",
            (str(session_id),),
        ).fetchone()
        return bool(row["flush_requested"]) if row is not None else False

    def observer_store_batch(
        self, *, batch_id: str, session_id: str, source_event_ids: list[str],
        queue_ids: list[int | str], payload: dict[str, Any] | None,
        raw_output: str, model_id: str, input_tokens: int, output_tokens: int,
    ) -> dict[str, Any]:
        """Durably store one model result until the caller confirms MemoryOS HTTP ack."""
        normalized_queue_ids = [int(value) for value in queue_ids]
        now = _utc_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT batch_id FROM observer_batches WHERE session_id=? AND status='PENDING'",
                (str(session_id),),
            ).fetchone()
            if existing is not None:
                if str(existing["batch_id"]) == str(batch_id):
                    self._conn.commit()
                    return self.observer_pending_batch(session_id)  # type: ignore[return-value]
                raise ValueError("an Observer batch is already awaiting HTTP acknowledgement")
            queued = self._conn.execute(
                "SELECT count(*) AS c FROM observer_queue WHERE session_id=? AND queue_id IN ("
                + ",".join("?" for _ in normalized_queue_ids) + ")",
                (str(session_id), *normalized_queue_ids),
            ).fetchone() if normalized_queue_ids else None
            if queued is None or int(queued["c"]) != len(set(normalized_queue_ids)):
                raise ValueError("Observer batch references missing durable queue rows")
            self._conn.execute(
                "INSERT INTO observer_batches(batch_id,session_id,source_event_ids_json,"
                " queue_ids_json,payload_json,raw_output,model_id,input_tokens,output_tokens,"
                " status,created_at) VALUES(?,?,?,?,?,?,?,?,?,'PENDING',?)",
                (str(batch_id), str(session_id), json.dumps(list(dict.fromkeys(source_event_ids))),
                 json.dumps(normalized_queue_ids), json.dumps(payload, ensure_ascii=False),
                 str(raw_output), str(model_id), max(0, int(input_tokens)),
                 max(0, int(output_tokens)), now),
            )
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return self.observer_pending_batch(session_id)  # type: ignore[return-value]

    def observer_pending_batch(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM observer_batches WHERE session_id=? AND status='PENDING'",
            (str(session_id),),
        ).fetchone()
        return self._observer_batch_dict(row) if row is not None else None

    def observer_get_batch(self, batch_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM observer_batches WHERE batch_id=?", (str(batch_id),),
        ).fetchone()
        return self._observer_batch_dict(row) if row is not None else None

    def observer_ack_batch(self, batch_id: str) -> dict[str, Any] | None:
        """Mark successful HTTP delivery and consume precisely its source fragments."""
        now = _utc_iso()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT * FROM observer_batches WHERE batch_id=?", (str(batch_id),),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown Observer batch {batch_id}")
            if row["status"] == "ACKED":
                self._conn.commit()
                return None
            queue_ids = json.loads(row["queue_ids_json"])
            if queue_ids:
                self._conn.execute(
                    "DELETE FROM observer_queue WHERE session_id=? AND queue_id IN ("
                    + ",".join("?" for _ in queue_ids) + ")",
                    (row["session_id"], *[int(value) for value in queue_ids]),
                )
            source_event_ids = json.loads(row["source_event_ids_json"])
            for source_id in source_event_ids:
                remaining_source_refs = self._conn.execute(
                    "SELECT count(*) AS c FROM observer_queue WHERE session_id=? AND source_event_id=?",
                    (row["session_id"], str(source_id)),
                ).fetchone()
                if not remaining_source_refs or int(remaining_source_refs["c"]) == 0:
                    self._conn.execute(
                        "UPDATE observer_source_watermarks SET status='DELIVERED',updated_at=?"
                        " WHERE source_event_id=? AND session_id=?",
                        (now, str(source_id), row["session_id"]),
                    )
            self._conn.execute(
                "UPDATE observer_batches SET status='ACKED', acked_at=? WHERE batch_id=?",
                (now, str(batch_id)),
            )
            remaining = self._conn.execute(
                "SELECT count(*) AS c FROM observer_queue WHERE session_id=?",
                (row["session_id"],),
            ).fetchone()
            if not remaining or int(remaining["c"]) == 0:
                self._conn.execute(
                    "DELETE FROM observer_sessions WHERE session_id=?", (row["session_id"],),
                )
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return self.observer_pending_batch(str(row["session_id"]))

    def observer_budget_snapshot(self, usage_day: str) -> dict[str, int]:
        row = self._conn.execute(
            "SELECT spent_tokens,reserved_tokens FROM observer_daily_usage WHERE usage_day=?",
            (str(usage_day),),
        ).fetchone()
        if row is None:
            return {"spent": 0, "reserved": 0}
        return {"spent": int(row["spent_tokens"]),
                "reserved": int(row["reserved_tokens"])}

    def observer_budget_reserve(
        self, usage_day: str, budget: int, reservation_id: str, token_count: int,
    ) -> bool:
        """Reserve daily Observer tokens transactionally across sessions/process restarts."""
        amount = max(0, int(token_count))
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO observer_daily_usage(usage_day) VALUES(?)",
                (str(usage_day),),
            )
            row = self._conn.execute(
                "SELECT spent_tokens,reserved_tokens FROM observer_daily_usage WHERE usage_day=?",
                (str(usage_day),),
            ).fetchone()
            existing = self._conn.execute(
                "SELECT usage_day,token_count FROM observer_token_reservations WHERE reservation_id=?",
                (str(reservation_id),),
            ).fetchone()
            if existing is not None:
                ok = (str(existing["usage_day"]) == str(usage_day)
                      and int(existing["token_count"]) == amount)
                self._conn.commit()
                return ok
            if int(row["spent_tokens"]) + int(row["reserved_tokens"]) + amount > max(0, int(budget)):
                self._conn.commit()
                return False
            self._conn.execute(
                "INSERT INTO observer_token_reservations(reservation_id,usage_day,token_count)"
                " VALUES(?,?,?)", (str(reservation_id), str(usage_day), amount),
            )
            self._conn.execute(
                "UPDATE observer_daily_usage SET reserved_tokens=reserved_tokens+? WHERE usage_day=?",
                (amount, str(usage_day)),
            )
            self._conn.commit()
            return True
        except BaseException:
            self._conn.rollback()
            raise

    def observer_budget_commit(self, reservation_id: str, actual_tokens: int) -> bool:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT usage_day,token_count FROM observer_token_reservations WHERE reservation_id=?",
                (str(reservation_id),),
            ).fetchone()
            if row is None:
                self._conn.commit()
                return False
            self._conn.execute(
                "UPDATE observer_daily_usage SET reserved_tokens=max(0,reserved_tokens-?),"
                " spent_tokens=spent_tokens+? WHERE usage_day=?",
                (int(row["token_count"]), max(0, int(actual_tokens)), str(row["usage_day"])),
            )
            self._conn.execute(
                "DELETE FROM observer_token_reservations WHERE reservation_id=?",
                (str(reservation_id),),
            )
            self._conn.commit()
            return True
        except BaseException:
            self._conn.rollback()
            raise

    def observer_budget_release(self, reservation_id: str) -> bool:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT usage_day,token_count FROM observer_token_reservations WHERE reservation_id=?",
                (str(reservation_id),),
            ).fetchone()
            if row is None:
                self._conn.commit()
                return False
            self._conn.execute(
                "UPDATE observer_daily_usage SET reserved_tokens=max(0,reserved_tokens-?)"
                " WHERE usage_day=?", (int(row["token_count"]), str(row["usage_day"])),
            )
            self._conn.execute(
                "DELETE FROM observer_token_reservations WHERE reservation_id=?",
                (str(reservation_id),),
            )
            self._conn.commit()
            return True
        except BaseException:
            self._conn.rollback()
            raise

    @staticmethod
    def _observer_batch_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["source_event_ids"] = json.loads(data.pop("source_event_ids_json"))
        data["queue_ids"] = json.loads(data.pop("queue_ids_json"))
        data["payload"] = json.loads(data.pop("payload_json"))
        return data

    # ------------------------------------------------------------------ 写入

    def enqueue(self, observation: dict[str, Any], *, context: dict[str, Any] | None = None,
                event_class: str = "PRODUCTION") -> dict[str, Any]:
        """第一次接收即持久化，返回稳定 id（source_event_id 不随重试改变）。

        payload_json 持久化 ``{observation, context, event_class}`` —— 重启后
        flush 的请求体逐字节稳定，服务端幂等才有确定输入。
        """
        source_event_id = str(observation.get("source_event_id") or "").strip()
        if not source_event_id:
            raise ValueError("observation.source_event_id 必填（outbox 稳定 id）")
        # 身份哈希一律**本地重算**（与 MemoryOS 服务端同一规则：不轻信传输哈希
        # —— 同 ID 改内容即使带着旧哈希也在本地即被拒，重试必然同内容）。
        content_hash = observation_content_hash(observation)
        size = len(json.dumps(observation.get("content") or {}, ensure_ascii=False,
                              sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if size > MAX_CONTENT_BYTES:
            # 本地显式拒绝（§2 超限）；不静默截断，媒体路径 UM05 接入
            raise ValueError(
                f"CONTENT_TOO_LARGE: normalized content is {size} bytes "
                f"(limit {MAX_CONTENT_BYTES}); media must be submitted separately")
        now = _utc_iso()
        payload = json.dumps(
            {"observation": observation, "context": context,
             "event_class": event_class or "PRODUCTION"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        existing = self._conn.execute(
            "SELECT id, content_hash, state FROM outbox_events"
            " WHERE source_event_id = ?", (source_event_id,)).fetchone()
        if existing is not None:
            if existing["content_hash"] != content_hash:
                raise OutboxConflict(source_event_id, existing["content_hash"],
                                     content_hash)
            return {"id": int(existing["id"]), "source_event_id": source_event_id,
                    "state": existing["state"], "created": False}
        cursor = self._conn.execute(
            "INSERT INTO outbox_events (source_event_id, payload_json, content_hash,"
            " state, attempts, created_at, updated_at)"
            " VALUES (?,?,?,?,0,?,?)",
            (source_event_id, payload, content_hash, STATE_NEW, now, now))
        self._conn.commit()
        return {"id": int(cursor.lastrowid), "source_event_id": source_event_id,
                "state": STATE_NEW, "created": True}

    # ------------------------------------------------------------------ 领取

    def poll_pending(self, limit: int = 50) -> list[dict[str, Any]]:
        """到期 NEW/RETRYABLE 行 → SENDING（lease 起算，attempts+1）。"""
        now = self._clock()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            rows = self._conn.execute(
                "SELECT * FROM outbox_events WHERE state IN (?,?)"
                "   AND (next_retry_at IS NULL OR next_retry_at <= ?)"
                " ORDER BY id LIMIT ?",
                (STATE_NEW, STATE_RETRYABLE, now, int(limit))).fetchall()
            polled: list[dict[str, Any]] = []
            for row in rows:
                self._conn.execute(
                    "UPDATE outbox_events SET state = ?, attempts = attempts + 1,"
                    " lease_expires_at = ?, updated_at = ? WHERE id = ?",
                    (STATE_SENDING, now + self._lease_seconds, _utc_iso(), row["id"]))
                polled.append(self._row_as_dict(row, overrides={
                    "state": STATE_SENDING,
                    "attempts": int(row["attempts"]) + 1,
                }))
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return polled

    # ------------------------------------------------------------------ 状态迁移

    def mark_acked(self, source_event_id: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE outbox_events SET state = ?, acked_at = ?, lease_expires_at = NULL,"
            " next_retry_at = NULL, updated_at = ?"
            " WHERE source_event_id = ? AND state = ?",
            (STATE_ACKED, _utc_iso(), _utc_iso(), source_event_id, STATE_SENDING))
        self._conn.commit()
        return cursor.rowcount > 0

    def mark_retryable(self, source_event_id: str, error: str,
                       backoff_seconds: float) -> bool:
        backoff = max(0.0, float(backoff_seconds))
        cursor = self._conn.execute(
            "UPDATE outbox_events SET state = ?, last_error = ?,"
            " next_retry_at = ?, lease_expires_at = NULL, updated_at = ?"
            " WHERE source_event_id = ? AND state = ?",
            (STATE_RETRYABLE, str(error)[:MAX_ERROR_CHARS],
             self._clock() + backoff, _utc_iso(), source_event_id, STATE_SENDING))
        self._conn.commit()
        return cursor.rowcount > 0

    def mark_blocked(self, source_event_id: str, reason: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE outbox_events SET state = ?, last_error = ?,"
            " next_retry_at = NULL, lease_expires_at = NULL, updated_at = ?"
            " WHERE source_event_id = ? AND state IN (?,?,?)",
            (STATE_BLOCKED, str(reason)[:MAX_ERROR_CHARS], _utc_iso(),
             source_event_id, STATE_NEW, STATE_SENDING, STATE_RETRYABLE))
        self._conn.commit()
        return cursor.rowcount > 0

    def recover_leases(self) -> int:
        """启动 / flush 前回收：超时（或无 lease）SENDING → RETRYABLE 立即可重试。"""
        now = self._clock()
        cursor = self._conn.execute(
            "UPDATE outbox_events SET state = ?, last_error = 'LEASE_RECOVERED',"
            " next_retry_at = ?, lease_expires_at = NULL, updated_at = ?"
            " WHERE state = ? AND (lease_expires_at IS NULL OR lease_expires_at <= ?)",
            (STATE_RETRYABLE, now, _utc_iso(), STATE_SENDING, now))
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------ 读取

    def get(self, source_event_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM outbox_events WHERE source_event_id = ?",
            (source_event_id,)).fetchone()
        return self._row_as_dict(row) if row is not None else None

    def stats(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT state, count(*) AS c FROM outbox_events GROUP BY state").fetchall()
        counts = {row["state"]: int(row["c"]) for row in rows}
        return {
            "total": sum(counts.values()),
            "new": counts.get(STATE_NEW, 0),
            "sending": counts.get(STATE_SENDING, 0),
            "acked": counts.get(STATE_ACKED, 0),
            "retryable": counts.get(STATE_RETRYABLE, 0),
            "blocked": counts.get(STATE_BLOCKED, 0),
            "pending": counts.get(STATE_NEW, 0) + counts.get(STATE_RETRYABLE, 0),
            "note": "operational outbox 不是可查询知识库；仅供 flush 与诊断",
        }

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:  # pragma: no cover
            pass

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _row_as_dict(row: sqlite3.Row, overrides: dict[str, Any] | None = None
                     ) -> dict[str, Any]:
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        if overrides:
            data.update(overrides)
        return data


# ------------------------------------------------------------------ flush

async def flush_once(outbox: OperationalOutbox, facade: Any, *,
                     limit: int = 50, backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
                     max_backoff_seconds: float = MAX_BACKOFF_SECONDS) -> dict[str, Any]:
    """把 outbox 中的到期观察逐条 POST /v1/unified/observe（T02.1 状态机）。

    * ack（2xx）→ ACKED；
    * 409 / 423（以及 422 契约违规、401/403 凭据、501 路由未接线）→ BLOCKED
      （记录错误，不重试 —— 重试必然得到同样结果）；
    * 网络 / 超时 / 5xx → RETRYABLE 指数退避（``backoff * 2^(attempts-1)``，
      封顶 ``max_backoff_seconds``）；同 source_event_id 重试不改 ID。
    """
    from atlas.memory.unified_client import (
        ContractViolation,
        ErasureBlocked,
        FeatureNotReady,
        ForbiddenSubject,
        RevisionConflict,
        ServiceUnavailable,
        UnauthorizedError,
        UnifiedMemoryError,
    )

    outbox.recover_leases()
    rows = outbox.poll_pending(limit)
    results: list[dict[str, Any]] = []
    counts = {"sent": len(rows), "acked": 0, "blocked": 0, "retryable": 0}
    for row in rows:
        payload = row["payload"]
        observation = payload.get("observation") or {}
        batch = {
            "contract_version": CONTRACT_VERSION,
            "event_class": payload.get("event_class") or "PRODUCTION",
            "context": payload.get("context") or facade.default_context(),
            "observations": [observation],
        }
        source_event_id = row["source_event_id"]
        try:
            await facade.observe_batch(batch)
        except (RevisionConflict, ErasureBlocked, ContractViolation,
                ForbiddenSubject, UnauthorizedError, FeatureNotReady) as exc:
            outbox.mark_blocked(source_event_id, f"{type(exc).__name__}: {exc}")
            counts["blocked"] += 1
            results.append({"source_event_id": source_event_id,
                            "state": STATE_BLOCKED, "error": str(exc)})
            continue
        except ServiceUnavailable as exc:
            backoff = min(backoff_seconds * (2 ** max(0, row["attempts"] - 1)),
                          max_backoff_seconds)
            outbox.mark_retryable(source_event_id, str(exc), backoff)
            counts["retryable"] += 1
            results.append({"source_event_id": source_event_id,
                            "state": STATE_RETRYABLE,
                            "retry_in_seconds": backoff, "error": str(exc)})
            continue
        except UnifiedMemoryError as exc:  # 410/423 或 SOURCE_BARRIERED/RECORD_ERASED → BLOCKED；其余受控错误保守重试
            if getattr(exc, "status_code", None) in (409, 410, 422, 423, 401, 403, 501) or getattr(
                exc, "code", None
            ) in (
                "ERASURE_BARRIER_ACTIVE",
                "SOURCE_BARRIERED",
                "SOURCE_DELETED",
                "RECORD_ERASED",
                "EVIDENCE_GONE",
                "MEDIA_GONE",
            ):
                outbox.mark_blocked(source_event_id, f"{type(exc).__name__}: {exc}")
                counts["blocked"] += 1
                results.append({"source_event_id": source_event_id,
                                "state": STATE_BLOCKED, "error": str(exc)})
                continue
            backoff = min(backoff_seconds * (2 ** max(0, row["attempts"] - 1)),
                          max_backoff_seconds)
            outbox.mark_retryable(source_event_id, str(exc), backoff)
            counts["retryable"] += 1
            results.append({"source_event_id": source_event_id,
                            "state": STATE_RETRYABLE,
                            "retry_in_seconds": backoff, "error": str(exc)})
            continue
        outbox.mark_acked(source_event_id)
        counts["acked"] += 1
        results.append({"source_event_id": source_event_id, "state": STATE_ACKED})
    return {**counts, "results": results,
            "outbox": outbox.stats(),
            "note": "队列不是可查询知识库；本函数是唯一消费路径（T02.2 起由采集控制器驱动）"}
