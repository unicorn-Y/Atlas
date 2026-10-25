"""Durable, local-only request traces and maintenance audit events."""

from __future__ import annotations

import json
import sqlite3
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
    db.execute("""CREATE TABLE IF NOT EXISTS maintenance_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
        category TEXT NOT NULL, action TEXT NOT NULL, outcome TEXT NOT NULL,
        details TEXT NOT NULL
    )""")
    db.commit()
    return db


def record_model_request(*, request_id: str, run_id: str, model: str, provider: str,
                         endpoint: str, params: dict[str, Any], started_at: str) -> None:
    with _connect() as db:
        db.execute("""INSERT OR REPLACE INTO model_request_traces
            (request_id,run_id,model,provider,endpoint,request_params,started_at,status)
            VALUES (?,?,?,?,?,?,?,'running')""",
            (request_id, run_id[:160], model[:200], provider[:120], endpoint[:300],
             json.dumps(params, ensure_ascii=False, separators=(",", ":")), started_at))


def finish_model_request(request_id: str, *, duration_ms: int, status: str,
                          error_category: str | None = None, error_detail: str | None = None) -> None:
    with _connect() as db:
        db.execute("""UPDATE model_request_traces SET duration_ms=?,status=?,error_category=?,error_detail=?
            WHERE request_id=?""",
            (max(0, duration_ms), status[:32], (error_category or "")[:80] or None,
             (error_detail or "")[:1200] or None, request_id))


def list_model_requests(query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    needle = f"%{query.strip()[:160]}%"
    with _connect() as db:
        rows = db.execute("""SELECT * FROM model_request_traces
            WHERE (?='' OR request_id LIKE ? OR run_id LIKE ? OR model LIKE ? OR provider LIKE ? OR status LIKE ? OR error_detail LIKE ?)
            ORDER BY started_at DESC LIMIT ?""",
            (query.strip(), needle, needle, needle, needle, needle, needle, max(1, min(500, limit)))).fetchall()
    return [{**dict(row), "request_params": json.loads(row["request_params"])} for row in rows]


def record_audit_event(category: str, action: str, outcome: str = "ok",
                       details: dict[str, Any] | None = None) -> None:
    with _connect() as db:
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
