"""Goal-driven scheduled execution and recovery tests."""

from __future__ import annotations

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
    await recovered.start()
    try:
        task = recovered.get_task(first_task.id)
        assert task is not None
        assert task.goal == first_task.goal
        assert task.goal_status == "interrupted"
        assert task.goal_progress == {"goal": first_task.goal, "subtasks": []}
        assert any(event["event"] == "goal.interrupted" for event in task.goal_events)
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
            await kwargs["plan_update_callback"]({
                "goal": kwargs["message"],
                "subtasks": [{"id": "inspect", "status": "pending"}],
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
    assert any(event["event"] == "approval.required" for event in task.goal_events)
