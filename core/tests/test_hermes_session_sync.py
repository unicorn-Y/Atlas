from __future__ import annotations

from atlas.engine.session_sync import (
    capture_session, delete_session, fork_session, restore_session,
    rewind_to_atlas_message,
)


def _seed_session(home, session_id="source"):
    import os

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
    import os

    os.environ["HERMES_HOME"] = str(home)
    from hermes_state import SessionDB

    with SessionDB(db_path=home / "state.db") as db:
        return db.get_messages_as_conversation(session_id)


def test_rewind_and_redo_restore_complete_hermes_transcript(tmp_path):
    home = tmp_path / "engine"
    home.mkdir()
    _seed_session(home)
    atlas = [
        {"id": "u1", "role": "user", "content": "first"},
        {"id": "a1", "role": "assistant", "content": "first answer"},
        {"id": "u2", "role": "user", "content": "second"},
    ]

    snapshot = rewind_to_atlas_message(home, "source", atlas, "u2")
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
    atlas = [
        {"id": "u1", "role": "user", "content": "first"},
        {"id": "a1", "role": "assistant", "content": "first answer"},
        {"id": "u2", "role": "user", "content": "second"},
        {"id": "a2", "role": "assistant", "content": "second answer"},
    ]

    fork_session(home, "source", "forked", atlas, "a1")
    fork = _history(home, "forked")
    assert [item["content"] for item in fork if item["role"] == "user"] == ["first"]
    assert any(item["role"] == "tool" and item["content"] == "fixture result" for item in fork)
    assert delete_session(home, "forked")
    assert capture_session(home, "forked") is None
    assert len(_history(home, "source")) > len(fork)
