"""Read-only runtime observability for autonomous goal execution."""

from __future__ import annotations

from pathlib import Path

import httpx

from atlas import server
from atlas.scheduler import AtlasScheduler, ScheduledTask, TriggerType


def _goal_task(task_id: str = "review") -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name="Review",
        description="",
        trigger_type=TriggerType.INTERVAL,
        trigger_args={"hours": 1},
        action="agent:Review the project.",
        goal="Review the project.",
    )


async def test_observability_snapshot_is_ordered_and_preserves_audit_provenance(
    tmp_path: Path,
) -> None:
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    for task in (_goal_task("z-review"), _goal_task("a-review")):
        await scheduler.add_task(task)
    await scheduler.update_goal_state("a-review", status="blocked")
    await scheduler.record_goal_event(
        "a-review", "execution.error", {"detail": "provider unavailable"},
    )

    snapshot = scheduler.observability_snapshot()

    assert snapshot["scheduler_running"] is False
    assert snapshot["goal_count"] == 2
    assert snapshot["goal_status_counts"]["blocked"] == 1
    assert snapshot["goal_status_counts"]["pending"] == 1
    assert [item["goal_id"] for item in snapshot["goals"]] == ["a-review", "z-review"]
    assert snapshot["goal_event_counts"] == {"execution.error": 1}
    assert snapshot["goals"][0]["latest_event"]["event"] == "execution.error"
    assert snapshot["goals"][0]["latest_event"]["sequence"] == 0
    assert "detail" not in snapshot["goals"][0]["latest_event"]
    assert all("goal" not in item for item in snapshot["goals"])


async def test_observability_snapshot_recovers_persisted_events(tmp_path: Path) -> None:
    path = tmp_path / "schedules.toml"
    first = AtlasScheduler(schedules_path=path)
    await first.add_task(_goal_task())
    await first.update_goal_state("review", status="interrupted")
    await first.record_goal_event("review", "goal.interrupted", {"source": "restart"})

    recovered = AtlasScheduler(schedules_path=path)
    await recovered.start()
    try:
        snapshot = recovered.observability_snapshot()
        assert snapshot["goal_status_counts"]["interrupted"] == 1
        assert snapshot["goal_event_counts"] == {"goal.interrupted": 1}
        assert snapshot["goals"][0]["goal_id"] == "review"
        assert snapshot["goals"][0]["latest_event"]["event"] == "goal.interrupted"
    finally:
        await recovered.stop()


async def test_goal_trace_endpoint_filters_and_orders_persisted_audit_events(
    tmp_path: Path, monkeypatch,
) -> None:
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    await scheduler.add_task(_goal_task())
    await scheduler.record_goal_event("review", "goal.triggered", {}, run_id="run-a")
    await scheduler.record_goal_event(
        "review", "plan.updated", {"step_ids": ["inspect"]},
        run_id="run-a", plan_id="plan-a",
    )
    await scheduler.record_goal_event("review", "goal.triggered", {}, run_id="run-b")
    monkeypatch.setattr(server, "scheduler", scheduler)

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        first = await client.get("/api/goals/review/trace", params={"run_id": "run-a"})
        second = await client.get("/api/goals/review/trace", params={"run_id": "run-a"})

    assert first.status_code == 200
    assert first.json() == second.json()
    trace = first.json()
    assert trace["goal_id"] == "review"
    assert [event["sequence"] for event in trace["events"]] == [0, 1]
    assert [event["event_id"] for event in trace["events"]] == ["review:0", "review:1"]
    assert trace["events"][1]["plan_id"] == "plan-a"


async def test_runtime_observability_reports_degraded_components_and_goal_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    class FailingOrchestrator:
        async def run(self, **kwargs):
            yield {"type": "error", "category": "model", "detail": "provider unavailable"}

    class ReflectionMemory:
        async def record_agent_reflection(self, **kwargs):
            return None

    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    task = _goal_task()
    await scheduler.add_task(task)
    monkeypatch.setattr(server, "scheduler", scheduler)
    monkeypatch.setattr(server, "orchestrator", FailingOrchestrator())
    monkeypatch.setattr(server, "memory", ReflectionMemory())

    await server._run_scheduled_goal(task.id, task.goal)

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        response = await client.get("/api/runtime/observability")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert scheduler.get_task("review").goal_status == "blocked"
    assert body["components"] == {
        "scheduler": {"available": True, "running": False},
        "orchestrator": {"available": True},
        "memory": {"available": True},
    }
    assert body["autonomous"]["goal_event_counts"] == {
        "execution.error": 1,
        "goal.triggered": 1,
    }
    assert body["autonomous"]["goals"][0]["goal_id"] == "review"
