"""Tests for the AtlasScheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from atlas.scheduler import (
    AtlasScheduler,
    ScheduledTask,
    TaskStatus,
    TriggerType,
    _load_tasks_from_toml,
    _make_trigger,
    _save_tasks_to_toml,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(
    task_id: str = "test-task",
    name: str = "Test Task",
    description: str = "A test task",
    trigger_type: TriggerType = TriggerType.CRON,
    trigger_args: dict[str, Any] | None = None,
    action: str = "agent:hello world",
    status: TaskStatus = TaskStatus.ACTIVE,
    tags: list[str] | None = None,
) -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name=name,
        description=description,
        trigger_type=trigger_type,
        trigger_args=trigger_args or {"hour": "9", "minute": "0"},
        action=action,
        status=status,
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# ScheduledTask data model
# ---------------------------------------------------------------------------

class TestScheduledTask:
    def test_to_dict(self) -> None:
        task = _make_task(tags=["daily", "news"])
        d = task.to_dict()
        assert d["id"] == "test-task"
        assert d["name"] == "Test Task"
        assert d["trigger_type"] == "cron"
        assert d["status"] == "active"
        assert d["tags"] == ["daily", "news"]

    def test_from_dict(self) -> None:
        d = {
            "id": "from-dict",
            "name": "From Dict",
            "description": "Created from dict",
            "trigger_type": "interval",
            "trigger_args": {"hours": 2},
            "action": "agent:check stuff",
            "status": "paused",
            "tags": ["test"],
            "created_at": "2026-01-01T00:00:00",
            "run_count": 5,
        }
        task = ScheduledTask.from_dict(d)
        assert task.id == "from-dict"
        assert task.trigger_type == TriggerType.INTERVAL
        assert task.status == TaskStatus.PAUSED
        assert task.run_count == 5

    def test_from_dict_defaults(self) -> None:
        d = {"id": "minimal", "name": "Minimal"}
        task = ScheduledTask.from_dict(d)
        assert task.trigger_type == TriggerType.CRON
        assert task.status == TaskStatus.ACTIVE
        assert task.tags == []
        assert task.run_count == 0

    def test_roundtrip(self) -> None:
        original = _make_task(
            task_id="roundtrip",
            tags=["a", "b"],
        )
        original.created_at = "2026-01-01T00:00:00"
        original.run_count = 3
        restored = ScheduledTask.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.trigger_type == original.trigger_type
        assert restored.run_count == original.run_count


# ---------------------------------------------------------------------------
# Trigger factory
# ---------------------------------------------------------------------------

class TestTriggerFactory:
    def test_cron_trigger(self) -> None:
        trigger = _make_trigger(
            TriggerType.CRON, {"hour": "9", "minute": "30"}
        )
        from apscheduler.triggers.cron import CronTrigger
        assert isinstance(trigger, CronTrigger)

    def test_interval_trigger(self) -> None:
        trigger = _make_trigger(
            TriggerType.INTERVAL, {"hours": 2, "minutes": 15}
        )
        from apscheduler.triggers.interval import IntervalTrigger
        assert isinstance(trigger, IntervalTrigger)

    def test_date_trigger(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        trigger = _make_trigger(
            TriggerType.DATE, {"run_time": future}
        )
        from apscheduler.triggers.date import DateTrigger
        assert isinstance(trigger, DateTrigger)

    def test_unknown_trigger(self) -> None:
        with pytest.raises(ValueError, match="Unknown trigger type"):
            _make_trigger("bogus", {})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TOML persistence
# ---------------------------------------------------------------------------

class TestTOMLPersistence:
    def test_save_and_load(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.toml"
        tasks = {
            "daily-news": _make_task(
                task_id="daily-news",
                name="Daily News",
                description="Fetch daily news",
                tags=["news"],
            ),
            "weekly-report": _make_task(
                task_id="weekly-report",
                name="Weekly Report",
                trigger_args={"day_of_week": "mon", "hour": "10"},
                tags=["report"],
            ),
        }
        tasks["daily-news"].created_at = "2026-01-01T00:00:00"
        tasks["daily-news"].run_count = 42

        _save_tasks_to_toml(path, tasks)
        assert path.exists()

        loaded = _load_tasks_from_toml(path)
        assert len(loaded) == 2
        assert loaded["daily-news"].name == "Daily News"
        assert loaded["daily-news"].run_count == 42
        assert loaded["weekly-report"].trigger_args["day_of_week"] == "mon"

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        loaded = _load_tasks_from_toml(tmp_path / "nope.toml")
        assert loaded == {}

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "dir" / "schedules.toml"
        _save_tasks_to_toml(path, {"t": _make_task()})
        assert path.exists()

    def test_save_escapes_special_chars(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.toml"
        task = _make_task(
            name='Task with "quotes" inside',
            description="Line1\nLine2",
        )
        _save_tasks_to_toml(path, {task.id: task})
        loaded = _load_tasks_from_toml(path)
        assert loaded[task.id].name == 'Task with "quotes" inside'
        assert loaded[task.id].description == "Line1\nLine2"


# ---------------------------------------------------------------------------
# AtlasScheduler — no APScheduler running (unit tests)
# ---------------------------------------------------------------------------

class TestSchedulerNoAPScheduler:
    """Test scheduler CRUD without starting APScheduler backend."""

    @pytest.fixture
    def scheduler(self, tmp_path: Path) -> AtlasScheduler:
        return AtlasScheduler(schedules_path=tmp_path / "schedules.toml")

    async def test_add_and_get(self, scheduler: AtlasScheduler) -> None:
        task = _make_task()
        result = await scheduler.add_task(task)
        assert result.id == "test-task"
        assert result.created_at != ""  # auto-set

        got = scheduler.get_task("test-task")
        assert got is not None
        assert got.name == "Test Task"

    async def test_add_duplicate_raises(self, scheduler: AtlasScheduler) -> None:
        await scheduler.add_task(_make_task())
        with pytest.raises(ValueError, match="already exists"):
            await scheduler.add_task(_make_task())

    async def test_list_tasks(self, scheduler: AtlasScheduler) -> None:
        await scheduler.add_task(_make_task(task_id="a"))
        await scheduler.add_task(_make_task(task_id="b", status=TaskStatus.PAUSED))
        await scheduler.add_task(_make_task(task_id="c", tags=["news"]))

        all_tasks = scheduler.list_tasks()
        assert len(all_tasks) == 3

        active = scheduler.list_tasks(status=TaskStatus.ACTIVE)
        assert len(active) == 2

        tagged = scheduler.list_tasks(tag="news")
        assert len(tagged) == 1
        assert tagged[0].id == "c"

    async def test_update_task(self, scheduler: AtlasScheduler) -> None:
        await scheduler.add_task(_make_task())
        result = await scheduler.update_task(
            "test-task",
            name="Updated Name",
            status=TaskStatus.PAUSED,
        )
        assert result is not None
        assert result.name == "Updated Name"
        assert result.status == TaskStatus.PAUSED

    async def test_update_nonexistent(self, scheduler: AtlasScheduler) -> None:
        result = await scheduler.update_task("nope", name="x")
        assert result is None

    async def test_delete_task(self, scheduler: AtlasScheduler) -> None:
        await scheduler.add_task(_make_task())
        assert scheduler.task_count == 1
        deleted = await scheduler.delete_task("test-task")
        assert deleted is True
        assert scheduler.task_count == 0

    async def test_delete_nonexistent(self, scheduler: AtlasScheduler) -> None:
        assert await scheduler.delete_task("nope") is False

    async def test_counts(self, scheduler: AtlasScheduler) -> None:
        await scheduler.add_task(_make_task(task_id="a"))
        await scheduler.add_task(_make_task(task_id="b", status=TaskStatus.PAUSED))
        assert scheduler.task_count == 2
        assert scheduler.active_count == 1

    async def test_persistence(self, tmp_path: Path) -> None:
        """Tasks survive scheduler recreation."""
        path = tmp_path / "schedules.toml"

        s1 = AtlasScheduler(schedules_path=path)
        await s1.add_task(_make_task(task_id="persist-me"))
        assert path.exists()

        # New scheduler instance loads from same file
        s2 = AtlasScheduler(schedules_path=path)
        # Manually load since we didn't call start()
        s2._tasks = _load_tasks_from_toml(path)
        assert s2.get_task("persist-me") is not None


# ---------------------------------------------------------------------------
# AtlasScheduler — with APScheduler running (integration)
# ---------------------------------------------------------------------------

class TestSchedulerWithAPScheduler:
    """Integration tests that actually start/stop the APScheduler."""

    async def test_start_stop(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.toml"
        scheduler = AtlasScheduler(schedules_path=path)
        await scheduler.start()
        assert scheduler._started is True
        await scheduler.stop()
        assert scheduler._started is False

    async def test_start_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.toml"
        scheduler = AtlasScheduler(schedules_path=path)
        await scheduler.start()
        await scheduler.start()  # should not raise
        assert scheduler._started is True
        await scheduler.stop()

    async def test_add_task_while_running(self, tmp_path: Path) -> None:
        fired: list[str] = []

        async def callback(task_id: str, message: str) -> None:
            fired.append(f"{task_id}:{message}")

        path = tmp_path / "schedules.toml"
        scheduler = AtlasScheduler(
            schedules_path=path,
            agent_callback=callback,
        )
        await scheduler.start()

        try:
            await scheduler.add_task(_make_task(
                task_id="interval-test",
                trigger_type=TriggerType.INTERVAL,
                trigger_args={"seconds": 0.5},
                action="agent:hello scheduler",
            ))

            # Wait for at least one fire
            await asyncio.sleep(1.5)
            assert len(fired) >= 1
            assert fired[0] == "interval-test:hello scheduler"

            # Verify run_count updated
            task = scheduler.get_task("interval-test")
            assert task is not None
            assert task.run_count >= 1
            assert task.last_run_at != ""

        finally:
            await scheduler.stop()

    async def test_pause_resume(self, tmp_path: Path) -> None:
        fired: list[str] = []

        async def callback(task_id: str, message: str) -> None:
            fired.append(task_id)

        path = tmp_path / "schedules.toml"
        scheduler = AtlasScheduler(
            schedules_path=path,
            agent_callback=callback,
        )
        await scheduler.start()

        try:
            await scheduler.add_task(_make_task(
                task_id="pause-test",
                trigger_type=TriggerType.INTERVAL,
                trigger_args={"seconds": 0.3},
                action="agent:test",
            ))

            # Let it fire once
            await asyncio.sleep(0.8)
            count_before_pause = len(fired)
            assert count_before_pause >= 1

            # Pause
            await scheduler.update_task("pause-test", status=TaskStatus.PAUSED)
            fired.clear()
            await asyncio.sleep(0.8)
            assert len(fired) == 0  # should not fire while paused

            # Resume
            await scheduler.update_task("pause-test", status=TaskStatus.ACTIVE)
            await asyncio.sleep(0.8)
            assert len(fired) >= 1  # should fire again

        finally:
            await scheduler.stop()

    async def test_run_now(self, tmp_path: Path) -> None:
        fired: list[str] = []

        async def callback(task_id: str, message: str) -> None:
            fired.append(f"{task_id}:{message}")

        path = tmp_path / "schedules.toml"
        scheduler = AtlasScheduler(
            schedules_path=path,
            agent_callback=callback,
        )
        await scheduler.start()

        try:
            # Add a task with a far-future cron (won't auto-fire)
            await scheduler.add_task(_make_task(
                task_id="manual-test",
                trigger_type=TriggerType.CRON,
                trigger_args={"year": "2099"},
                action="agent:manual fire",
            ))

            result = await scheduler.run_now("manual-test")
            assert result is True

            # Give the job executor a moment
            await asyncio.sleep(0.5)
            assert len(fired) >= 1
            assert fired[0] == "manual-test:manual fire"

        finally:
            await scheduler.stop()

    async def test_delete_while_running(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.toml"
        scheduler = AtlasScheduler(schedules_path=path)
        await scheduler.start()

        try:
            await scheduler.add_task(_make_task(
                task_id="del-test",
                trigger_type=TriggerType.INTERVAL,
                trigger_args={"seconds": 60},
            ))
            assert scheduler.task_count == 1

            deleted = await scheduler.delete_task("del-test")
            assert deleted is True
            assert scheduler.task_count == 0

        finally:
            await scheduler.stop()

    async def test_run_now_nonexistent(self, tmp_path: Path) -> None:
        path = tmp_path / "schedules.toml"
        scheduler = AtlasScheduler(schedules_path=path)
        await scheduler.start()
        try:
            assert await scheduler.run_now("nope") is False
        finally:
            await scheduler.stop()
