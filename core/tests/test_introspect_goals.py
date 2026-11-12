"""The goals introspection provider: read-only answers about persistent goals.

Goals are the one subsystem whose state is invisible from the REST list — a
``/goal`` started in a chat session has no scheduler task row, so ``/api/goals``
cannot see it. These tests pin the DB-backed provider that can, and pin its
degradation behaviour, because an introspection query that 500s on one corrupt
goal tells you nothing about the others.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.engine.goals import GoalManager
from atlas.engine.session_sync import record_goal_event
from atlas.introspect.providers import goals as gp
from atlas.introspect.registry import Context


@pytest.fixture()
def engine_home(tmp_path, monkeypatch):
    """An engine directory that the provider resolves to, not the real one."""
    import atlas.config as config

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    home = tmp_path / "engine"
    home.mkdir(parents=True, exist_ok=True)
    return home


@pytest.fixture()
def ctx():
    return Context(services=None, app=None)


def _goal(home: Path, session_id: str, text: str, subgoals=()) -> GoalManager:
    manager = GoalManager(session_id, home=home)
    manager.set(text)
    for subgoal in subgoals:
        manager.add_subgoal(subgoal)
    return manager


def test_gate_reports_the_real_limits(ctx):
    from atlas.engine.goals import MAX_PLAN_ATTEMPTS

    payload = gp._gate(ctx, {})
    assert payload["max_plan_attempts"] == MAX_PLAN_ATTEMPTS
    assert "PLAN REQUIRED" in payload["requirement_prompt"]
    assert payload["events"] == ["goal.planning_turn"]


def test_stranded_lists_active_goals_with_remaining_milestones(engine_home, ctx):
    _goal(engine_home, "s1", "重构调度器", ["抽出持久化层", "接上重启续跑"])
    payload = gp._stranded(ctx, {})
    assert payload["resumable"] == 1
    assert payload["sessions"] == ["s1"]
    row = payload["goals"][0]
    assert row["session_id"] == "s1"
    assert row["remaining_subgoals"] == ["抽出持久化层", "接上重启续跑"]
    assert payload["home"].endswith("engine")


def test_stranded_skips_completed_goals(engine_home, ctx):
    manager = _goal(engine_home, "s1", "一次性任务")
    manager._state.status = "done"
    manager._save()
    assert gp._stranded(ctx, {})["resumable"] == 0


def test_stranded_search_filters(engine_home, ctx):
    _goal(engine_home, "s1", "重构调度器")
    _goal(engine_home, "s2", "清理空行")
    assert gp._stranded(ctx, {"search": "调度"})["resumable"] == 1
    assert gp._stranded(ctx, {"search": "s2"})["resumable"] == 1
    assert gp._stranded(ctx, {"search": "zzz"})["resumable"] == 0


def test_state_reports_milestones_and_gate(engine_home, ctx):
    manager = _goal(engine_home, "s1", "重构调度器", ["一", "二"])
    manager.complete_subgoal(1)
    payload = gp._state(ctx, {"session_id": "s1"})
    assert payload["exists"] is True
    assert payload["subgoals"] == ["一", "二"]
    assert payload["completed_subgoals"] == [1]
    assert payload["done_count"] == 1
    assert payload["remaining_subgoals"] == ["二"]
    assert payload["plan"]["needs_plan"] is False
    assert payload["plan"]["decomposition_required"] is True


def test_state_marks_a_goal_that_still_needs_planning(engine_home, ctx):
    _goal(engine_home, "s1", "重构调度器")
    payload = gp._state(ctx, {"session_id": "s1"})
    assert payload["plan"]["needs_plan"] is True
    assert payload["plan"]["plan_attempts"] == 0


def test_state_unknown_session_is_an_answer(engine_home, ctx):
    payload = gp._state(ctx, {"session_id": "absent"})
    assert payload["exists"] is False
    assert "error" not in payload


def test_state_survives_a_corrupt_row(engine_home, ctx):
    from atlas.engine.state.atlas_state import SessionDB

    with SessionDB(db_path=engine_home / "state.db") as db:
        db.set_meta("goal:broken", "{not json")
    payload = gp._state(ctx, {"session_id": "broken"})
    assert payload["exists"] is True
    assert "error" in payload


def test_state_without_a_database_is_an_answer(tmp_path, monkeypatch, ctx):
    import atlas.config as config

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)  # no engine/ subdir
    payload = gp._state(ctx, {"session_id": "s1"})
    assert payload["exists"] is False
    assert "note" in payload


def test_history_counts_planning_turns(engine_home, ctx):
    record_goal_event(engine_home, "s1", "goal.created", {"goal": "g"})
    record_goal_event(engine_home, "s1", "goal.planning_turn", {"attempt": 1})
    record_goal_event(engine_home, "s1", "goal.evaluated", {"verdict": "continue"})
    payload = gp._history(ctx, {"session_id": "s1"})
    assert payload["count"] == 3
    assert payload["planning_turns"] == 1
    assert [e["event"] for e in payload["events"]] == [
        "goal.created", "goal.planning_turn", "goal.evaluated",
    ]


def test_history_event_filter(engine_home, ctx):
    record_goal_event(engine_home, "s1", "goal.created", {"goal": "g"})
    record_goal_event(engine_home, "s1", "goal.planning_turn", {"attempt": 1})
    payload = gp._history(ctx, {"session_id": "s1", "event": "goal.planning_turn"})
    assert payload["count"] == 1
    assert payload["events"][0]["data"]["attempt"] == 1


def test_history_limit_is_clamped(engine_home, ctx):
    for index in range(8):
        record_goal_event(engine_home, "s1", "goal.evaluated", {"n": index})
    assert len(gp._history(ctx, {"session_id": "s1", "limit": 3})["events"]) == 3
    assert len(gp._history(ctx, {"session_id": "s1", "limit": 9999})["events"]) == 8
    assert len(gp._history(ctx, {"session_id": "s1", "limit": "junk"})["events"]) == 8


def test_provider_is_registered_with_four_methods():
    from atlas.introspect.registry import providers

    registered = {provider.id: provider for provider in providers()}
    assert "goals" in registered
    assert [m.name for m in registered["goals"].methods] == [
        "stranded", "state", "history", "gate",
    ]
    manifest = registered["goals"].manifest()
    assert manifest["id"] == "goals"
    json.dumps(manifest)  # the manifest must be JSON-serialisable


def test_required_inputs_are_declared():
    from atlas.introspect.registry import QueryError, providers

    provider = {p.id: p for p in providers()}["goals"]
    for name in ("state", "history"):
        schema = provider.method(name).input_schema
        assert schema["required"] == ["session_id"]
    assert "required" not in provider.method("gate").input_schema
    with pytest.raises(QueryError):
        provider.method("nope")
