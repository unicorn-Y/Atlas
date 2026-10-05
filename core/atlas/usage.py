# Logic adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# agent/usage_pricing.py (MIT, (c) Nous Research); account and credit features excluded.
"""Persistent run usage records and grouped cost summaries."""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import aiosqlite

from atlas.usage_pricing import estimate_cost


_RUN_USAGE_SUM_FIELDS = (
    "input_tokens", "uncached_input_tokens", "output_tokens",
    "cached_input_tokens", "cache_write_tokens", "request_count",
)


def deduplicate_run_usage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the latest diagnostic row for each request ID, preserving order."""
    unique: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for row in rows:
        request_id = str(row.get("request_id") or "")
        if request_id and request_id in positions:
            unique[positions[request_id]] = row
        else:
            if request_id:
                positions[request_id] = len(unique)
            unique.append(row)
    return unique


def aggregate_run_usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum unique request usage while keeping context size as the latest window."""
    unique = deduplicate_run_usage(rows)
    if not unique:
        return {
            **{key: None for key in _RUN_USAGE_SUM_FIELDS if key != "request_count"},
            "request_count": 0, "context_tokens": None, "context_limit": None,
            "model": None, "wire_model": None, "purpose_totals": {},
            "usage_available": True, "cache_hit_rate": None,
        }

    def sum_field(items: list[dict[str, Any]], key: str) -> int | None:
        if key != "request_count" and any(item.get("usage_available") is False for item in items):
            return None
        values = [
            item.get(key, 1) if key == "request_count" else item.get(key)
            for item in items
        ]
        if not values or any(
            not isinstance(value, int) or isinstance(value, bool) for value in values
        ):
            return None
        return sum(values)

    def purpose_totals(items: list[dict[str, Any]]) -> dict[str, Any]:
        purposes = dict.fromkeys(str(item.get("purpose") or "conversation") for item in items)
        return {
            purpose: {
                key: sum_field([
                    item for item in items
                    if str(item.get("purpose") or "conversation") == purpose
                ], key)
                for key in _RUN_USAGE_SUM_FIELDS
            }
            for purpose in purposes
        }

    conversation_rows = [
        item for item in unique if item.get("purpose", "conversation") == "conversation"
    ]
    window_rows = conversation_rows or unique
    latest_window = next(
        (item for item in reversed(window_rows) if isinstance(item.get("context_tokens"), int)),
        None,
    )
    latest_conversation = conversation_rows[-1] if conversation_rows else unique[-1]
    totals = {key: sum_field(unique, key) for key in _RUN_USAGE_SUM_FIELDS}
    totals.update(
        context_tokens=latest_window.get("context_tokens") if latest_window else None,
        context_limit=next(
            (item.get("context_limit") for item in reversed(window_rows)
             if item.get("context_limit") is not None), None,
        ),
        model=latest_conversation.get("model"),
        wire_model=latest_conversation.get("wire_model"),
        purpose_totals=purpose_totals(unique),
        usage_available=all(item.get("usage_available", True) is not False for item in unique),
    )
    if isinstance(totals["input_tokens"], int) and isinstance(totals["cached_input_tokens"], int):
        totals["cache_hit_rate"] = (
            round(totals["cached_input_tokens"] / totals["input_tokens"], 4)
            if totals["input_tokens"] > 0 else None
        )
    else:
        totals["cache_hit_rate"] = None
    return totals


class RunUsageBudget:
    """Harness opt-in input-token cap shared by requests in one runtime process."""

    def __init__(
        self, limit: int | None, audit_path: str | None = None, budget_id: str = "",
    ) -> None:
        self.limit = limit
        self.audit_path = audit_path
        self.budget_id = budget_id
        self.used = 0
        self.reserved = 0
        self.usage_unknown = False
        self._pending: dict[str, dict[str, Any]] = {}
        self._request_ids: set[str] = set()
        self._lock = threading.Lock()

    def reserve(
        self, request_id: str, estimated_input_tokens: int, *,
        purpose: str = "conversation", model: str = "", wire_model: str = "",
    ) -> bool:
        estimate = max(0, int(estimated_input_tokens or 0))
        with self._lock:
            if self.usage_unknown:
                return False
            if request_id in self._pending:
                self.reserved -= self._pending.pop(request_id)["estimate"]
            if self.limit is not None and self.used + self.reserved + estimate > self.limit:
                return False
            self.reserved += estimate
            self._pending[request_id] = {
                "estimate": estimate, "purpose": purpose, "model": model,
                "wire_model": wire_model,
            }
            return True

    def release(self, request_id: str) -> None:
        with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return
            estimate = pending["estimate"]
            self.reserved -= estimate
            self.used += estimate
            self.usage_unknown = True
            if request_id:
                self._request_ids.add(request_id)
            if self.audit_path:
                audit_row = {
                    "request_id": request_id,
                    "purpose": pending["purpose"],
                    "model": pending["model"],
                    "wire_model": pending["wire_model"],
                    "request_count": 1,
                    "usage_available": False,
                    "input_tokens": None,
                    "estimated_input_tokens": estimate,
                    "budget_input_tokens": estimate,
                    "budget_usage_unknown": True,
                    "budget_id": self.budget_id or os.environ.get("ATLAS_RUN_BUDGET_ID", ""),
                }
                path = Path(self.audit_path).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(audit_row, ensure_ascii=False, separators=(",", ":")) + "\n")

    def refund(self, request_id: str) -> None:
        """Return a never-sent request's reservation: no charge, no audit row.

        A failure report marked ``request_sent: False`` means the request
        provably never reached a provider (e.g. auxiliary routing refused
        before any HTTP call). Charging its estimate would both inflate the
        audit beyond the requests actually sent and latch ``usage_unknown``
        for the whole run, so the reservation is returned and the identity is
        settled instead.
        """
        with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return
            self.reserved -= pending["estimate"]
            if request_id:
                self._request_ids.add(request_id)

    def record(self, usage: dict[str, Any]) -> bool:
        request_id = str(usage.get("request_id") or "")
        with self._lock:
            if request_id and request_id in self._request_ids:
                return not self.usage_unknown and (self.limit is None or self.used <= self.limit)
            if request_id:
                self._request_ids.add(request_id)
            pending = self._pending.pop(request_id, None)
            estimate = pending["estimate"] if pending else None
            if estimate is not None:
                self.reserved -= estimate
            if usage.get("usage_available") is False:
                self.used += estimate or 0
                self.usage_unknown = True
            else:
                self.used += max(0, int(usage.get("input_tokens") or 0))
            if self.audit_path:
                audit_row = {
                    key: usage.get(key) for key in (
                        "request_id", "purpose", "model", "wire_model", "request_count",
                        "usage_available", "input_tokens", "uncached_input_tokens",
                        "output_tokens", "cached_input_tokens", "cache_write_tokens",
                        "context_tokens", "cache_usage_available", "cache_usage_fields",
                    ) if key in usage
                }
                audit_row["estimated_input_tokens"] = estimate
                audit_row["budget_input_tokens"] = (
                    estimate if usage.get("usage_available") is False
                    else max(0, int(usage.get("input_tokens") or 0))
                )
                audit_row["budget_usage_unknown"] = self.usage_unknown
                audit_row["budget_id"] = self.budget_id or os.environ.get("ATLAS_RUN_BUDGET_ID", "")
                path = Path(self.audit_path).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(audit_row, ensure_ascii=False, separators=(",", ":")) + "\n")
            return not self.usage_unknown and (
                self.limit is None or self.used + self.reserved <= self.limit
            )


_ENV_BUDGETS: dict[str, RunUsageBudget] = {}
_ENV_BUDGETS_LOCK = threading.Lock()
_ACTIVE_RUN_BUDGET: ContextVar[RunUsageBudget | None] = ContextVar(
    "atlas_active_run_usage_budget", default=None,
)


def current_run_usage_budget() -> RunUsageBudget | None:
    return _ACTIVE_RUN_BUDGET.get()


@contextmanager
def use_run_usage_budget(budget: RunUsageBudget | None):
    token = _ACTIVE_RUN_BUDGET.set(budget)
    try:
        yield
    finally:
        _ACTIVE_RUN_BUDGET.reset(token)


def env_run_usage_budget() -> RunUsageBudget | None:
    """Return a shared budget only when the test harness explicitly opts in."""
    active = current_run_usage_budget()
    if active is not None:
        return active
    try:
        raw_limit = os.environ.get("ATLAS_RUN_INPUT_TOKEN_LIMIT", "").strip()
        limit = int(raw_limit) if raw_limit else None
    except ValueError:
        return None
    if limit is not None and limit <= 0:
        return None
    audit_path = os.environ.get("ATLAS_RUN_USAGE_AUDIT_FILE") or None
    if limit is None and not audit_path:
        return None
    key = f"{os.environ.get('ATLAS_RUN_BUDGET_ID', str(os.getpid()))}:{limit}"
    if audit_path:
        key += f":{audit_path}"
    with _ENV_BUDGETS_LOCK:
        return _ENV_BUDGETS.setdefault(
            key, RunUsageBudget(limit, audit_path, os.environ.get("ATLAS_RUN_BUDGET_ID", key)),
        )


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
                est_cost REAL,
                cache_miss_reason TEXT
            )
        """)
        columns = {row[1] async for row in await self._db.execute(
            "PRAGMA table_info(usage_records)")}
        if "cache_miss_reason" not in columns:
            await self._db.execute(
                "ALTER TABLE usage_records ADD COLUMN cache_miss_reason TEXT")
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
             output_tokens, cached_input_tokens, cache_write_tokens, est_cost,
             cache_miss_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, conversation_id, subtask_id, model, started_at,
             values["input_tokens"], values["output_tokens"],
             values["cached_input_tokens"], values["cache_write_tokens"],
             float(cost) if cost is not None else None,
             usage.get("cache_miss_reason") or None),
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
        sql = ("SELECT " + expression
               + " AS grp, run_id, subtask_id, model, input_tokens, output_tokens, "
               + "cached_input_tokens, est_cost, cache_miss_reason FROM usage_records")
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
            # 分组行附带未命中原因：取组内最近一条非空记录（通常同组同轮）。
            reasons = [item.get("cache_miss_reason") for item in items
                       if item.get("cache_miss_reason")]
            row["cache_miss_reason"] = reasons[-1] if reasons else None
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
