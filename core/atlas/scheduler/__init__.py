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
import fnmatch
import os
import shutil
import uuid
from contextlib import suppress
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
    EVENT = "event"


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
    runs: list[dict[str, Any]] = field(default_factory=list)

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
            "runs": self.runs,
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
            runs=d.get("runs", []),
        )


# ---------------------------------------------------------------------------
# TOML persistence helpers
# ---------------------------------------------------------------------------

def _default_schedules_path() -> Path:
    cfg = get_config()
    data_dir = cfg.db_path.parent  # same dir as the sqlite db
    return data_dir / "schedules.toml"


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            error = ctypes.get_last_error()
            if error == 5:  # Access denied still means the process exists.
                return True
            if error == 87:  # Invalid PID.
                return False
            raise ctypes.WinError(error)
        try:
            state = kernel32.WaitForSingleObject(handle, 0)
            if state == 0:
                return False
            if state == 0x00000102:  # WAIT_TIMEOUT
                return True
            raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
        for field_name in ("runs", "trigger_args"):
            serialized = task_data.pop(f"{field_name}_json", None)
            if serialized:
                try:
                    task_data[field_name] = json.loads(serialized)
                except (TypeError, ValueError):
                    log.warning("scheduler.state_load_error", task_id=task_id,
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
        lines.append(f'runs_json = "{_escape_toml(json.dumps(task.runs, ensure_ascii=False))}"')
        lines.append(f'trigger_args_json = "{_escape_toml(json.dumps(task.trigger_args, ensure_ascii=False))}"')

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
    elif trigger_type == TriggerType.EVENT:
        raise ValueError("event triggers are dispatched by AtlasScheduler")
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
        role: str = "desktop",
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
        self._role = role
        self._started = False
        self._goal_heartbeat_task: asyncio.Task[None] | None = None
        self._goal_locks: dict[str, asyncio.Lock] = {}
        self._event_debounce: dict[str, float] = {}
        self._lease_token = uuid.uuid4().hex
        self._lease_task: asyncio.Task[None] | None = None
        self._lease_ready: asyncio.Event | None = None
        self._watchdog_observer: Any = None
        self._store_mtime_ns = 0

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

        owns_lease = self._claim_lease()
        if owns_lease:
            self._migrate_hub_tasks()
        self._tasks = _load_tasks_from_toml(self._path)
        if owns_lease:
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

        self._lease_ready = asyncio.Event()
        self._lease_task = asyncio.create_task(self._lease_loop(), name="atlas-scheduler-lease")
        await self._lease_ready.wait()
        log.info("scheduler.started")

    async def stop(self) -> None:
        """Stop the scheduler and persist state."""
        if self._lease_task:
            self._lease_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._lease_task
            self._lease_task = None
        self._release_lease()
        log.info("scheduler.stopped")

    @property
    def _lease_path(self) -> Path:
        return self._path.with_name("scheduler.lock")

    def _claim_lease(self) -> bool:
        self._lease_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"pid": os.getpid(), "token": self._lease_token, "role": self._role,
                              "heartbeat": datetime.now(UTC).isoformat()})
        try:
            fd = os.open(self._lease_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                current = json.loads(self._lease_path.read_text(encoding="utf-8"))
                pid = int(current.get("pid", -1))
                if not _is_process_alive(pid):
                    raise ProcessLookupError(pid)
                if self._role == "hub" and current.get("role", "desktop") == "desktop":
                    tmp = self._lease_path.with_suffix(".lock.tmp")
                    tmp.write_text(json.dumps({"pid": os.getpid(), "token": self._lease_token,
                                               "role": self._role,
                                               "heartbeat": datetime.now(UTC).isoformat()}),
                                   encoding="utf-8")
                    os.replace(tmp, self._lease_path)
                    return True
                return current.get("token") == self._lease_token
            except ProcessLookupError:
                with suppress(OSError):
                    self._lease_path.unlink()
                return self._claim_lease()
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return False
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
        return True

    def _heartbeat_lease(self) -> None:
        try:
            current = json.loads(self._lease_path.read_text(encoding="utf-8"))
            if current.get("token") != self._lease_token:
                return
            tmp = self._lease_path.with_suffix(".lock.tmp")
            tmp.write_text(json.dumps({"pid": os.getpid(), "token": self._lease_token,
                                       "role": self._role,
                                       "heartbeat": datetime.now(UTC).isoformat()}),
                           encoding="utf-8")
            os.replace(tmp, self._lease_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return

    def _release_lease(self) -> None:
        try:
            current = json.loads(self._lease_path.read_text(encoding="utf-8"))
            if current.get("token") == self._lease_token:
                self._lease_path.unlink(missing_ok=True)
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    async def _activate_if_lease_owner(self) -> None:
        if self._started or not self._claim_lease():
            return
        self._migrate_hub_tasks()
        self._tasks = _load_tasks_from_toml(self._path)
        cfg = get_config()
        self._ap_scheduler = AsyncScheduler()
        await self._ap_scheduler.__aenter__()
        for task in self._tasks.values():
            if task.status != TaskStatus.ACTIVE or task.trigger_type == TriggerType.EVENT:
                continue
            try:
                trigger = _make_trigger(task.trigger_type, task.trigger_args, cfg.scheduler_timezone)
                await self._ap_scheduler.configure_task(task.id, func=self._make_executor(task))
                await self._ap_scheduler.add_schedule(task.id, trigger=trigger, id=task.id,
                                                      conflict_policy="replace")
            except Exception as exc:
                log.warning("scheduler.register_error", task_id=task.id, error=str(exc))
        await self._ap_scheduler.start_in_background()
        self._started = True
        self._start_file_watchers()
        self._goal_heartbeat_task = asyncio.create_task(
            self._goal_heartbeat_loop(), name="atlas-goal-heartbeat",
        )

    async def _lease_loop(self) -> None:
        try:
            while True:
                if self._started:
                    if not self._owns_lease():
                        await self._deactivate_scheduler()
                    else:
                        self._heartbeat_lease()
                        await self._refresh_if_changed()
                else:
                    try:
                        await self._activate_if_lease_owner()
                    except Exception as exc:
                        log.error("scheduler.activation_error", error=str(exc))
                if self._lease_ready:
                    self._lease_ready.set()
                await asyncio.sleep(2)
        finally:
            if self._started:
                await self._deactivate_scheduler()
            self._release_lease()

    async def _refresh_if_changed(self) -> None:
        if not self._reload_shared_tasks() or not self._ap_scheduler:
            return
        try:
            schedules = await self._ap_scheduler.get_schedules()
            for schedule in schedules:
                task = self._tasks.get(schedule.id)
                if task is None or task.status != TaskStatus.ACTIVE or task.trigger_type == TriggerType.EVENT:
                    await self._ap_scheduler.remove_schedule(schedule.id)
            cfg = get_config()
            for task in self._tasks.values():
                if task.status == TaskStatus.ACTIVE and task.trigger_type != TriggerType.EVENT:
                    await self._ap_scheduler.configure_task(task.id, func=self._make_executor(task))
                    await self._ap_scheduler.add_schedule(
                        task.id, trigger=_make_trigger(task.trigger_type, task.trigger_args,
                                                       cfg.scheduler_timezone),
                        id=task.id, conflict_policy="replace",
                    )
            await self._restart_file_watchers()
        except Exception as exc:
            log.warning("scheduler.refresh_error", error=str(exc))

    async def _restart_file_watchers(self) -> None:
        if self._watchdog_observer is not None:
            self._watchdog_observer.stop()
            await asyncio.to_thread(self._watchdog_observer.join, 5)
            self._watchdog_observer = None
        self._start_file_watchers()

    def _owns_lease(self) -> bool:
        try:
            owner = json.loads(self._lease_path.read_text(encoding="utf-8"))
            return owner.get("token") == self._lease_token
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    async def _deactivate_scheduler(self) -> None:
        if self._watchdog_observer is not None:
            self._watchdog_observer.stop()
            await asyncio.to_thread(self._watchdog_observer.join, 5)
            self._watchdog_observer = None
        if self._goal_heartbeat_task:
            self._goal_heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._goal_heartbeat_task
            self._goal_heartbeat_task = None
        if self._ap_scheduler:
            await self._ap_scheduler.stop()
            await self._ap_scheduler.__aexit__(None, None, None)
            self._ap_scheduler = None
        self._started = False

    def _start_file_watchers(self) -> None:
        tasks = [task for task in self._tasks.values()
                 if task.trigger_type == TriggerType.EVENT and task.status == TaskStatus.ACTIVE
                 and task.trigger_args.get("event") == "file.changed"]
        if not tasks:
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning("scheduler.watchdog_unavailable")
            return
        observer = Observer()
        loop = asyncio.get_running_loop()
        manager = self

        class Handler(FileSystemEventHandler):
            def __init__(self, task: ScheduledTask) -> None:
                self.task = task

            def on_any_event(self, event: Any) -> None:
                if event.is_directory or getattr(event, "event_type", "") in {"opened", "closed_no_write"}:
                    return
                filters = self.task.trigger_args.get("filter", {})
                payload = {"root": str(Path(filters["root"]).resolve()),
                           "path": str(Path(event.src_path).resolve())}
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(manager.dispatch_event("file.changed", payload)),
                )

        seen: set[str] = set()
        for task in tasks:
            filters = task.trigger_args.get("filter", {})
            root = str(filters.get("root", "")) if isinstance(filters, dict) else ""
            if not root or not Path(root).is_absolute() or not Path(root).is_dir() or root in seen:
                continue
            seen.add(root)
            observer.schedule(Handler(task), root, recursive=True)
        if seen:
            observer.start()
            self._watchdog_observer = observer

    def _persist(self) -> None:
        """Save current tasks to TOML."""
        _save_tasks_to_toml(self._path, self._tasks)
        self._store_mtime_ns = self._path.stat().st_mtime_ns

    def _reload_shared_tasks(self) -> bool:
        try:
            mtime = self._path.stat().st_mtime_ns
        except OSError:
            return False
        if mtime == self._store_mtime_ns:
            return False
        self._tasks = _load_tasks_from_toml(self._path)
        self._store_mtime_ns = mtime
        return True

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

    def _migrate_hub_tasks(self) -> None:
        """Merge the former Hub-only schedule store once into the canonical store."""
        hub_path = self._path.with_name("hub-schedules.toml")
        marker = self._path.with_name("hub-schedules.toml.migrated")
        if not hub_path.exists() or marker.exists():
            return
        canonical = _load_tasks_from_toml(self._path)
        incoming = _load_tasks_from_toml(hub_path)
        for task_id, task in incoming.items():
            candidate = task_id
            if candidate in canonical:
                candidate = f"{task_id}-hub"
                suffix = 2
                while candidate in canonical:
                    candidate = f"{task_id}-hub-{suffix}"
                    suffix += 1
            task.id = candidate
            canonical[candidate] = task
        _save_tasks_to_toml(self._path, canonical)
        hub_path.replace(marker)

    async def dispatch_event(self, event: str, payload: dict[str, Any] | None = None) -> int:
        """Fire matching event schedules, with a two-second debounce per task."""
        if not self._started:
            return 0
        import time

        payload = payload or {}
        now = time.monotonic()
        fired = 0
        for task in self._tasks.values():
            if task.status != TaskStatus.ACTIVE or task.trigger_type != TriggerType.EVENT:
                continue
            args = task.trigger_args
            if args.get("event") != event:
                continue
            filters = args.get("filter", {})
            if isinstance(filters, dict):
                if event == "file.changed":
                    root = str(Path(str(filters.get("root", ""))).resolve())
                    changed_root = str(Path(str(payload.get("root", ""))).resolve())
                    if root != changed_root:
                        continue
                    pattern = filters.get("glob")
                    if pattern:
                        try:
                            relative = Path(str(payload.get("path", ""))).resolve().relative_to(Path(root))
                        except ValueError:
                            continue
                        if not fnmatch.fnmatch(relative.as_posix(), str(pattern)):
                            continue
                elif any(payload.get(k) != v for k, v in filters.items()):
                    continue
            if now - self._event_debounce.get(task.id, 0) < 2:
                continue
            self._event_debounce[task.id] = now
            await self._execute_task(task)
            fired += 1
        return fired

    async def _execute_task(self, task: ScheduledTask) -> None:
        run_id = uuid.uuid4().hex
        run = {"run_id": run_id, "conversation_id": f"scheduled-{task.id}-{run_id[:8]}",
               "started_at": datetime.now(UTC).isoformat(), "status": "running"}
        task.runs.append(run)
        task.runs = task.runs[-20:]
        task.last_run_at = run["started_at"]
        task.run_count += 1
        self._persist()
        try:
            action = task.action
            if action.startswith("agent:") and self._agent_callback:
                await self._agent_callback(task.id, action[len("agent:"):])
                run["status"] = "completed"
            else:
                run["status"] = "failed"
        except Exception:
            run["status"] = "failed"
            log.exception("scheduler.task_run_error", task_id=task.id)
        finally:
            self._persist()

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
                or task.goal_status in {"running", "completed", "blocked", "awaiting_approval", "paused"}
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
            run_id = uuid.uuid4().hex
            run = {"run_id": run_id, "conversation_id": f"scheduled-{task.id}-{run_id[:8]}",
                   "started_at": now, "status": "running"}
            if t:
                t.last_run_at = now
                t.run_count += 1
                t.runs.append(run)
                t.runs = t.runs[-20:]
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
                        run["status"] = "completed"
                    except Exception as e:
                        run["status"] = "failed"
                        log.error("scheduler.agent_callback_error",
                                  task_id=task_id, error=str(e))
                else:
                    run["status"] = "failed"
                    log.warning("scheduler.no_agent_callback", task_id=task_id)
            else:
                run["status"] = "failed"
                log.warning("scheduler.unknown_action", task_id=task_id,
                            action=action)
            self._persist()

        return _run

    # -- CRUD ------------------------------------------------------------------

    async def add_task(self, task: ScheduledTask) -> ScheduledTask:
        """Add a new scheduled task."""
        if self._started and not self._owns_lease():
            self._reload_shared_tasks()
        if task.id in self._tasks:
            raise ValueError(f"Task already exists: {task.id}")

        now = datetime.now(timezone.utc).isoformat()
        task.created_at = task.created_at or now
        task.updated_at = now

        self._tasks[task.id] = task

        # Register with APScheduler if active and scheduler is running
        if (task.status == TaskStatus.ACTIVE and task.trigger_type != TriggerType.EVENT
                and self._ap_scheduler and self._started):
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
        if self._started and not self._owns_lease():
            self._reload_shared_tasks()
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
                    if task.trigger_type == TriggerType.EVENT:
                        try:
                            await self._ap_scheduler.remove_schedule(task_id)
                        except Exception:
                            pass
                    else:
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
        if not self._started:
            self._reload_shared_tasks()
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
        if self._started and not self._owns_lease():
            self._reload_shared_tasks()
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        tag: str | None = None,
    ) -> list[ScheduledTask]:
        """List tasks with optional filters."""
        if self._started and not self._owns_lease():
            self._reload_shared_tasks()
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
        if self._started and not self._owns_lease():
            self._reload_shared_tasks()
            return False
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
