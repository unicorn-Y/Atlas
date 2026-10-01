# Logic adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# agent/usage_pricing.py (MIT, (c) Nous Research); account and credit features excluded.
"""Persistent run usage records and grouped cost summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite

from atlas.usage_pricing import estimate_cost


class UsageLedger:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS usage_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                subtask_id TEXT,
                model TEXT NOT NULL,
                started_at TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                est_cost REAL
            )
        """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_started ON usage_records(started_at)")
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def record(
        self, *, run_id: str, conversation_id: str, subtask_id: str | None,
        model: str, started_at: str, usage: dict[str, Any],
        price: dict[str, Any] | None = None,
    ) -> None:
        if self._db is None:
            return
        values = {
            "input_tokens": max(0, int(usage.get("input_tokens") or 0)),
            "output_tokens": max(0, int(usage.get("output_tokens") or 0)),
            "cached_input_tokens": max(0, int(usage.get("cached_input_tokens") or 0)),
            "cache_write_tokens": max(0, int(usage.get("cache_write_tokens") or 0)),
        }
        cost = estimate_cost(model, **values, price=price)
        await self._db.execute(
            """INSERT INTO usage_records
            (run_id, conversation_id, subtask_id, model, started_at, input_tokens,
             output_tokens, cached_input_tokens, cache_write_tokens, est_cost)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, conversation_id, subtask_id, model, started_at,
             values["input_tokens"], values["output_tokens"],
             values["cached_input_tokens"], values["cache_write_tokens"],
             float(cost) if cost is not None else None),
        )
        await self._db.commit()

    async def query(
        self, *, start: str | None, end: str | None, group_by: str,
    ) -> dict[str, Any]:
        if self._db is None:
            return {"rows": [], "totals": _aggregate([])}
        expression = {
            "day": "substr(started_at, 1, 10)",
            "conversation": "conversation_id",
            "model": "model",
        }[group_by]
        where, params = [], []
        if start:
            where.append("started_at >= ?")
            params.append(start)
        if end:
            where.append("started_at < ?")
            params.append(end)
        sql = "SELECT " + expression + " AS grp, run_id, subtask_id, model, input_tokens, output_tokens, cached_input_tokens, est_cost FROM usage_records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        async with self._db.execute(sql, params) as cursor:
            records = [dict(zip((col[0] for col in cursor.description), row))
                       async for row in cursor]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            grouped.setdefault(str(record["grp"]), []).append(record)
        rows = []
        for key, items in sorted(grouped.items()):
            row = _aggregate(items)
            rows.append({"key": key, "label": key, **row})
        return {"rows": rows, "totals": _aggregate(records)}


def _aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    input_tokens = sum(int(item.get("input_tokens") or 0) for item in items)
    cached = sum(int(item.get("cached_input_tokens") or 0) for item in items)
    costs = [item.get("est_cost") for item in items]
    known_costs = [float(cost) for cost in costs if cost is not None]
    return {
        "runs": len({(item.get("run_id"), item.get("subtask_id")) for item in items}),
        "input_tokens": input_tokens,
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in items),
        "cached_input_tokens": cached,
        "cache_hit_rate": round(cached / input_tokens, 4) if input_tokens else None,
        "est_cost": sum(known_costs) if len(known_costs) == len(costs) else None,
    }
