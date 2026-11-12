"""The plan-gate surface in /api/schedules' goal_progress payload."""

from __future__ import annotations

import json

import pytest

from atlas.engine.goals import GoalManager


class FakeTask:
    id = "task-1"
    goal = ""

    def to_dict(self):
        return {"id": self.id}


async def _noop(_task):
    return None


@pytest.fixture()
def _server(monkeypatch):
    from atlas.api import scheduling_router as sr

    monkeypatch.setattr(sr, "_server", lambda: type("S", (), {
        "_ensure_goal_migrated": staticmethod(_noop),
        "_goal_session_id": staticmethod(lambda _tid: "payload-session"),
    })())
    return sr


@pytest.fixture()
def manager(tmp_path):
    mgr = GoalManager("payload-session", home=tmp_path)
    return mgr


def _wire(monkeypatch, mgr):
    from atlas.engine import session_sync

    monkeypatch.setattr(
        session_sync, "goal_state",
        lambda _home, _sid: json.loads(mgr.state.to_json()),
    )


@pytest.mark.asyncio
async def test_fresh_goal_reports_needs_plan(_server, manager, monkeypatch):
    manager.set("refactor the scheduler")
    _wire(monkeypatch, manager)
    payload = await _server._goal_payload(FakeTask())
    progress = payload["goal_progress"]
    assert progress["needs_plan"] is True
    assert progress["decomposition_required"] is True
    assert progress["plan_attempts"] == 0
    assert progress["max_plan_attempts"] >= 1
    assert progress["completed_count"] == 0


@pytest.mark.asyncio
async def test_planned_goal_reports_progress(_server, manager, monkeypatch):
    manager.set("refactor the scheduler")
    manager.add_subgoal("extract the parser")
    manager.add_subgoal("wire the gate")
    manager.complete_subgoal(1)
    _wire(monkeypatch, manager)
    progress = (await _server._goal_payload(FakeTask()))["goal_progress"]
    assert progress["needs_plan"] is False
    assert progress["subgoals"] == ["extract the parser", "wire the gate"]
    assert progress["completed_subgoals"] == [1]
    assert progress["completed_count"] == 1


@pytest.mark.asyncio
async def test_gate_off_reports_no_plan_need(_server, manager, monkeypatch):
    manager.set("a one-line lookup")
    manager.state.decomposition_required = False
    manager._save()
    _wire(monkeypatch, manager)
    progress = (await _server._goal_payload(FakeTask()))["goal_progress"]
    assert progress["needs_plan"] is False
    assert progress["decomposition_required"] is False


@pytest.mark.asyncio
async def test_malformed_row_degrades_without_raising(_server, monkeypatch):
    from atlas.engine import session_sync

    monkeypatch.setattr(
        session_sync, "goal_state",
        lambda _home, _sid: {"goal": "legacy", "status": "active", "subgoals": "not-a-list"},
    )
    payload = await _server._goal_payload(FakeTask())
    assert payload["goal_progress"]["needs_plan"] is False


@pytest.mark.asyncio
async def test_no_goal_yields_empty_progress(_server, monkeypatch):
    from atlas.engine import session_sync

    monkeypatch.setattr(session_sync, "goal_state", lambda _home, _sid: None)
    payload = await _server._goal_payload(FakeTask())
    assert payload["goal_progress"] == {}
    assert payload["goal_status"] == "cleared"


@pytest.mark.asyncio
async def test_completed_count_ignores_out_of_range_indices(_server, manager, monkeypatch):
    manager.set("a goal")
    manager.add_subgoal("only milestone")
    manager.state.completed_subgoals = [1, 9, 42]
    manager._save()
    _wire(monkeypatch, manager)
    progress = (await _server._goal_payload(FakeTask()))["goal_progress"]
    assert progress["completed_count"] == 1


@pytest.mark.asyncio
async def test_plan_fields_reach_api_goals_over_http(tmp_path, monkeypatch):
    """The GoalsPanel reads /api/goals; guard the wire format it depends on."""
    from contextlib import asynccontextmanager

    import httpx

    from atlas.api.application import create_app
    from atlas.api.app_services import AppServices
    from atlas.engine import session_sync
    from atlas.scheduler import AtlasScheduler

    @asynccontextmanager
    async def _noop_lifespan():
        yield

    services = AppServices()
    services.scheduler = AtlasScheduler(schedules_path=tmp_path / "schedules.json")
    app = create_app(lifespan=_noop_lifespan, services=services)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atlas") as client:
        created = await client.post("/api/goals", json={
            "id": "goal-plan-surface",
            "name": "plan surface",
            "goal": "refactor the scheduler",
            "trigger_type": "interval",
            "trigger_args": {"minutes": 30},
        })
        assert created.status_code == 201, created.text
        session_id = created.json()["goal_session_id"]

        mgr = GoalManager(session_id, home=tmp_path)
        mgr.set("refactor the scheduler")
        monkeypatch.setattr(
            session_sync, "goal_state",
            lambda _home, _sid: json.loads(mgr.state.to_json()),
        )

        progress = (await client.get("/api/goals")).json()["goals"][0]["goal_progress"]
        assert progress["needs_plan"] is True
        assert progress["decomposition_required"] is True
        assert progress["plan_attempts"] == 0
        assert progress["max_plan_attempts"] >= 1
        assert progress["completed_count"] == 0

        mgr.add_subgoal("extract parser")
        mgr.add_subgoal("wire gate")
        mgr.complete_subgoal(1)
        progress = (await client.get("/api/goals")).json()["goals"][0]["goal_progress"]
        assert progress["needs_plan"] is False
        assert progress["subgoals"] == ["extract parser", "wire gate"]
        assert progress["completed_subgoals"] == [1]
        assert progress["completed_count"] == 1
