import pytest

from atlas.engine.goals import GoalManager, GoalRevisionConflict


@pytest.mark.unit
def test_goal_default_budget_is_256_and_goal_updates_increment_revision(tmp_path):
    manager = GoalManager("cas", home=tmp_path)
    state = manager.set("ship it")

    assert state.max_turns == 256
    assert state.revision == 1
    first_id = state.goal_id
    manager.add_subgoal("first milestone", expected_goal_id=first_id, expected_revision=1)
    assert manager.state.revision == 2
    assert manager.state.goal_id == first_id

    prompt = manager.next_continuation_prompt()
    assert f"goal_id={first_id} revision=2" in prompt


@pytest.mark.unit
def test_stale_goal_writer_is_rejected_without_overwriting_newer_state(tmp_path):
    first = GoalManager("cas-stale", home=tmp_path)
    first.set("ship it")
    stale = GoalManager("cas-stale", home=tmp_path)

    first.add_subgoal("newer")
    with pytest.raises(GoalRevisionConflict):
        stale.add_subgoal("stale")

    reloaded = GoalManager("cas-stale", home=tmp_path)
    assert reloaded.state.subgoals == ["newer"]
    assert reloaded.state.revision == 2


@pytest.mark.unit
def test_explicit_goal_id_and_revision_are_required_to_match_current_goal(tmp_path):
    manager = GoalManager("cas-explicit", home=tmp_path)
    state = manager.set("ship it")

    with pytest.raises(GoalRevisionConflict):
        manager.add_subgoal("stale request", expected_goal_id=state.goal_id,
                            expected_revision=state.revision - 1)

    assert manager.state.subgoals == []


@pytest.mark.unit
def test_session_goal_command_rejects_stale_cas_token(tmp_path):
    from atlas.engine.session_sync import goal_command

    manager = GoalManager("cas-api", home=tmp_path)
    state = manager.set("ship it")
    stale_revision = state.revision
    manager.add_subgoal("newer")

    result = goal_command(
        tmp_path, "cas-api", "subgoal add stale",
        expected_goal_id=state.goal_id, expected_revision=stale_revision,
    )

    assert result["error"] is True
    assert "stale goal revision" in result["output"]
    assert result["goal"]["subgoals"] == ["newer"]
    assert result["goal"]["revision"] == 2


@pytest.mark.unit
def test_legacy_goal_is_upgraded_to_persistent_identity(tmp_path):
    import json

    from atlas.engine.state.atlas_state import SessionDB

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.set_meta("goal:legacy-cas", json.dumps({"goal": "old goal", "status": "active"}))

    first = GoalManager("legacy-cas", home=tmp_path).state
    second = GoalManager("legacy-cas", home=tmp_path).state

    assert first.goal_id
    assert first.goal_id == second.goal_id
    assert first.revision == second.revision == 1
