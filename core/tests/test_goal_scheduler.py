"""Focused Automation-to-Hermes GoalManager integration tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from atlas import config, server
from atlas.engine.session_sync import goal_command, goal_events, goal_state, mutate_goal
from atlas.scheduler import AtlasScheduler, TaskStatus


def _isolate_goal_home(tmp_path: Path, monkeypatch) -> Path:
    data_root = tmp_path / "atlas-data"
    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("ATLAS_DATA_DIR", str(data_root))
    monkeypatch.setattr(config, "DATA_ROOT", data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    return data_root / "engine"


@pytest.mark.asyncio
async def test_automation_and_chat_share_goal_pause_resume_replace_and_clear(
    tmp_path: Path, monkeypatch,
) -> None:
    home = _isolate_goal_home(tmp_path, monkeypatch)
    scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.toml")
    monkeypatch.setattr(server, "scheduler", scheduler)
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        payload = {
            "id": "weekly-review", "name": "Weekly review",
            "goal": "Review this week and list priorities.",
            "trigger_type": "interval", "trigger_args": {"hours": 1},
        }
        created = await client.post("/api/goals", json=payload)
        assert created.status_code == 201
        session_id = "scheduled-goal-weekly-review"
        assert created.json()["goal_status"] == "active"
        assert goal_state(home, session_id)["goal"] == payload["goal"]

        paused = await client.post("/api/goals/weekly-review/pause")
        assert paused.json()["goal_status"] == "paused"
        assert goal_command(home, session_id, "status")["goal"]["status"] == "paused"
        goal_command(home, session_id, "resume")
        assert (await client.get("/api/goals/weekly-review")).json()["goal_status"] == "active"
        assert scheduler.get_task("weekly-review").status == TaskStatus.ACTIVE

        goal_command(home, session_id, "pause")
        resumed = await client.post("/api/goals/weekly-review/resume")
        assert resumed.json()["goal_status"] == "active"
        goal_command(home, session_id, "A goal replaced from chat.")
        assert (await client.get("/api/goals/weekly-review")).json()["goal"] == "A goal replaced from chat."
        replaced = await client.put("/api/goals/weekly-review", json={"goal": "Review next week."})
        assert replaced.json()["goal"] == "Review next week."
        assert goal_state(home, session_id)["goal"] == "Review next week."
        assert "goal_status" not in scheduler.get_task("weekly-review").to_dict()

        goal_command(home, session_id, "clear")
        assert (await client.get("/api/goals/weekly-review")).json()["goal_status"] == "cleared"
        assert goal_command(home, session_id, "status")["goal"]["status"] == "cleared"
        trace = await client.get("/api/goals/weekly-review/trace")
        names = [item["event"] for item in trace.json()["events"]]
        assert names == [
            "goal.created", "goal.paused", "goal.resumed", "goal.paused", "goal.resumed",
            "goal.replaced", "goal.replaced", "goal.cleared",
        ], names
        cleared = await client.delete("/api/goals/weekly-review")
        assert cleared.json()["status"] == "cleared"


@pytest.mark.asyncio
async def test_scheduled_trigger_uses_hermes_continuation_and_evaluation(
    tmp_path: Path, monkeypatch,
) -> None:
    home = _isolate_goal_home(tmp_path, monkeypatch)
    scheduler = AtlasScheduler(
        schedules_path=tmp_path / "schedules.toml", agent_callback=server._scheduled_goal,
    )
    monkeypatch.setattr(server, "scheduler", scheduler)
    monkeypatch.setattr(server, "memory", None)
    prompts: list[str] = []

    class FakeOrchestrator:
        async def run(self, **kwargs):
            prompts.append(kwargs["message"])
            assert kwargs["conversation_id"] == "scheduled-goal-weekly-review"
            assert await kwargs["approval_callback"]("approval:test", "delete_file", {}) == "deny"
            yield {"type": "chunk", "content": f"Response to: {kwargs['message']}"}
            yield {"type": "done", "message_id": f"assistant-{len(prompts)}", "model": "fake"}

    monkeypatch.setattr(server, "orchestrator", FakeOrchestrator())
    import hermes_cli.goals as hermes_goals
    verdicts = iter([
        ("continue", "Continue with the next concrete step.", False, None, False),
        ("done", "The review is complete.", False, None, False),
    ])
    monkeypatch.setattr(hermes_goals, "judge_goal", lambda *_args, **_kwargs: next(verdicts))

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        created = await client.post("/api/goals", json={
            "id": "weekly-review", "name": "Weekly review",
            "goal": "Review this week and list priorities.",
            "trigger_type": "interval", "trigger_args": {"hours": 1},
        })
        assert created.status_code == 201
        response = await client.post("/api/goals/weekly-review/run")
        assert response.status_code == 200
        state = goal_state(home, "scheduled-goal-weekly-review")
        assert len(prompts) == 2
        assert prompts[0] == "Review this week and list priorities."
        assert prompts[1].startswith("[Continuing toward your standing goal]")
        assert "Goal: Review this week and list priorities." in prompts[1]
        assert state["status"] == "done"
        assert state["turns_used"] == 2
        assert state["last_verdict"] == "done"
        assert state["last_reason"] == "The review is complete."
        trace = await client.get("/api/goals/weekly-review/trace")
        assert [item["event"] for item in trace.json()["events"]] == [
            "goal.created", "goal.triggered", "goal.evaluated", "goal.evaluated",
        ]


@pytest.mark.asyncio
async def test_legacy_schedule_imports_once_and_clear_does_not_resurrect(
    tmp_path: Path, monkeypatch,
) -> None:
    home = _isolate_goal_home(tmp_path, monkeypatch)
    path = tmp_path / "schedules.toml"
    path.write_text(
        '[tasks.legacy-review]\n'
        'name = "Legacy review"\n'
        'description = ""\n'
        'trigger_type = "interval"\n'
        'action = "agent:Review the archive."\n'
        'status = "paused"\n'
        'goal = "Review the archive."\n'
        'goal_status = "running"\n'
        'goal_progress_json = "{\\"turns_used\\":8}"\n'
        'goal_events_json = "[]"\n'
        'trigger_args_json = "{\\"hours\\":1}"\n'
        'runs_json = "[]"\n',
        encoding="utf-8",
    )
    scheduler = AtlasScheduler(schedules_path=path)
    await scheduler.start()
    await scheduler.stop()
    scheduler = AtlasScheduler(schedules_path=path)
    await scheduler.start()
    assert scheduler.get_task("legacy-review").legacy_goal == "Review the archive."
    monkeypatch.setattr(server, "scheduler", scheduler)
    transport = httpx.ASGITransport(app=server.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
            listed = await client.get("/api/goals")
            goal = listed.json()["goals"][0]
            assert goal["goal"] == "Review the archive."
            assert goal["goal_status"] == "paused"
            assert scheduler.get_task("legacy-review").action == "goal"
            assert scheduler.get_task("legacy-review").legacy_goal == ""
            stored = path.read_text(encoding="utf-8")
            assert "goal_status" not in stored
            assert "goal_progress_json" not in stored
            assert "goal_events_json" not in stored

            mutate_goal(home, "scheduled-goal-legacy-review", "clear")
            await scheduler.stop()
            recovered = AtlasScheduler(schedules_path=path)
            await recovered.start()
            monkeypatch.setattr(server, "scheduler", recovered)
            refreshed = await client.get("/api/goals")
            assert refreshed.json()["goals"][0]["goal_status"] == "cleared"
            assert refreshed.json()["goals"][0]["goal"] == "Review the archive."
            assert goal_state(home, "scheduled-goal-legacy-review")["status"] == "cleared"
            events = goal_events(home, "scheduled-goal-legacy-review")
            assert [item["sequence"] for item in events] == sorted(item["sequence"] for item in events)
            assert [item["event"] for item in events] == ["goal.created"]
    finally:
        current = server.scheduler
        if current is not None:
            await current.stop()
