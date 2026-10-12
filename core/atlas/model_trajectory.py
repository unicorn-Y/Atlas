"""Persistent per-request model usage records for trajectory inspection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


class ModelTrajectoryStore:
    """Persist observed model calls and provide conversation-scoped filtering."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS model_trajectory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                model TEXT NOT NULL,
                source TEXT NOT NULL,
                call_type TEXT NOT NULL,
                subtask_id TEXT,
                usage_available INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cached_input_tokens INTEGER,
                cache_write_tokens INTEGER,
                details_json TEXT NOT NULL,
                UNIQUE(run_id, request_id)
            )
        """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_model_trajectory_conversation "
            "ON model_trajectory(conversation_id, occurred_at DESC, id DESC)"
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def record(
        self, *, run_id: str, conversation_id: str, usage: dict[str, Any],
    ) -> None:
        if self._db is None:
            return
        request_id = str(usage.get("request_id") or "").strip()
        if not request_id or usage.get("request_sent") is False:
            return
        call_type = str(usage.get("purpose") or "conversation").strip() or "conversation"
        default_source = "subagent" if usage.get("subtask_id") else "run"
        source = str(usage.get("source") or usage.get("origin") or default_source).strip() or default_source
        timestamp = datetime.now(timezone.utc).isoformat()
        values = {
            "input_tokens": _optional_nonnegative_int(usage.get("input_tokens")),
            "output_tokens": _optional_nonnegative_int(usage.get("output_tokens")),
            "cached_input_tokens": _optional_nonnegative_int(usage.get("cached_input_tokens")),
            "cache_write_tokens": _optional_nonnegative_int(usage.get("cache_write_tokens")),
        }
        available = usage.get("usage_available")
        details = {
            key: usage[key] for key in (
                "provider", "wire_model", "purpose", "duration_ms", "context_tokens",
                "reasoning_effort_applied", "estimated_input_tokens", "request_sent",
                "cached_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
            ) if key in usage
        }
        await self._db.execute("""
            INSERT INTO model_trajectory (
                request_id, run_id, conversation_id, occurred_at, model, source,
                call_type, subtask_id, usage_available, input_tokens,
                output_tokens, cached_input_tokens, cache_write_tokens, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, request_id) DO UPDATE SET
                model=excluded.model, source=excluded.source,
                call_type=excluded.call_type, subtask_id=excluded.subtask_id,
                usage_available=excluded.usage_available,
                input_tokens=excluded.input_tokens,
                output_tokens=excluded.output_tokens,
                cached_input_tokens=excluded.cached_input_tokens,
                cache_write_tokens=excluded.cache_write_tokens,
                details_json=excluded.details_json
        """, (
            request_id, run_id, conversation_id, timestamp,
            str(usage.get("model") or usage.get("wire_model") or "unknown"),
            source, call_type, usage.get("subtask_id"),
            None if available is None else int(bool(available)),
            values["input_tokens"], values["output_tokens"],
            values["cached_input_tokens"], values["cache_write_tokens"],
            json.dumps(details, ensure_ascii=False, separators=(",", ":")),
        ))
        await self._db.commit()

    async def search(
        self, conversation_id: str, *, query: str = "", source: str = "",
        call_type: str = "", limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        if self._db is None:
            raise RuntimeError("model trajectory store is not initialized")
        clauses = ["conversation_id = ?"]
        params: list[Any] = [conversation_id]
        if source:
            clauses.append("source = ?")
            params.append(source)
        if call_type:
            clauses.append("call_type = ?")
            params.append(call_type)
        if query.strip():
            like = f"%{query.strip()}%"
            clauses.append("(model LIKE ? OR source LIKE ? OR call_type LIKE ? OR "
                           "request_id LIKE ? OR run_id LIKE ? OR subtask_id LIKE ? OR details_json LIKE ?)")
            params.extend([like] * 7)
        where = " AND ".join(clauses)
        total_cursor = await self._db.execute(
            f"SELECT COUNT(*) FROM model_trajectory WHERE {where}", params,
        )
        total = int((await total_cursor.fetchone())[0])
        rows_cursor = await self._db.execute(
            f"SELECT id, request_id, run_id, conversation_id, occurred_at, model, "
            f"source, call_type, subtask_id, usage_available, input_tokens, "
            f"output_tokens, cached_input_tokens, cache_write_tokens, details_json "
            f"FROM model_trajectory WHERE {where} ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, max(1, min(500, int(limit))), max(0, int(offset))],
        )
        rows = [dict(row) for row in await rows_cursor.fetchall()]
        for row in rows:
            row["details"] = json.loads(row.pop("details_json"))
            if row["usage_available"] is not None:
                row["usage_available"] = bool(row["usage_available"])
        return {"items": rows, "total": total, "limit": max(1, min(500, int(limit))),
                "offset": max(0, int(offset))}


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None
