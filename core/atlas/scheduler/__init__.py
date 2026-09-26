"""Atlas Scheduler — persistent scheduled tasks backed by APScheduler 4.x.

Provides a thin wrapper over APScheduler's AsyncScheduler with:
- TOML-based task persistence (human-readable, editable)
- Cron / interval / one-shot trigger types
- Pause / resume / CRUD API
- Integration hook for the Agent orchestrator (run a message as the user)
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine

import structlog

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from atlas.config import PROJECT_ROOT, get_config

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class TriggerType(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    DATE = "date"


class TaskStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"


@dataclass
class ScheduledTask:
    """A user-defined scheduled task."""

    id: str  # unique slug, e.g. "daily-arxiv-digest"
    name: str  # display name
    description: str
    trigger_type: TriggerType
    trigger_args: dict[str, Any]  # passed to APScheduler trigger constructor
    action: str  # "agent:<message>" or "callback:<dotted.path>"
    status: TaskStatus = TaskStatus.ACTIVE
    tags: list[str] = field(default_factory=list)
    created_at: str = ""  # ISO 8601
    updated_at: str = ""  # ISO 8601
    last_run_at: str = ""  # ISO 8601, empty if never
    next_run_at: str = ""  # computed from APScheduler
    run_count: int = 0
    goal: str = ""
    goal_status: str = "pending"
    goal_progress: dict[str, Any] = field(default_factory=dict)
    goal_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API / TOML persistence."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger_type": self.trigger_type.value,
            "trigger_args": self.trigger_args,
            "action": self.action,
            "status": self.status.value,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "run_count": self.run_count,
            "goal": self.goal,
            "goal_status": self.goal_status,
            "goal_progress": self.goal_progress,
            "goal_events": self.goal_events,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScheduledTask:
        """Deserialize from dict (TOML / API)."""
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            description=d.get("description", ""),
            trigger_type=TriggerType(d.get("trigger_type", "cron")),
            trigger_args=d.get("trigger_args", {}),
            action=d.get("action", ""),
            status=TaskStatus(d.get("status", "active")),
            tags=d.get("tags", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            last_run_at=d.get("last_run_at", ""),
            next_run_at=d.get("next_run_at", ""),
            run_count=d.get("run_count", 0),
            goal=d.get("goal", ""),
            goal_status=d.get("goal_status", "pending"),
            goal_progress=d.get("goal_progress", {}),
            goal_events=d.get("goal_events", []),
        )


# ---------------------------------------------------------------------------
# TOML persistence helpers
# ---------------------------------------------------------------------------

def _default_schedules_path() -> Path:
    cfg = get_config()
    data_dir = cfg.db_path.parent  # same dir as the sqlite db
    return data_dir / "schedules.toml"


def _load_tasks_from_toml(path: Path) -> dict[str, ScheduledTask]:
    """Load tasks from a TOML file."""
    if not path.exists():
        return {}

    with open(path, "rb") as f:
        data = tomllib.load(f)

    tasks: dict[str, ScheduledTask] = {}
    for task_id, task_data in data.get("tasks", {}).items():
        task_data["id"] = task_id
        for field_name in ("goal_progress", "goal_events"):
            serialized = task_data.pop(f"{field_name}_json", None)
            if serialized:
                try:
                    task_data[field_name] = json.loads(serialized)
                except (TypeError, ValueError):
                    log.warning("scheduler.goal_state_load_error", task_id=task_id,
                                field=field_name)
        try:
            tasks[task_id] = ScheduledTask.from_dict(task_data)
        except (KeyError, ValueError) as e:
            log.warning("scheduler.load_error", task_id=task_id, error=str(e))
    return tasks


def _save_tasks_to_toml(path: Path, tasks: dict[str, ScheduledTask]) -> None:
    """Save tasks to a TOML file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# Atlas Scheduled Tasks",
        "# Auto-generated — manual edits are welcome but keep the format.",
        "",
    ]

    for task in sorted(tasks.values(), key=lambda t: t.id):
        lines.append(f"[tasks.{task.id}]")
        lines.append(f'name = "{_escape_toml(task.name)}"')
        lines.append(f'description = "{_escape_toml(task.description)}"')
        lines.append(f'trigger_type = "{task.trigger_type.value}"')
        lines.append(f'action = "{_escape_toml(task.action)}"')
        lines.append(f'status = "{task.status.value}"')
        lines.append(f'created_at = "{task.created_at}"')
        lines.append(f'updated_at = "{task.updated_at}"')
        lines.append(f'last_run_at = "{task.last_run_at}"')
        lines.append(f'next_run_at = "{task.next_run_at}"')
        lines.append(f"run_count = {task.run_count}")
        lines.append(f'goal = "{_escape_toml(task.goal)}"')
        lines.append(f'goal_status = "{task.goal_status}"')
        progress_json = _escape_toml(
            json.dumps(task.goal_progress, ensure_ascii=False)
        )
        events_json = _escape_toml(
            json.dumps(task.goal_events, ensure_ascii=False)
        )
        lines.append(
            f'goal_progress_json = "{progress_json}"'
        )
        lines.append(
            f'goal_events_json = "{events_json}"'
        )

        if task.tags:
            tag_list = ", ".join(f'"{t}"' for t in task.tags)
            lines.append(f"tags = [{tag_list}]")
        else:
            lines.append("tags = []")

        # trigger_args as inline table or sub-table
        lines.append("")
        lines.append(f"[tasks.{task.id}.trigger_args]")
        for k, v in task.trigger_args.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{_escape_toml(v)}"')
            elif isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f'{k} = "{_escape_toml(str(v))}"')

        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _escape_toml(s: str) -> str:
    """Escape a string for TOML double-quoted value."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------------------------------------------------------------------------
# Trigger factory
# ---------------------------------------------------------------------------

def _make_trigger(
    trigger_type: TriggerType,
    trigger_args: dict[str, Any],
    timezone_str: str = "Asia/Shanghai",
) -> CronTrigger | IntervalTrigger | DateTrigger:
    """Create an APScheduler trigger from our config."""
    if trigger_type == TriggerType.CRON:
        return CronTrigger(timezone=timezone_str, **trigger_args)
    elif trigger_type == TriggerType.INTERVAL:
        return IntervalTrigger(**trigger_args)
    elif trigger_type == TriggerType.DATE:
        run_time = trigger_args.get("run_time", "")
        if isinstance(run_time, str) and run_time:
            run_time = datetime.fromisoformat(run_time)
        return DateTrigger(run_time=run_time)
    else:
        raise ValueError(f"Unknown trigger type: {trigger_type}")


# ---------------------------------------------------------------------------
# AtlasScheduler
# ---------------------------------------------------------------------------

class AtlasScheduler:
    """Manages scheduled tasks with APScheduler 4.x backend.

    Usage::

        scheduler = AtlasScheduler()
        await scheduler.start()
        await scheduler.add_task(ScheduledTask(...))
        ...
        await scheduler.stop()
    """

    def __init__(
        self,
        schedules_path: Path | None = None,
        agent_callback: Callable[[str, str], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """
        Args:
            schedules_path: Path to the TOML persistence file.
            agent_callback: async fn(task_id, message) called for "agent:..." actions.
        """
        self._schedules_path = schedules_path  # resolved lazily
        self._tasks: dict[str, ScheduledTask] = {}
        self._ap_scheduler: AsyncScheduler | None = None
        self._agent_callback = agent_callback
        self._started = False
        self._goal_heartbeat_task: asyncio.Task[None] | None = None
        self._goal_locks: dict[str, asyncio.Lock] = {}

    GOAL_HEARTBEAT_SECONDS = 30

    @property
    def _path(self) -> Path:
        if self._schedules_path is None:
            self._schedules_path = _default_schedules_path()
        return self._schedules_path

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        """Load persisted tasks and start the APScheduler."""
        if self._started:
            return

        self._tasks = _load_tasks_from_toml(self._path)
        for task in self._tasks.values():
            if task.goal and task.goal_status == "running":
                task.goal_status = "interrupted"
                trace = task.goal_progress.get("execution_trace", {})
                if not isinstance(trace, dict):
                    trace = {}
                self._append_goal_event(task, "goal.interrupted", {
                    "detail": "The service restarted during goal execution.",
                }, run_id=trace.get("run_id"), plan_id=trace.get("plan_id"))
        self._persist()
        log.info("scheduler.loaded", count=len(self._tasks), path=str(self._path))

        cfg = get_config()
        tz = cfg.scheduler_timezone

        # APScheduler 4.x requires entering the async context manager
        # before calling start_in_background().
        self._ap_scheduler = AsyncScheduler()
        await self._ap_scheduler.__aenter__()

        # Register all active tasks with APScheduler
        for task in self._tasks.values():
            if task.status == TaskStatus.ACTIVE:
                try:
                    trigger = _make_trigger(task.trigger_type, task.trigger_args, tz)
                    await self._ap_scheduler.configure_task(
                        task.id, func=self._make_executor(task)
                    )
                    await self._ap_scheduler.add_schedule(
                        task.id,
                        trigger=trigger,
                        id=task.id,
                        conflict_policy="replace",
                    )
                except Exception as e:
                    log.warning("scheduler.register_error",
                                task_id=task.id, error=str(e))

        await self._ap_scheduler.start_in_background()
        self._started = True
        self._goal_heartbeat_task = asyncio.create_task(
            self._goal_heartbeat_loop(), name="atlas-goal-heartbeat"
        )
        log.info("scheduler.started")

    async def stop(self) -> None:
        """Stop the scheduler and persist state."""
        if not self._started or self._ap_scheduler is None:
            return

        if self._goal_heartbeat_task:
            self._goal_heartbeat_task.cancel()
            try:
                await self._goal_heartbeat_task
            except asyncio.CancelledError:
                pass
            self._goal_heartbeat_task = None

        await self._ap_scheduler.stop()
        await self._ap_scheduler.__aexit__(None, None, None)
        self._persist()
        self._started = False
        log.info("scheduler.stopped")

    def _persist(self) -> None:
        """Save current tasks to TOML."""
        _save_tasks_to_toml(self._path, self._tasks)

    @staticmethod
    def _append_goal_event(
        task: ScheduledTask,
        event: str,
        data: dict[str, Any],
        *,
        run_id: str | None = None,
        plan_id: str | None = None,
        step_id: str | None = None,
    ) -> None:
        sequence = max(
            (item.get("sequence", index)
             for index, item in enumerate(task.goal_events)
             if isinstance(item, dict)
             and isinstance(item.get("sequence", index), int)),
            default=-1,
        ) + 1
        record: dict[str, Any] = {
            "event_id": f"{task.id}:{sequence}",
            "sequence": sequence,
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }
        if run_id:
            record["run_id"] = run_id
        if plan_id:
            record["plan_id"] = plan_id
        if step_id:
            record["step_id"] = step_id
        task.goal_events.append(record)

    async def update_goal_state(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: dict[str, Any] | None = None,
    ) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if task is None or not task.goal:
            return None
        if status is not None:
            task.goal_status = status
        if progress is not None:
            task.goal_progress = progress
        self._persist()
        return task

    async def record_goal_event(
        self,
        task_id: str,
        event: str,
        data: dict[str, Any],
        *,
        run_id: str | None = None,
        plan_id: str | None = None,
        step_id: str | None = None,
    ) -> ScheduledTask | None:
        task = self._tasks.get(task_id)
        if task is None or not task.goal:
            return None
        self._append_goal_event(
            task, event, data, run_id=run_id, plan_id=plan_id, step_id=step_id,
        )
        self._persist()
        return task

    def goal_trace(
        self, task_id: str, *, run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return persisted goal audit events in stable append order."""
        task = self._tasks.get(task_id)
        if task is None or not task.goal:
            return None
        events = []
        for index, event in enumerate(task.goal_events):
            if not isinstance(event, dict):
                continue
            sequence = event.get("sequence", index)
            if not isinstance(sequence, int):
                sequence = index
            if run_id is not None and event.get("run_id") != run_id:
                continue
            events.append({**event, "sequence": sequence})
        events.sort(key=lambda event: (event["sequence"], event.get("event_id", "")))
        return {
            "goal_id": task.id,
            "status": task.goal_status,
            "events": events,
        }

    async def heartbeat_goals(self) -> int:
        """Continue durable goals whose last run left work pending."""
        if self._agent_callback is None:
            return 0
        candidates = [
            task for task in self.list_tasks(status=TaskStatus.ACTIVE)
            if task.goal and task.goal_status in {"pending", "interrupted"}
        ]
        started = 0
        for task in candidates:
            if await self._invoke_goal_callback(task.id, task.goal):
                task.last_run_at = datetime.now(UTC).isoformat()
                task.run_count += 1
                self._persist()
                started += 1
        return started

    async def _goal_heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.GOAL_HEARTBEAT_SECONDS)
            try:
                await self.heartbeat_goals()
            except Exception as exc:
                log.error("scheduler.goal_heartbeat_error", error=str(exc))

    async def _invoke_goal_callback(self, task_id: str, message: str) -> bool:
        callback = self._agent_callback
        if callback is None:
            return False
        lock = self._goal_locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            task = self._tasks.get(task_id)
            if (
                task is None or not task.goal
                or task.goal_status in {"running", "completed", "blocked", "awaiting_approval"}
            ):
                return False
            await callback(task_id, message)
            return True

    # -- executor factory ------------------------------------------------------

    def _make_executor(self, task: ScheduledTask) -> Callable[[], Coroutine[Any, Any, None]]:
        """Create an async callable for APScheduler to run."""
        task_id = task.id
        action = task.action

        async def _run() -> None:
            now = datetime.now(timezone.utc).isoformat()
            t = self._tasks.get(task_id)
            if t:
                t.last_run_at = now
                t.run_count += 1
                self._persist()

            log.info("scheduler.task_fired", task_id=task_id, action=action)

            if action.startswith("agent:"):
                message = action[len("agent:"):]
                if self._agent_callback:
                    try:
                        t = self._tasks.get(task_id)
                        if t and t.goal:
                            await self._invoke_goal_callback(task_id, message)
                        else:
                            await self._agent_callback(task_id, message)
                    except Exception as e:
                        log.error("scheduler.agent_callback_error",
                                  task_id=task_id, error=str(e))
                else:
                    log.warning("scheduler.no_agent_callback", task_id=task_id)
            else:
                log.warning("scheduler.unknown_action", task_id=task_id,
                            action=action)

        return _run

    # -- CRUD ------------------------------------------------------------------

    async def add_task(self, task: ScheduledTask) -> ScheduledTask:
        """Add a new scheduled task."""
        if task.id in self._tasks:
            raise ValueError(f"Task already exists: {task.id}")

        now = datetime.now(timezone.utc).isoformat()
        task.created_at = task.created_at or now
        task.updated_at = now

        self._tasks[task.id] = task

        # Register with APScheduler if active and scheduler is running
        if task.status == TaskStatus.ACTIVE and self._ap_scheduler and self._started:
            cfg = get_config()
            trigger = _make_trigger(
                task.trigger_type, task.trigger_args, cfg.scheduler_timezone
            )
            await self._ap_scheduler.configure_task(
                task.id, func=self._make_executor(task)
            )
            await self._ap_scheduler.add_schedule(
                task.id,
                trigger=trigger,
                id=task.id,
                conflict_policy="replace",
            )

        self._persist()
        log.info("scheduler.task_added", task_id=task.id)
        return task

    async def update_task(
        self,
        task_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        trigger_type: TriggerType | None = None,
        trigger_args: dict[str, Any] | None = None,
        action: str | None = None,
        status: TaskStatus | None = None,
        tags: list[str] | None = None,
    ) -> ScheduledTask | None:
        """Update an existing task. Returns the updated task or None."""
        task = self._tasks.get(task_id)
        if task is None:
            return None

        if name is not None:
            task.name = name
        if description is not None:
            task.description = description
        if action is not None:
            task.action = action
        if tags is not None:
            task.tags = tags

        trigger_changed = False
        if trigger_type is not None:
            task.trigger_type = trigger_type
            trigger_changed = True
        if trigger_args is not None:
            task.trigger_args = trigger_args
            trigger_changed = True

        old_status = task.status
        if status is not None:
            task.status = status

        task.updated_at = datetime.now(timezone.utc).isoformat()

        # Update APScheduler registration
        if self._ap_scheduler and self._started:
            if task.status == TaskStatus.PAUSED and old_status == TaskStatus.ACTIVE:
                # Pause: remove schedule from APScheduler
                try:
                    await self._ap_scheduler.remove_schedule(task_id)
                except Exception:
                    pass
            elif task.status == TaskStatus.ACTIVE:
                if old_status == TaskStatus.PAUSED or trigger_changed:
                    # Resume or trigger changed: re-register
                    cfg = get_config()
                    trigger = _make_trigger(
                        task.trigger_type, task.trigger_args, cfg.scheduler_timezone
                    )
                    await self._ap_scheduler.configure_task(
                        task_id, func=self._make_executor(task)
                    )
                    await self._ap_scheduler.add_schedule(
                        task_id,
                        trigger=trigger,
                        id=task_id,
                        conflict_policy="replace",
                    )

        self._persist()
        log.info("scheduler.task_updated", task_id=task_id)
        return task

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task. Returns True if deleted."""
        task = self._tasks.pop(task_id, None)
        if task is None:
            return False

        # Remove from APScheduler
        if self._ap_scheduler and self._started:
            try:
                await self._ap_scheduler.remove_schedule(task_id)
            except Exception:
                pass

        self._persist()
        log.info("scheduler.task_deleted", task_id=task_id)
        return True

    def get_task(self, task_id: str) -> ScheduledTask | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        tag: str | None = None,
    ) -> list[ScheduledTask]:
        """List tasks with optional filters."""
        result = list(self._tasks.values())
        if status is not None:
            result = [t for t in result if t.status == status]
        if tag is not None:
            result = [t for t in result if tag in t.tags]
        return sorted(result, key=lambda t: t.id)

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    @property
    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values()
                   if t.status == TaskStatus.ACTIVE)

    def observability_snapshot(self) -> dict[str, Any]:
        """Return a deterministic, read-only summary of autonomous goal activity."""
        goals = [task for task in self.list_tasks() if task.goal]
        status_counts: dict[str, int] = {
            status: 0 for status in (
                "pending", "running", "interrupted", "completed", "blocked",
                "awaiting_approval",
            )
        }
        event_counts: dict[str, int] = {}
        summaries: list[dict[str, Any]] = []

        for task in goals:
            status = task.goal_status if isinstance(task.goal_status, str) else "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
            events = [event for event in task.goal_events if isinstance(event, dict)]
            for event in events:
                name = event.get("event")
                if isinstance(name, str) and name:
                    event_counts[name] = event_counts.get(name, 0) + 1

            latest_event = None
            if events:
                event = events[-1]
                latest_event = {
                    "event": event.get("event", ""),
                    "timestamp": event.get("timestamp", ""),
                    "sequence": len(task.goal_events) - 1,
                }
            summaries.append({
                "goal_id": task.id,
                "status": status,
                "last_run_at": task.last_run_at,
                "run_count": task.run_count,
                "event_count": len(task.goal_events),
                "latest_event": latest_event,
            })

        return {
            "scheduler_running": self._started,
            "task_count": self.task_count,
            "active_task_count": self.active_count,
            "goal_count": len(goals),
            "goal_status_counts": dict(sorted(status_counts.items())),
            "goal_event_counts": dict(sorted(event_counts.items())),
            "goals": summaries,
        }

    # -- manual trigger --------------------------------------------------------

    async def run_now(self, task_id: str) -> bool:
        """Manually trigger a task immediately. Returns True if fired."""
        task = self._tasks.get(task_id)
        if task is None:
            return False

        if self._ap_scheduler and self._started:
            executor = self._make_executor(task)
            # Fire immediately via add_job
            await self._ap_scheduler.configure_task(
                f"{task_id}__manual", func=executor
            )
            await self._ap_scheduler.add_job(
                f"{task_id}__manual"
            )
            log.info("scheduler.manual_run", task_id=task_id)
            return True
        else:
            # Scheduler not running — call directly
            executor = self._make_executor(task)
            await executor()
            return True
