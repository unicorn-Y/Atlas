"""Goal-driven scheduled execution and recovery tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from atlas import server
from atlas.scheduler import AtlasScheduler, ScheduledTask, TriggerType


def _goal_task() -> ScheduledTask:
    return ScheduledTask(
        id="weekly-review",
        name="Weekly review",
        description="",
        trigger_type=TriggerType.INTERVAL,
        trigger_args={"hours": 1},
        action="agent:Review this week and list priorities.",
        goal="Review this week and list priorities.",
    )


async def test_goal_and_progress_survive_scheduler_restart(tmp_path: Path) -> None:
    path = tmp_path / "schedules.toml"
    first = AtlasScheduler(schedules_path=path)
    first_task = _goal_task()
    await first.add_task(first_task)
    await first.update_goal_state(
        first_task.id,
        status="running",
        progress={"goal": first_task.goal, "subtasks": []},
    )
    await first.record_goal_event(first_task.id, "plan.updated", {"count": 0})

    recovered = AtlasScheduler(schedules_path=path)
    resumed: list[str] = []
    resumed_event = asyncio.Event()

    async def resume_goal(task_id: str, message: str) -> None:
        resumed.append(task_id)
        await recovered.update_goal_state(task_id, status="running")
        resumed_event.set()

    recovered._agent_callback = resume_goal
    recovered.GOAL_HEARTBEAT_SECONDS = 0.01
    await recovered.start()
    try:
        task = recovered.get_task(first_task.id)
        assert task is not None
        assert task.goal == first_task.goal
        assert task.goal_status == "interrupted"
        assert task.goal_progress == {"goal": first_task.goal, "subtasks": []}
        assert any(event["event"] == "goal.interrupted" for event in task.goal_events)

        await asyncio.wait_for(resumed_event.wait(), timeout=2)
        assert resumed == [first_task.id]
        assert task.goal_status == "running"
    finally:
        await recovered.stop()


async def test_goal_api_creates_durable_scheduled_goal(tmp_path: Path, monkeypatch) -> None:
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    monkeypatch.setattr(server, "scheduler", scheduler)

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        response = await client.post("/api/goals", json={
            "id": "weekly-review",
            "name": "Weekly review",
            "goal": "Review this week and list priorities.",
            "trigger_type": "interval",
            "trigger_args": {"hours": 1},
        })

    assert response.status_code == 201
    assert response.json()["goal_status"] == "pending"
    recovered = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    assert recovered.get_task("weekly-review") is None
    await recovered.start()
    try:
        task = recovered.get_task("weekly-review")
        assert task is not None
        assert task.goal == "Review this week and list priorities."
    finally:
        await recovered.stop()


async def test_goal_trigger_persists_plan_and_denies_unapproved_tool(
    tmp_path: Path, monkeypatch,
) -> None:
    class FakeOrchestrator:
        approval_choice = None

        async def run(self, **kwargs):
            assert kwargs["force_plan"] is True
            await kwargs["plan_update_callback"]({
                "goal": kwargs["message"],
                "subtasks": [{
                    "id": "inspect", "title": "Inspect", "verification": "Files inspected",
                    "status": "pending",
                }],
            })
            self.approval_choice = await kwargs["approval_callback"](
                "approval:test", "delete_file", {"path": "important.txt"}
            )
            yield {"type": "done"}

    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    task = _goal_task()

    async def run_goal(task_id: str, message: str) -> None:
        await server._run_scheduled_goal(task_id, message)

    scheduler._agent_callback = run_goal
    monkeypatch.setattr(server, "scheduler", scheduler)
    orchestrator = FakeOrchestrator()
    monkeypatch.setattr(server, "orchestrator", orchestrator)

    await scheduler.add_task(task)
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        response = await client.post(f"/api/goals/{task.id}/run")

    assert response.status_code == 200
    assert any(event["event"] == "goal.triggered" for event in task.goal_events)
    assert orchestrator.approval_choice == "deny"
    assert task.goal_status == "awaiting_approval"
    assert task.goal_progress["subtasks"][0]["status"] == "pending"
    assert task.goal_progress["blocked"] is True
    assert any(event["event"] == "approval.required" for event in task.goal_events)


async def test_goal_heartbeat_continues_pending_and_interrupted_goals(tmp_path: Path) -> None:
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    called: list[str] = []

    async def callback(task_id: str, message: str) -> None:
        called.append(task_id)
        await scheduler.update_goal_state(task_id, status="running")

    scheduler._agent_callback = callback
    for task_id, status in (
        ("pending", "pending"),
        ("interrupted", "interrupted"),
        ("completed", "completed"),
        ("approval", "awaiting_approval"),
    ):
        task = _goal_task()
        task.id = task_id
        task.goal_status = status
        await scheduler.add_task(task)

    assert await scheduler.heartbeat_goals() == 2
    assert called == ["interrupted", "pending"]
    assert scheduler.get_task("pending").goal_status == "running"
    assert scheduler.get_task("interrupted").goal_status == "running"


async def test_goal_execution_tracks_steps_and_only_completes_verified_plan(
    tmp_path: Path, monkeypatch,
) -> None:
    class FakeOrchestrator:
        async def run(self, **kwargs):
            assert kwargs["force_plan"] is True
            assert kwargs["plan_state"] is None
            await kwargs["plan_update_callback"]({
                "goal": kwargs["message"],
                "subtasks": [{
                    "id": "inspect", "title": "Inspect", "verification": "Files inspected",
                    "status": "completed", "evidence": "README reviewed",
                }, {
                    "id": "summarize", "title": "Summarize", "verification": "Summary exists",
                }],
            })
            yield {"type": "done"}

    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    task = _goal_task()
    task.goal_progress = {"goal": task.goal, "subtasks": []}
    await scheduler.add_task(task)
    scheduler._agent_callback = lambda task_id, message: server._run_scheduled_goal(
        task_id, message,
    )
    monkeypatch.setattr(server, "scheduler", scheduler)
    monkeypatch.setattr(server, "orchestrator", FakeOrchestrator())

    await server._run_scheduled_goal(task.id, task.goal)

    assert task.goal_status == "pending"
    assert task.goal_progress["current_step"] == "summarize"
    assert task.goal_progress["completed_steps"] == ["inspect"]
    assert any(event["event"] == "goal.continuation_pending" for event in task.goal_events)


async def test_goal_completes_only_after_each_step_has_verification_evidence(
    tmp_path: Path, monkeypatch,
) -> None:
    class VerifiedOrchestrator:
        async def run(self, **kwargs):
            await kwargs["plan_update_callback"]({
                "goal": kwargs["message"],
                "subtasks": [{
                    "id": "inspect", "title": "Inspect", "verification": "Files inspected",
                    "status": "completed", "evidence": "README reviewed",
                }, {
                    "id": "summarize", "title": "Summarize", "verification": "Summary exists",
                    "status": "completed", "evidence": "Summary saved",
                }],
            })
            yield {"type": "done"}

    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    task = _goal_task()
    await scheduler.add_task(task)
    monkeypatch.setattr(server, "scheduler", scheduler)
    monkeypatch.setattr(server, "orchestrator", VerifiedOrchestrator())

    await server._run_scheduled_goal(task.id, task.goal)

    assert task.goal_status == "completed"
    assert task.goal_progress["current_step"] is None
    assert task.goal_progress["completed_steps"] == ["inspect", "summarize"]
    assert any(event["event"] == "goal.verified" for event in task.goal_events)


async def test_goal_failure_is_reflected_and_blocks_until_requested_retry(
    tmp_path: Path, monkeypatch,
) -> None:
    class FailingOrchestrator:
        async def run(self, **kwargs):
            yield {"type": "error", "category": "model", "detail": "provider unavailable"}

    class ReflectionMemory:
        calls: list[dict] = []

        async def record_agent_reflection(self, **kwargs):
            self.calls.append(kwargs)

    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    task = _goal_task()
    await scheduler.add_task(task)
    reflection_memory = ReflectionMemory()
    monkeypatch.setattr(server, "scheduler", scheduler)
    monkeypatch.setattr(server, "orchestrator", FailingOrchestrator())
    monkeypatch.setattr(server, "memory", reflection_memory)

    await server._run_scheduled_goal(task.id, task.goal)

    assert task.goal_status == "blocked"
    assert task.goal_progress["blocked"] is True
    assert len(reflection_memory.calls) == 1
    assert reflection_memory.calls[0]["category"] == "model"
    assert reflection_memory.calls[0]["component"] == "goal_scheduler"
    assert task.goal_progress["reflection_run_ids"]


async def test_manual_goal_retry_unblocks_a_failed_goal(tmp_path: Path, monkeypatch) -> None:
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    task = _goal_task()
    task.goal_status = "blocked"
    task.goal_progress = {"blocked": True, "blocked_reason": "execution_error"}
    await scheduler.add_task(task)
    monkeypatch.setattr(server, "scheduler", scheduler)

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        response = await client.post(f"/api/goals/{task.id}/run")

    assert response.status_code == 200
    assert task.goal_status == "pending"
    assert task.goal_progress["blocked"] is False
    assert any(event["event"] == "goal.retry_requested" for event in task.goal_events)
