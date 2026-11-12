"""Durable, local-only request traces and maintenance audit events."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT


def _path() -> Path:
    return DATA_ROOT / "data" / "diagnostics.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS model_request_traces (
        request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, model TEXT NOT NULL,
        provider TEXT NOT NULL, endpoint TEXT NOT NULL, request_params TEXT NOT NULL,
        started_at TEXT NOT NULL, duration_ms INTEGER, status TEXT NOT NULL,
        error_category TEXT, error_detail TEXT
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_model_trace_started ON model_request_traces(started_at)")
    db.execute("""CREATE TABLE IF NOT EXISTS tool_call_traces (
        call_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tool_name TEXT NOT NULL,
        family TEXT, tier TEXT, started_at TEXT NOT NULL, duration_ms INTEGER,
        status TEXT NOT NULL, is_error INTEGER NOT NULL DEFAULT 0,
        arguments_chars INTEGER, result_chars INTEGER, error_detail TEXT
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tool_trace_started ON tool_call_traces(started_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tool_trace_run ON tool_call_traces(run_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS maintenance_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
        category TEXT NOT NULL, action TEXT NOT NULL, outcome TEXT NOT NULL,
        details TEXT NOT NULL
    )""")
    db.commit()
    return db


def record_model_request(*, request_id: str, run_id: str, model: str, provider: str,
                         endpoint: str, params: dict[str, Any], started_at: str) -> None:
    with closing(_connect()) as db, db:
        db.execute("""INSERT OR REPLACE INTO model_request_traces
            (request_id,run_id,model,provider,endpoint,request_params,started_at,status)
            VALUES (?,?,?,?,?,?,?,'running')""",
            (request_id, run_id[:160], model[:200], provider[:120], endpoint[:300],
             json.dumps(params, ensure_ascii=False, separators=(",", ":")), started_at))


def finish_model_request(request_id: str, *, duration_ms: int, status: str,
                          error_category: str | None = None, error_detail: str | None = None) -> None:
    with closing(_connect()) as db, db:
        db.execute("""UPDATE model_request_traces SET duration_ms=?,status=?,error_category=?,error_detail=?
            WHERE request_id=?""",
            (max(0, duration_ms), status[:32], (error_category or "")[:80] or None,
             (error_detail or "")[:1200] or None, request_id))


def list_model_requests(query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    needle = f"%{query.strip()[:160]}%"
    with closing(_connect()) as db, db:
        rows = db.execute("""SELECT * FROM model_request_traces
            WHERE (?='' OR request_id LIKE ? OR run_id LIKE ? OR model LIKE ? OR provider LIKE ? OR status LIKE ? OR error_detail LIKE ?)
            ORDER BY started_at DESC LIMIT ?""",
            (query.strip(), needle, needle, needle, needle, needle, needle, max(1, min(500, limit)))).fetchall()
    return [{**dict(row), "request_params": json.loads(row["request_params"])} for row in rows]


def record_tool_call(*, call_id: str, run_id: str, tool_name: str, family: str = "",
                     tier: str = "", started_at: str, arguments_chars: int = 0) -> None:
    """Open one tool-call trace row, keyed to the same ``run_id`` as model traces.

    Model requests and tool calls share ``run_id``, so a single run can be read
    back end to end without inventing a parallel trace id.
    """
    with closing(_connect()) as db, db:
        db.execute("""INSERT OR REPLACE INTO tool_call_traces
            (call_id,run_id,tool_name,family,tier,started_at,status,is_error,arguments_chars)
            VALUES (?,?,?,?,?,?,'running',0,?)""",
            (call_id[:160], run_id[:160], tool_name[:200], family[:80] or None,
             tier[:40] or None, started_at, max(0, int(arguments_chars))))


def finish_tool_call(call_id: str, *, duration_ms: int, is_error: bool = False,
                     result_chars: int = 0, error_detail: str | None = None) -> None:
    with closing(_connect()) as db, db:
        db.execute("""UPDATE tool_call_traces SET duration_ms=?,status=?,is_error=?,
            result_chars=?,error_detail=? WHERE call_id=?""",
            (max(0, duration_ms), "error" if is_error else "ok", 1 if is_error else 0,
             max(0, int(result_chars)), (error_detail or "")[:1200] or None, call_id[:160]))


def list_tool_calls(query: str = "", limit: int = 100,
                    run_id: str = "") -> list[dict[str, Any]]:
    needle = f"%{query.strip()[:160]}%"
    with closing(_connect()) as db:
        rows = db.execute("""SELECT * FROM tool_call_traces
            WHERE (?='' OR run_id=?)
              AND (?='' OR call_id LIKE ? OR run_id LIKE ? OR tool_name LIKE ?
                   OR family LIKE ? OR status LIKE ? OR error_detail LIKE ?)
            ORDER BY started_at DESC LIMIT ?""",
            (run_id.strip(), run_id.strip(), query.strip(), needle, needle, needle,
             needle, needle, needle, max(1, min(500, limit)))).fetchall()
    return [dict(row) for row in rows]


def record_audit_event(category: str, action: str, outcome: str = "ok",
                       details: dict[str, Any] | None = None) -> None:
    with closing(_connect()) as db, db:
        db.execute("INSERT INTO maintenance_audit(created_at,category,action,outcome,details) VALUES(?,?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), category[:80], action[:160], outcome[:32],
                    json.dumps(details or {}, ensure_ascii=False, separators=(",", ":"))[:4000]))


def list_audit_events(query: str = "", limit: int = 200) -> list[dict[str, Any]]:
    needle = f"%{query.strip()[:160]}%"
    with _connect() as db:
        rows = db.execute("""SELECT * FROM maintenance_audit
            WHERE (?='' OR category LIKE ? OR action LIKE ? OR outcome LIKE ? OR details LIKE ?)
            ORDER BY id DESC LIMIT ?""",
            (query.strip(), needle, needle, needle, needle, max(1, min(500, limit)))).fetchall()
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]
