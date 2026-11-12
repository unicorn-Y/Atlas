"""Tests for the stranded-goal HTTP surface."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.api.application import create_app


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Point DATA_ROOT at a temp dir so tests never touch the real state.db."""
    import atlas.api.goal_loop_router as router_module

    monkeypatch.setattr(router_module, "_engine_home", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def client():
    app = create_app(lifespan=_noop_lifespan, services=AppServices())
    return TestClient(app)


def _seed(home, session_id: str, **kwargs):
    from atlas.engine.goals import GoalManager

    manager = GoalManager(session_id, home=home)
    manager.set(kwargs.pop("goal", "ship it"))
    for text in kwargs.pop("subgoals", []):
        manager.add_subgoal(text)
    for index in kwargs.pop("complete", []):
        manager.complete_subgoal(index)
    return manager


def test_stranded_empty_when_no_goals(home, client):
    got = client.get("/api/engine-goals/stranded")
    assert got.status_code == 200
    body = got.json()
    assert body["goals"] == []
    assert body["summary"]["resumable"] == 0


def test_stranded_lists_active_goal(home, client):
    _seed(home, "s1", subgoals=["a", "b"], complete=[1])
    body = client.get("/api/engine-goals/stranded").json()
    assert len(body["goals"]) == 1
    assert body["goals"][0]["session_id"] == "s1"
    assert body["goals"][0]["remaining_subgoals"] == ["b"]


def test_stranded_skips_paused_goal(home, client):
    manager = _seed(home, "s1")
    manager.pause()
    assert client.get("/api/engine-goals/stranded").json()["goals"] == []


def test_resume_returns_prompt(home, client):
    _seed(home, "s1", subgoals=["a", "b"], complete=[1])
    got = client.post("/api/engine-goals/resume", json={"session_id": "s1"})
    assert got.status_code == 200
    body = got.json()
    assert body["session_id"] == "s1"
    assert "b" in body["continuation_prompt"]
    assert "[Working toward this goal]" in body["continuation_prompt"]


def test_resume_unknown_session_is_404(home, client):
    got = client.post("/api/engine-goals/resume", json={"session_id": "nope"})
    assert got.status_code == 404
    assert "nope" in got.json()["detail"]


def test_resume_paused_goal_is_404(home, client):
    """A paused goal is not in the resumable list, so resume must refuse it."""
    manager = _seed(home, "s1")
    manager.pause()
    got = client.post("/api/engine-goals/resume", json={"session_id": "s1"})
    assert got.status_code == 404


def test_resume_requires_session_id(home, client):
    got = client.post("/api/engine-goals/resume", json={"session_id": ""})
    assert got.status_code == 422


def test_resume_does_not_mutate_goal(home, client):
    """Handing back a prompt must not spend a turn or change status."""
    from atlas.engine.goals import GoalManager

    manager = _seed(home, "s1", subgoals=["a"])
    before = manager.state.turns_used
    client.post("/api/engine-goals/resume", json={"session_id": "s1"})
    after = GoalManager("s1", home=home).state
    assert after.turns_used == before
    assert after.status == "active"


def test_stranded_summary_counts_multiple(home, client):
    _seed(home, "s1", subgoals=["a"])
    _seed(home, "s2", subgoals=["b"], complete=[1])
    summary = client.get("/api/engine-goals/stranded").json()["summary"]
    assert summary["resumable"] == 2
    assert summary["with_remaining_subgoals"] == 1
    assert summary["all_subgoals_done"] == 1
