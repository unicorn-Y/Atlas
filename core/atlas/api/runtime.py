"""Per-application run state and WebSocket connection/runtime persistence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import structlog
from fastapi import WebSocket, WebSocketDisconnect

from atlas.config import get_config

log = structlog.get_logger(__name__)

# How many times a single run may be resumed after a restart. A crash that
# repeats would otherwise restart the same work on every boot; after this the
# run stays failed and the user decides.
MAX_RESUME_ATTEMPTS = 3


class RunState:
    """Tracks a single agent run's state for the runtime protocol."""

    __slots__ = (
        "run_id", "conversation_id", "model", "started_at", "sequence",
        "status", "events", "cancel_event", "pause_event",
        "approval_futures", "approval_contexts", "task", "plan_state",
        "event_lock", "steer_queue", "input_futures", "mode", "workspace",
        "usage", "workspace_rules", "plan_future", "plan_edits",
        "tool_allow", "tool_deny", "reasoning_effort", "reasoning_effort_applied",
        "ephemeral", "ephemeral_source", "tool_output_dir", "subtasks",
        "read_only", "active_skills", "profile_id", "user_input",
        "permission_mode", "allowed_paths", "trust_future", "trust_event_id",
        "executor", "sandbox", "extra_roots",
        "trust_roots",
        "session_env",
        "project_id",
        "task_id",
        "telegram_user_id",
        "updated_at", "waiting_for", "persisted_sequence",
        "dynamic_plan_mode", "plan_approval_callback", "plan_mode_callback", "end_conversation_reason",
        "end_conversation_callback",
        "config_override", "ignore_project_config", "ignore_workspace_rules",
        "resume_attempts", "resume_context", "background",
    )

    def __init__(self, run_id: str, conversation_id: str, model: str) -> None:
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.model = model
        self.started_at = datetime.now(UTC).isoformat()
        self.updated_at = self.started_at
        self.waiting_for: str | None = None
        self.persisted_sequence = 0
        self.sequence = 0
        self.status = "running"  # running | paused | waiting | completed | failed | cancelled
        self.events: list[dict[str, Any]] = []  # full event log for replay
        self.cancel_event = asyncio.Event()
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # not paused initially
        self.approval_futures: dict[str, asyncio.Future[str]] = {}
        self.approval_contexts: dict[str, dict[str, Any]] = {}
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
        # Auto-resume bookkeeping (restart recovery). ``resume_attempts`` is
        # persisted so a run that keeps getting interrupted is never resumed
        # in an endless loop.
        self.resume_attempts = 0
        self.resume_context: dict[str, Any] = {}
        self.background = False
        self.permission_mode = "full_access"
        self.allowed_paths: list[str] = []
        self.trust_future: asyncio.Future[bool] | None = None
        self.trust_event_id: str | None = None
        self.executor = "atlas"
        self.sandbox: dict[str, Any] | None = None
        self.extra_roots: list[str] = []
        self.trust_roots: list[str] = []
        self.session_env: dict[str, str] = {}
        self.project_id: str | None = None
        self.task_id: str | None = None
        self.telegram_user_id: int | None = None
        self.dynamic_plan_mode = False
        self.plan_approval_callback: Any = None
        self.plan_mode_callback: Any = None
        self.end_conversation_reason = ""
        self.end_conversation_callback: Any = None
        self.config_override: dict[str, Any] | None = None
        self.ignore_project_config = False
        self.ignore_workspace_rules = False

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
        self.updated_at = envelope["timestamp"]
        if event == "approval.required":
            self.waiting_for = "approval"
        elif event == "input.required":
            self.waiting_for = "input"
        elif event == "run.plan.proposed":
            self.waiting_for = "plan"
        elif event == "rules.trust_required":
            self.waiting_for = "trust"
        elif event in {"run.completed", "run.failed", "run.cancelled", "run.started"}:
            self.waiting_for = None
        return envelope


def _resume_context(run: "RunState") -> dict[str, Any]:
    """The minimum a restart needs to rebuild this run, or an empty dict.

    Only what the execution path cannot re-derive is stored: the original
    request, its workspace/mode/model, and the read-only + ephemeral flags
    that change tool permissions. Rules, skills and trust state are rebuilt
    from the workspace on replay, so persisting them would only let them go
    stale.
    """
    context = {
        "workspace": run.workspace,
        "mode": run.mode,
        "model": run.model,
        "permission_mode": run.permission_mode,
        "allowed_paths": run.allowed_paths,
        "extra_roots": run.extra_roots,
        "read_only": run.read_only,
        "ephemeral": run.ephemeral,
        "ephemeral_source": run.ephemeral_source,
        "profile_id": run.profile_id,
        "project_id": run.project_id,
        "reasoning_effort": run.reasoning_effort,
        "config_override": run.config_override,
        "ignore_project_config": run.ignore_project_config,
        "ignore_workspace_rules": run.ignore_workspace_rules,
        "background": run.background,
    }
    return {key: value for key, value in context.items() if value not in (None, "", [], False)}


class RuntimeManager:
    """Manages active WebSocket connections and agent runs."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.connections: dict[str, WebSocket] = {}  # conn_id → ws
        self.runs: dict[str, RunState] = {}  # run_id → RunState
        self.conn_runs: dict[str, str] = {}  # conn_id → active run_id
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._persist_lock = asyncio.Lock()
        self.services: Any = None
        # run_ids interrupted by a restart that may be resumed automatically.
        # Populated by init(), consumed once by resume_interrupted_runs().
        self.pending_resumes: list[str] = []

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
                plan_state TEXT,
                started_at TEXT,
                updated_at TEXT,
                waiting_for TEXT,
                user_input TEXT,
                resume_context TEXT,
                resume_attempts INTEGER NOT NULL DEFAULT 0
            )
        """)
        async with self._db.execute("PRAGMA table_info(runtime_runs)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "plan_state" not in columns:
            await self._db.execute("ALTER TABLE runtime_runs ADD COLUMN plan_state TEXT")
        for name in ("started_at", "updated_at", "waiting_for", "user_input", "resume_context"):
            if name not in columns:
                await self._db.execute(f"ALTER TABLE runtime_runs ADD COLUMN {name} TEXT")
        if "resume_attempts" not in columns:
            await self._db.execute(
                "ALTER TABLE runtime_runs ADD COLUMN resume_attempts INTEGER NOT NULL DEFAULT 0"
            )
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS runtime_activity (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                conversation_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL,
                status TEXT NOT NULL,
                waiting_for TEXT,
                detail TEXT,
                PRIMARY KEY (run_id, sequence)
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS runtime_activity_recent
            ON runtime_activity(timestamp DESC)
        """)
        await self._db.commit()
        async with self._db.execute("SELECT * FROM runtime_runs") as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            run = RunState(row["run_id"], row["conversation_id"], row["model"])
            run.status = row["status"]
            run.sequence = row["sequence"]
            run.persisted_sequence = row["sequence"]
            # Older rows have no timestamp. Keep it unknown rather than making
            # a historical run appear to have started during this boot.
            run.started_at = row["started_at"] or ""
            run.updated_at = row["updated_at"] or ""
            run.waiting_for = row["waiting_for"]
            run.plan_state = json.loads(row["plan_state"]) if row["plan_state"] else None
            run.user_input = row["user_input"] or ""
            run.resume_attempts = row["resume_attempts"] or 0
            run.resume_context = (
                json.loads(row["resume_context"]) if row["resume_context"] else {}
            )
            run.background = bool(run.resume_context.get("background"))
            if run.status in ("running", "paused", "waiting"):
                # A restart is an interruption, not a verdict. Runs that were
                # mid-flight become ``failed`` so nothing in the sidebar
                # claims to still be working, but they are queued for an
                # explicit resume (``pending_resumes``) that the server
                # triggers once the rest of startup is wired.
                interrupted_from = run.status
                run.status = "failed"
                run.waiting_for = None
                detail = (
                    "The service restarted while this run was active; "
                    "execution was not resumed."
                )
                recovery = run.next_envelope("run.failed", {
                    "category": "interrupted",
                    "detail": detail,
                    "recoverable": True,
                })
                await self.persist_run(run, recovery_event=recovery)
                if self._resumable(run, interrupted_from):
                    self.pending_resumes.append(run.run_id)
            elif row["recovery_event"]:
                run.events.append(json.loads(row["recovery_event"]))
            self.runs[run.run_id] = run

    @staticmethod
    def _resumable(run: RunState, interrupted_from: str) -> bool:
        """Whether an interrupted run may be continued automatically.

        A run only resumes when nothing external was blocking it: a run that
        was ``waiting`` (approval, plan, input, rule trust) is *not* resumed,
        because continuing it would silently answer a question the user was
        asked. Ephemeral side chats and runs without a stored request are
        skipped for the same reason: there is nothing faithful to replay.
        """
        if interrupted_from != "running":
            return False
        if not (run.user_input or "").strip():
            return False
        if run.ephemeral or run.read_only:
            return False
        return run.resume_attempts < MAX_RESUME_ATTEMPTS
    async def resume_interrupted_runs(
        self, resume: Callable[[RunState], Awaitable[bool]],
    ) -> list[str]:
        """Continue runs interrupted by the previous shutdown.

        ``resume`` performs the actual continuation; it returns True when the
        run was taken over. This method owns the bookkeeping so the caller
        never has to: one attempt is recorded per run *before* handing it
        off, which is what bounds a crash-loop that would otherwise re-run
        the same work on every boot.
        """
        resumed: list[str] = []
        pending, self.pending_resumes = self.pending_resumes, []
        for run_id in pending:
            run = self.runs.get(run_id)
            if run is None:
                continue
            # Only the run that was actually interrupted may continue: a
            # newer turn in the same conversation supersedes it, and
            # continuing would talk over what the user asked for since.
            newer = self._newer_run_in_conversation(run)
            if newer is not None:
                log.info(
                    "run.resume_skipped", run_id=run_id, reason="superseded",
                    newer_run_id=newer,
                )
                continue
            run.resume_attempts += 1
            await self.persist_run(run)
            try:
                taken = await resume(run)
            except Exception:
                log.exception("run.resume_failed", run_id=run_id)
                continue
            if taken:
                resumed.append(run_id)
                log.info("run.resumed_after_restart", run_id=run_id)
        return resumed

    def _newer_run_in_conversation(self, run: RunState) -> str | None:
        """Run id of a newer non-resumed run in the same conversation."""
        latest: tuple[str, str] | None = None
        for other in self.runs.values():
            if other.run_id == run.run_id:
                continue
            if other.conversation_id != run.conversation_id:
                continue
            stamp = other.updated_at or other.started_at or ""
            if latest is None or stamp > latest[1]:
                latest = (other.run_id, stamp)
        if latest is None:
            return None
        mine = run.updated_at or run.started_at or ""
        return latest[0] if latest[1] > mine else None

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def persist_run(
        self, run: RunState, recovery_event: dict[str, Any] | None = None,
    ) -> None:
        if self._db is None:
            return
        async with self._persist_lock:
            await self._persist_run_locked(run, recovery_event)

    async def _persist_run_locked(
        self, run: RunState, recovery_event: dict[str, Any] | None,
    ) -> None:
        assert self._db is not None
        if run.status != "waiting":
            run.waiting_for = None
        await self._db.execute("""
            INSERT INTO runtime_runs (
                run_id, conversation_id, model, status, sequence, recovery_event,
                plan_state, started_at, updated_at, waiting_for, user_input,
                resume_context, resume_attempts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                conversation_id=excluded.conversation_id,
                model=excluded.model,
                status=excluded.status,
                sequence=excluded.sequence,
                recovery_event=COALESCE(excluded.recovery_event, runtime_runs.recovery_event),
                plan_state=COALESCE(excluded.plan_state, runtime_runs.plan_state),
                started_at=COALESCE(runtime_runs.started_at, excluded.started_at),
                updated_at=excluded.updated_at,
                waiting_for=excluded.waiting_for,
                -- Resume context is written once, by the turn that owns it.
                -- COALESCE keeps later turns (steering, approvals, retries)
                -- from erasing or rewording the original request.
                user_input=COALESCE(runtime_runs.user_input, excluded.user_input),
                resume_context=COALESCE(runtime_runs.resume_context, excluded.resume_context),
                resume_attempts=excluded.resume_attempts
        """, (
            run.run_id, run.conversation_id, run.model, run.status, run.sequence,
            json.dumps(recovery_event) if recovery_event else None,
            json.dumps(run.plan_state, ensure_ascii=False) if run.plan_state else None,
            run.started_at, run.updated_at, run.waiting_for,
            run.user_input or None,
            json.dumps(_resume_context(run), ensure_ascii=False),
            run.resume_attempts,
        ))
        activity_events = {
            "run.started": "running",
            "approval.required": "waiting", "input.required": "waiting",
            "run.plan.proposed": "waiting", "rules.trust_required": "waiting",
            "run.completed": "completed", "run.failed": "failed",
            "run.cancelled": "cancelled",
        }
        new_events = []
        for envelope in reversed(run.events):
            if envelope.get("sequence", 0) <= run.persisted_sequence:
                break
            new_events.append(envelope)
        for envelope in reversed(new_events):
            sequence = envelope.get("sequence", 0)
            event = envelope.get("event")
            if event not in activity_events:
                continue
            data = envelope.get("data") or {}
            waiting_for = {
                "approval.required": "approval", "input.required": "input",
                "run.plan.proposed": "plan", "rules.trust_required": "trust",
            }.get(event)
            detail = data.get("detail") if event == "run.failed" else None
            await self._db.execute("""
                INSERT OR IGNORE INTO runtime_activity
                (run_id, sequence, conversation_id, timestamp, event, status, waiting_for, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run.run_id, sequence, run.conversation_id, envelope["timestamp"],
                event, activity_events[event], waiting_for,
                str(detail) if detail is not None else None,
            ))
        await self._db.commit()
        if new_events:
            run.persisted_sequence = new_events[0]["sequence"]

    async def conversation_activity(self, limit: int = 100) -> dict[str, Any]:
        """Return persisted run states and recent lifecycle events for the sidebar."""
        if self._db is None:
            return {"items": [], "events": []}
        async with self._persist_lock:
            async with self._db.execute("""
                SELECT run_id, conversation_id, status, started_at, updated_at, waiting_for
                FROM runtime_runs ORDER BY COALESCE(updated_at, started_at) DESC, rowid DESC
            """) as cursor:
                runs = [dict(row) for row in await cursor.fetchall()]
            async with self._db.execute("""
                SELECT run_id, sequence, conversation_id, timestamp, event, status,
                       waiting_for, detail
                FROM runtime_activity ORDER BY timestamp DESC, run_id DESC, sequence DESC
                LIMIT ?
            """, (limit,)) as cursor:
                events = [dict(row) for row in await cursor.fetchall()]
        by_conversation: dict[str, dict[str, Any]] = {}
        active = {"running", "waiting", "paused"}
        for row in runs:
            conversation_id = row["conversation_id"]
            previous = by_conversation.get(conversation_id)
            if previous and (previous["status"] in active or row["status"] not in active):
                continue
            by_conversation[conversation_id] = {
                "conversation_id": conversation_id,
                "run_id": row["run_id"],
                "status": row["status"],
                "updated_at": row["updated_at"] or row["started_at"],
                "waiting_for": row["waiting_for"] if row["status"] == "waiting" else None,
            }
        return {"items": list(by_conversation.values()), "events": events}

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
            except (OSError, RuntimeError, WebSocketDisconnect):
                return  # connection may have closed

    async def send_run(self, run: RunState, data: dict[str, Any], fallback_conn_id: str) -> None:
        """Send to the most recently attached connection for this run."""
        event = data.get("event")
        if event == "run.failed":
            try:
                from atlas.diagnostic_alerts import record_alert
                detail = data.get("data", {}).get("detail", "任务运行失败。") if isinstance(data.get("data"), dict) else "任务运行失败。"
                record_alert("model", "模型/任务运行失败", str(detail), target="diagnostics", dedupe_key=f"run-failed:{run.run_id}")
            except OSError:
                log.warning("diagnostic alert persistence failed", run_id=run.run_id)
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
