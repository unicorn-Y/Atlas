"""Per-application run state and WebSocket connection/runtime persistence."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import WebSocket

from atlas.config import get_config


class RunState:
    """Tracks a single agent run's state for the runtime protocol."""

    __slots__ = (
        "run_id", "conversation_id", "model", "started_at", "sequence",
        "status", "events", "cancel_event", "pause_event",
        "approval_futures", "task", "plan_state",
        "event_lock", "steer_queue", "input_futures", "mode", "workspace",
        "usage", "workspace_rules", "plan_future", "plan_edits",
        "tool_allow", "tool_deny", "reasoning_effort", "reasoning_effort_applied",
        "ephemeral", "ephemeral_source", "tool_output_dir", "subtasks",
        "read_only", "active_skills", "profile_id", "user_input",
        "permission_mode", "allowed_paths", "trust_future", "trust_event_id",
        "executor", "sandbox", "extra_roots",
        "trust_roots",
        "project_id",
        "telegram_user_id",
    )

    def __init__(self, run_id: str, conversation_id: str, model: str) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.model = model
        self.started_at = datetime.now(UTC).isoformat()
        self.sequence = 0
        self.status = "running"  # running | paused | waiting | completed | failed | cancelled
        self.events: list[dict[str, Any]] = []  # full event log for replay
        self.cancel_event = asyncio.Event()
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # not paused initially
        self.approval_futures: dict[str, asyncio.Future[str]] = {}
        self.task: asyncio.Task[None] | None = None
        self.plan_state: dict[str, Any] | None = None
        self.event_lock = asyncio.Lock()
        self.steer_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.input_futures: dict[str, asyncio.Future[str]] = {}
        self.mode = "act"
        self.workspace: str | None = None
        self.usage: list[dict[str, Any]] = []
        self.workspace_rules: list[dict[str, Any]] = []
        self.plan_future: asyncio.Future[dict[str, str]] | None = None
        self.plan_edits = ""
        self.tool_allow: list[str] | None = None
        self.tool_deny: list[str] = []
        self.reasoning_effort: str | None = None
        self.reasoning_effort_applied: bool | None = None
        self.ephemeral = False
        self.ephemeral_source: str | None = None
        self.tool_output_dir: Path | None = None
        self.subtasks: dict[str, dict[str, Any]] = {}
        self.read_only = False
        self.active_skills: list[str] = []
        self.profile_id: str | None = None
        self.user_input = ""
        self.permission_mode = "full_access"
        self.allowed_paths: list[str] = []
        self.trust_future: asyncio.Future[bool] | None = None
        self.trust_event_id: str | None = None
        self.executor = "atlas"
        self.sandbox: dict[str, Any] | None = None
        self.extra_roots: list[str] = []
        self.trust_roots: list[str] = []
        self.project_id: str | None = None
        self.telegram_user_id: int | None = None

    def next_envelope(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        """Build a Runtime Event envelope and append to log."""
        self.sequence += 1
        envelope = {
            "type": "agent_event",
            "run_id": self.run_id,
            "event_id": f"{self.run_id}:{self.sequence}",
            "sequence": self.sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "data": data,
        }
        self.events.append(envelope)
        return envelope

class RuntimeManager:
    """Manages active WebSocket connections and agent runs."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.connections: dict[str, WebSocket] = {}  # conn_id → ws
        self.runs: dict[str, RunState] = {}  # run_id → RunState
        self.conn_runs: dict[str, str] = {}  # conn_id → active run_id
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self.services: Any = None

    async def init(self, db_path: Path | None = None) -> None:
        """Load persisted lifecycle metadata and fail runs interrupted by restart."""
        if db_path is not None:
            self.db_path = db_path
        if self.db_path is None:
            self.db_path = get_config().db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS runtime_runs (
                run_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 0,
                recovery_event TEXT,
                plan_state TEXT
            )
        """)
        async with self._db.execute("PRAGMA table_info(runtime_runs)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "plan_state" not in columns:
            await self._db.execute("ALTER TABLE runtime_runs ADD COLUMN plan_state TEXT")
        await self._db.commit()
        async with self._db.execute("SELECT * FROM runtime_runs") as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            run = RunState(row["run_id"], row["conversation_id"], row["model"])
            run.status = row["status"]
            run.sequence = row["sequence"]
            run.plan_state = json.loads(row["plan_state"]) if row["plan_state"] else None
            if run.status in ("running", "paused", "waiting"):
                run.status = "failed"
                recovery = run.next_envelope("run.failed", {
                    "category": "interrupted",
                    "detail": (
                        "The service restarted while this run was active; "
                        "execution was not resumed."
                    ),
                    "recoverable": True,
                })
                await self.persist_run(run, recovery_event=recovery)
            elif row["recovery_event"]:
                run.events.append(json.loads(row["recovery_event"]))
            self.runs[run.run_id] = run

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def persist_run(
        self, run: RunState, recovery_event: dict[str, Any] | None = None,
    ) -> None:
        if self._db is None:
            return
        await self._db.execute("""
            INSERT INTO runtime_runs (
                run_id, conversation_id, model, status, sequence, recovery_event, plan_state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                conversation_id=excluded.conversation_id,
                model=excluded.model,
                status=excluded.status,
                sequence=excluded.sequence,
                recovery_event=COALESCE(excluded.recovery_event, runtime_runs.recovery_event),
                plan_state=COALESCE(excluded.plan_state, runtime_runs.plan_state)
        """, (
            run.run_id, run.conversation_id, run.model, run.status, run.sequence,
            json.dumps(recovery_event) if recovery_event else None,
            json.dumps(run.plan_state, ensure_ascii=False) if run.plan_state else None,
        ))
        await self._db.commit()

    async def connect(self, ws: WebSocket, conn_id: str) -> None:
        await ws.accept()
        self.connections[conn_id] = ws

    def disconnect(self, conn_id: str) -> None:
        self.connections.pop(conn_id, None)
        self.conn_runs.pop(conn_id, None)

    async def send(self, conn_id: str, data: dict[str, Any]) -> None:
        ws = self.connections.get(conn_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                pass  # connection may have closed

    async def send_run(self, run: RunState, data: dict[str, Any], fallback_conn_id: str) -> None:
        """Send to the most recently attached connection for this run."""
        conn_id = next(
            (
                conn for conn, active_run_id in reversed(self.conn_runs.items())
                if active_run_id == run.run_id
            ),
            fallback_conn_id,
        )
        async with run.event_lock:
            await self.persist_run(run)
            await self.send(conn_id, data)
