"""Read-only observability for scheduled triggers and Hermes-owned goals."""

from __future__ import annotations

from pathlib import Path

import httpx
from hermes_cli import goals as hermes_goals

from atlas import config, server
from atlas.engine.session_sync import (
    evaluate_goal_after_turn,
    goal_state,
    mutate_goal,
    record_goal_event,
    set_goal,
)
from atlas.scheduler import AtlasScheduler, ScheduledTask, TriggerType


def _goal_task(task_id: str = "review") -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name="Review",
        description="",
        trigger_type=TriggerType.INTERVAL,
        trigger_args={"hours": 1},
        action="goal",
    )


def _hermes_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    home = tmp_path / "engine"
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _goal_session_id(task_id: str) -> str:
    return f"scheduled-goal-{task_id}"


async def test_observability_snapshot_is_ordered_and_preserves_audit_provenance(
    tmp_path: Path, monkeypatch,
) -> None:
    home = _hermes_home(tmp_path, monkeypatch)
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    await scheduler.add_task(ScheduledTask(
        id="daily-summary",
        name="Daily summary",
        description="",
        trigger_type=TriggerType.INTERVAL,
        trigger_args={"hours": 24},
        action="agent:Summarize the project.",
    ))
    for task_id in ("z-review", "a-review"):
        await scheduler.add_task(_goal_task(task_id))
        set_goal(home, _goal_session_id(task_id), "Review the project.")

    monkeypatch.setattr(
        hermes_goals,
        "judge_goal",
        lambda *_args, **_kwargs: (
            "blocked", "provider unavailable", False, None, False,
        ),
    )
    evaluate_goal_after_turn(home, _goal_session_id("a-review"), "Unable to proceed.")
    record_goal_event(
        home, _goal_session_id("a-review"), "execution.error",
        {"detail": "provider unavailable"},
    )

    snapshot = scheduler.observability_snapshot()

    assert snapshot["scheduler_running"] is False
    assert snapshot["task_count"] == 3
    assert snapshot["active_task_count"] == 3
    assert snapshot["goal_count"] == 2
    assert snapshot["goal_status_counts"]["blocked"] == 1
    assert snapshot["goal_status_counts"]["pending"] == 1
    assert [item["goal_id"] for item in snapshot["goals"]] == ["a-review", "z-review"]
    assert snapshot["goal_event_counts"] == {"execution.error": 1}
    assert snapshot["goals"][0]["latest_event"]["event"] == "execution.error"
    assert snapshot["goals"][0]["latest_event"]["sequence"] == 0
    assert "detail" not in snapshot["goals"][0]["latest_event"]
    assert all("goal" not in item for item in snapshot["goals"])


async def test_observability_snapshot_recovers_persisted_events(
    tmp_path: Path, monkeypatch,
) -> None:
    home = _hermes_home(tmp_path, monkeypatch)
    path = tmp_path / "schedules.toml"
    first = AtlasScheduler(schedules_path=path)
    await first.add_task(_goal_task())
    set_goal(home, _goal_session_id("review"), "Review the project.")
    mutate_goal(home, _goal_session_id("review"), "pause", "user-paused")
    record_goal_event(home, _goal_session_id("review"), "goal.interrupted", {"source": "restart"})

    recovered = AtlasScheduler(schedules_path=path)
    await recovered.start()
    try:
        snapshot = recovered.observability_snapshot()
        assert snapshot["goal_status_counts"]["paused"] == 1
        assert snapshot["goal_event_counts"] == {"goal.interrupted": 1}
        assert snapshot["goals"][0]["goal_id"] == "review"
        assert snapshot["goals"][0]["latest_event"]["event"] == "goal.interrupted"
    finally:
        await recovered.stop()


async def test_goal_trace_endpoint_filters_and_orders_persisted_audit_events(
    tmp_path: Path, monkeypatch,
) -> None:
    home = _hermes_home(tmp_path, monkeypatch)
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    await scheduler.add_task(_goal_task())
    session_id = _goal_session_id("review")
    set_goal(home, session_id, "Review the project.")
    record_goal_event(home, session_id, "goal.triggered", {}, run_id="run-a")
    record_goal_event(
        home, session_id, "plan.updated", {"step_ids": ["inspect"]},
        run_id="run-a",
    )
    record_goal_event(home, session_id, "goal.triggered", {}, run_id="run-b")
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
    assert [event["event_id"] for event in trace["events"]] == [
        "scheduled-goal-review:0", "scheduled-goal-review:1",
    ]
    assert trace["events"][1]["data"]["step_ids"] == ["inspect"]


async def test_runtime_observability_reports_degraded_components_and_goal_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    home = _hermes_home(tmp_path, monkeypatch)

    class FailingOrchestrator:
        async def run(self, **kwargs):
            yield {"type": "error", "category": "model", "detail": "provider unavailable"}

    class ReflectionMemory:
        async def record_agent_reflection(self, **kwargs):
            return None

        async def record_goal_outcome(self, **kwargs):
            return None

    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    task = _goal_task()
    await scheduler.add_task(task)
    set_goal(home, _goal_session_id(task.id), "Review the project.")
    monkeypatch.setattr(server, "scheduler", scheduler)
    monkeypatch.setattr(server, "orchestrator", FailingOrchestrator())
    monkeypatch.setattr(server, "memory", ReflectionMemory())

    await server._run_scheduled_goal(task.id)

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        response = await client.get("/api/runtime/observability")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"] == {
        "scheduler": {"available": True, "running": False},
        "orchestrator": {"available": True},
        "memory": {"available": True},
    }
    assert goal_state(home, _goal_session_id(task.id))["status"] == "paused"
    assert body["autonomous"]["goal_event_counts"] == {
        "execution.error": 1,
        "goal.triggered": 1,
    }
    assert body["autonomous"]["goals"][0]["goal_id"] == "review"
