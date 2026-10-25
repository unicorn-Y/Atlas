"""Durable cross-automation run inbox with per-run read state."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from atlas.config import DATA_ROOT

_PATH = DATA_ROOT / "data" / "automation-inbox.sqlite3"
_LOCK = threading.RLock()


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _connect() -> sqlite3.Connection:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(_PATH, timeout=10, factory=_ClosingConnection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS automation_inbox (
        run_key TEXT PRIMARY KEY,
        automation_id TEXT NOT NULL,
        automation_name TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'automation',
        status TEXT NOT NULL DEFAULT 'error',
        trigger TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        result_json TEXT NOT NULL DEFAULT 'null',
        result_url TEXT NOT NULL DEFAULT '',
        conversation_id TEXT NOT NULL DEFAULT '',
        started_at TEXT NOT NULL DEFAULT '',
        finished_at TEXT NOT NULL DEFAULT '',
        read_at TEXT,
        created_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_automation_inbox_finished ON automation_inbox(finished_at DESC, run_key)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_automation_inbox_read ON automation_inbox(read_at, finished_at DESC)")
    db.commit()
    return db


def _run_fields(
    *, run_key: str, automation_id: str, automation_name: str, source: str,
    status: str, trigger: str, result: Any, error: str, conversation_id: str,
    started_at: str, finished_at: str,
) -> tuple[Any, ...]:
    result_obj = result if isinstance(result, (dict, list, str, int, float, bool)) or result is None else str(result)
    if isinstance(result_obj, str):
        summary = result_obj
    elif isinstance(result_obj, dict):
        summary = str(result_obj.get("text") or result_obj.get("stdout") or result_obj.get("summary") or "")
        conversation_id = conversation_id or str(result_obj.get("conversation_id") or "")
    else:
        summary = ""
    if error:
        summary = f"{summary}\n\n错误：{error}" if summary else error
    result_url = ""
    if isinstance(result_obj, dict):
        result_url = str(result_obj.get("result_url") or result_obj.get("artifact_url") or result_obj.get("url") or "")
    return (
        run_key, automation_id, automation_name, source, status, trigger,
        summary[:4000], json.dumps(result_obj, ensure_ascii=False, default=str)[:30_000],
        result_url[:2000], conversation_id[:128], started_at, finished_at, _now(),
    )


def record_run(record: dict[str, Any], run: dict[str, Any]) -> None:
    """Insert/update a completed execution idempotently from its DBOS step."""
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    result = run.get("result")
    conversation_id = str(run.get("conversation_id") or "")
    fields = _run_fields(
        run_key=str(run.get("run_id") or ""), automation_id=str(record.get("id") or ""),
        automation_name=str(record.get("name") or record.get("id") or ""),
        source=("heartbeat" if payload.get("kind") == "heartbeat" else "script" if payload.get("kind") == "script" else "automation"),
        status=str(run.get("status") or "error"),
        trigger=str(run.get("trigger") or ""), result=result, error=str(run.get("error") or ""),
        conversation_id=conversation_id, started_at=str(run.get("started_at") or ""),
        finished_at=str(run.get("finished_at") or ""),
    )
    if not fields[0]:
        return
    with _LOCK, _connect() as db:
        db.execute("""INSERT INTO automation_inbox (
            run_key,automation_id,automation_name,source,status,trigger,summary,result_json,result_url,
            conversation_id,started_at,finished_at,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_key) DO UPDATE SET automation_name=excluded.automation_name,
            source=excluded.source,status=excluded.status,trigger=excluded.trigger,summary=excluded.summary,
            result_json=excluded.result_json,result_url=excluded.result_url,
            conversation_id=excluded.conversation_id,started_at=excluded.started_at,
            finished_at=excluded.finished_at""", fields)


def import_run(record: dict[str, Any], run: dict[str, Any]) -> None:
    """Backfill a prior DBOS history row without replacing its read marker."""
    workflow_id = str(run.get("workflow_id") or run.get("workflow_run_id") or "")
    output = run.get("result") if isinstance(run.get("result"), dict) else {}
    run_key = str(output.get("run_id") or workflow_id)
    if not run_key:
        return
    result = output.get("result") if output else run.get("result")
    raw_status = str(output.get("status") or run.get("status") or "error").lower()
    status = {"success": "ok", "completed": "ok", "failed": "error", "cancelled": "cancelled",
              "pending": "queued", "enqueued": "queued"}.get(raw_status, raw_status)
    fields = _run_fields(
        run_key=run_key, automation_id=str(record.get("id") or ""),
        automation_name=str(record.get("name") or record.get("id") or ""),
        source=("heartbeat" if (record.get("payload") or {}).get("kind") == "heartbeat"
                else "script" if (record.get("payload") or {}).get("kind") == "script" else "automation"),
        status=status, trigger=str(output.get("trigger") or ""),
        result=result, error=str(output.get("error") or run.get("error") or ""),
        conversation_id=str(output.get("conversation_id") or (result.get("conversation_id") if isinstance(result, dict) else "") or ""),
        started_at=str(output.get("started_at") or run.get("created_at") or ""),
        finished_at=str(output.get("finished_at") or run.get("completed_at") or run.get("updated_at") or ""),
    )
    with _LOCK, _connect() as db:
        db.execute("""INSERT OR IGNORE INTO automation_inbox (
            run_key,automation_id,automation_name,source,status,trigger,summary,result_json,result_url,
            conversation_id,started_at,finished_at,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", fields)


def unread_count() -> int:
    with _LOCK, _connect() as db:
        return int(db.execute("SELECT count(*) FROM automation_inbox WHERE read_at IS NULL").fetchone()[0])


def list_runs(*, limit: int, offset: int, status: str, source: str, unread: bool) -> dict[str, Any]:
    where: list[str] = []
    values: list[Any] = []
    if status != "all":
        where.append("status=?"); values.append(status)
    if source != "all":
        where.append("source=?"); values.append(source)
    if unread:
        where.append("read_at IS NULL")
    clause = " WHERE " + " AND ".join(where) if where else ""
    with _LOCK, _connect() as db:
        total = int(db.execute("SELECT count(*) FROM automation_inbox" + clause, values).fetchone()[0])
        rows = db.execute(
            "SELECT * FROM automation_inbox" + clause + " ORDER BY finished_at DESC,run_key DESC LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
        unread_total = int(db.execute("SELECT count(*) FROM automation_inbox WHERE read_at IS NULL").fetchone()[0])
    runs = []
    for row in rows:
        try:
            result = json.loads(row["result_json"])
        except (TypeError, ValueError):
            result = None
        runs.append({key: row[key] for key in row.keys() if key != "result_json"} | {"result": result})
    return {"runs": runs, "total": total, "unread": unread_total, "limit": limit, "offset": offset,
            "next_offset": offset + len(runs) if offset + len(runs) < total else None}


def mark_read(run_ids: list[str] | None = None) -> int:
    now = _now()
    with _LOCK, _connect() as db:
        if run_ids is not None and not run_ids:
            return 0
        if run_ids is not None:
            placeholders = ",".join("?" for _ in run_ids)
            cursor = db.execute(
                f"UPDATE automation_inbox SET read_at=? WHERE read_at IS NULL AND run_key IN ({placeholders})",
                [now, *run_ids],
            )
        else:
            cursor = db.execute("UPDATE automation_inbox SET read_at=? WHERE read_at IS NULL", (now,))
        return int(cursor.rowcount)
