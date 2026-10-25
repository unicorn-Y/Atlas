from __future__ import annotations

import asyncio
import json
import os

from atlas.engine.session_sync import (
    append_session_message,
    append_branch_summary,
    atlas_turn_ordinal,
    capture_session,
    delete_session,
    evaluate_goal_after_turn,
    fork_session_through_turn,
    goal_command,
    list_branch_tree,
    restore_session,
    rewind_user_turn,
    read_session_all_messages,
    read_session_model_messages,
)


def _seed_session(home, session_id="source"):
    os.environ["HERMES_HOME"] = str(home)
    from hermes_state import SessionDB

    with SessionDB(db_path=home / "state.db") as db:
        db.ensure_session(session_id, "api_server", cwd=str(home))
        db.append_message(session_id, "user", "first")
        db.append_message(session_id, "assistant", "first answer")
        db.append_message(session_id, "assistant", "", tool_calls=[{
            "id": "call-1", "type": "function",
            "function": {"name": "read_file", "arguments": "{}"},
        }])
        db.append_message(session_id, "tool", "fixture result", tool_name="read_file",
                          tool_call_id="call-1")
        db.append_message(session_id, "user", "second")
        db.append_message(session_id, "assistant", "second answer")


def _history(home, session_id):
    os.environ["HERMES_HOME"] = str(home)
    from hermes_state import SessionDB

    with SessionDB(db_path=home / "state.db") as db:
        return db.get_messages_as_conversation(session_id)


def test_rewind_and_redo_restore_complete_hermes_transcript(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)

    snapshot = rewind_user_turn(home, "source", 1)
    rewound = _history(home, "source")
    assert [item["content"] for item in rewound if item["role"] == "user"] == ["first"]
    assert any(item["role"] == "tool" and item["content"] == "fixture result" for item in rewound)

    restore_session(home, snapshot)
    restored = _history(home, "source")
    assert [item["content"] for item in restored if item["role"] == "user"] == ["first", "second"]
    assert any(item["role"] == "tool" and item["content"] == "fixture result" for item in restored)


def test_fork_copies_selected_turn_and_delete_removes_hermes_history(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)

    fork_session_through_turn(home, "source", "forked", 1, branch_message_id="a1")
    fork = _history(home, "forked")
    assert [item["content"] for item in fork if item["role"] == "user"] == ["first"]
    assert any(item["role"] == "tool" and item["content"] == "fixture result" for item in fork)
    from hermes_state import SessionDB
    with SessionDB(db_path=home / "state.db") as db:
        metadata = db.get_session("forked")
    assert metadata["parent_session_id"] == "source"
    import json
    assert json.loads(metadata["model_config"])["_branched_from"] == "source"
    tree = list_branch_tree(home, "forked")
    assert [item["id"] for item in tree] == ["source", "forked"]
    assert tree[1]["branch_message_id"] == "a1"
    assert delete_session(home, "forked")
    assert capture_session(home, "forked") is None
    assert len(_history(home, "source")) > len(fork)


def test_goal_commands_persist_per_conversation_and_return_resume_prompt(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)
    created = goal_command(home, "source", "verify the fixture outcome")
    assert created["goal"]["text"] == "verify the fixture outcome"
    assert created["goal"]["status"] == "active"
    assert created["prompt"]
    paused = goal_command(home, "source", "pause")
    assert paused["goal"]["status"] == "paused"
    resumed = goal_command(home, "source", "resume")
    assert resumed["goal"]["status"] == "active"
    assert resumed["prompt"]
    assert goal_command(home, "source", "clear")["goal"] is None


def test_goal_turn_evaluation_uses_persisted_hermes_manager(tmp_path, monkeypatch):
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)
    goal_command(home, "source", "verify the fixture outcome")
    seen = {}

    def evaluate(manager, response):
        seen["goal"] = manager.state.goal
        seen["response"] = response
        return {"status": "active", "should_continue": True,
                "continuation_prompt": "continue the fixture", "verdict": "continue"}

    monkeypatch.setattr("hermes_cli.goals.GoalManager.evaluate_after_turn", evaluate)
    decision = evaluate_goal_after_turn(home, "source", "fixture response")
    assert seen == {"goal": "verify the fixture outcome", "response": "fixture response"}
    assert decision["continuation_prompt"] == "continue the fixture"


def test_branch_summary_is_mirrored_to_hermes_parent_session(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)
    append_branch_summary(home, "source", "child", "a1", "branch note")
    messages = _history(home, "source")
    assert messages[-1]["content"] == "branch note"


def test_subtask_activity_is_saved_for_ui_and_hidden_from_model_context(tmp_path, monkeypatch):
    home = tmp_path / "engine"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    from hermes_state import SessionDB

    with SessionDB(db_path=home / "state.db") as db:
        db.ensure_session("parent", "api_server", cwd=str(home))
        db.append_message("parent", "user", "delegate the work")
    append_session_message(home, "parent", "system", "", {
        "display_kind": "subtask_activity",
        "activity": {"event": "subtask.completed", "subtask_id": "child-1", "summary": "done"},
    })

    activity = read_session_all_messages(home, "parent")[-1]
    assert activity["metadata"]["display_kind"] == "subtask_activity"
    assert activity["metadata"]["activity"]["subtask_id"] == "child-1"
    assert all(item.get("display_kind") != "subtask_activity" for item in read_session_model_messages(home, "parent"))


# ----- H2.1 step 2: direct SessionDB write path (no Atlas state in the loop) -----


def test_atlas_turn_ordinal_resolves_targets_without_syncing():
    atlas = [
        {"id": "u1", "role": "user", "content": "first"},
        {"id": "a1", "role": "assistant", "content": "first answer"},
        {"id": "u2", "role": "user", "content": "second"},
        {"id": "a2", "role": "assistant", "content": "second answer"},
    ]
    assert atlas_turn_ordinal(atlas, "u2", through_target=False) == 1
    assert atlas_turn_ordinal(atlas, "a1", through_target=True) == 1
    assert atlas_turn_ordinal(atlas, "a2", through_target=True) == 2
    assert atlas_turn_ordinal(atlas, "missing", through_target=False) is None


def test_rewind_user_turn_direct_op_needs_no_atlas_state(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)

    snapshot = rewind_user_turn(home, "source", 1)
    rewound = _history(home, "source")
    assert [item["content"] for item in rewound if item["role"] == "user"] == ["first"]
    assert any(item["role"] == "tool" and item["content"] == "fixture result" for item in rewound)

    restore_session(home, snapshot)
    restored = _history(home, "source")
    assert [item["content"] for item in restored if item["role"] == "user"] == ["first", "second"]
    assert any(item["role"] == "tool" and item["content"] == "fixture result" for item in restored)


def test_fork_session_through_turn_direct_cuts_from_sessiondb_transcript(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)

    fork_session_through_turn(home, "source", "forked", 1, branch_message_id="a1")
    fork = _history(home, "forked")
    assert [item["content"] for item in fork if item["role"] == "user"] == ["first"]
    assert any(item["role"] == "tool" and item["content"] == "fixture result" for item in fork)
    from hermes_state import SessionDB
    with SessionDB(db_path=home / "state.db") as db:
        metadata = db.get_session("forked")
    assert metadata["parent_session_id"] == "source"
    assert json.loads(metadata["model_config"])["_branched_from"] == "source"
    assert json.loads(metadata["model_config"])["_branch_message_id"] == "a1"
    tree = list_branch_tree(home, "forked")
    assert [item["id"] for item in tree] == ["source", "forked"]
    assert tree[1]["branch_message_id"] == "a1"
    # The source transcript is untouched by the fork.
    assert [item["content"] for item in _history(home, "source") if item["role"] == "user"] == [
        "first", "second"]


def test_history_mutations_keep_doctor_sessions_consistent(tmp_path, monkeypatch):
    """Taskbook H2.1 acceptance: after fork/rewind/export+import/delete, the
    `atlas doctor sessions` cross-store check reports zero inconsistencies."""
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)
    monkeypatch.setenv("HERMES_HOME", str(home))

    import atlas.config as atlas_config
    from atlas.memory import MemoryStore

    monkeypatch.setattr(atlas_config, "DATA_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(atlas_config, "_config", atlas_config.AtlasConfig(), raising=False)
    memory = MemoryStore(db_path=tmp_path / "data" / "atlas.db")

    async def _build():
        await memory.init()
        await memory.save_conversation_metadata("source")

    asyncio.run(_build())

    def _doctor():
        from atlas.cli import _check_sessions

        report = _check_sessions()
        assert report["state_db_error"] == "", report
        assert report["atlas_db_error"] == "", report
        return report

    def _assert_consistent():
        report = _doctor()
        assert report["ok"] is True, report
        assert report["missing_in_hermes"] == []
        assert report["orphans_in_hermes"] == []

    # Baseline: source exists in both stores.
    _assert_consistent()
    # Fork (direct SessionDB op + metadata-only conversation row).
    fork_session_through_turn(home, "source", "forked", 1, branch_message_id="a1")

    async def _seed_fork_row():
        await memory.save_conversation_metadata("forked")
        await memory.update_conversation("forked", parent_conversation_id="source",
                                         fork_message_id="a1")

    asyncio.run(_seed_fork_row())
    _assert_consistent()
    # Rewind changes the canonical transcript only; Atlas' old message table is frozen.
    rewind_user_turn(home, "source", 1)
    _assert_consistent()
    # Export + import roundtrip: same session ids on both sides.
    payload = capture_session(home, "source")
    restore_session(home, payload)
    _assert_consistent()
    # Delete: dropped from both stores.
    assert delete_session(home, "forked") is True
    assert asyncio.run(memory.delete_conversation("forked")) is True
    _assert_consistent()
    assert capture_session(home, "forked") is None
