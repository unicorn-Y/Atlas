from __future__ import annotations

import sqlite3

import pytest

pytestmark = pytest.mark.unit


def test_fork_refuses_a_cut_with_unanswered_tool_calls(tmp_path):
    from atlas.engine.session_sync import fork_session_through_turn
    from atlas.engine.state.atlas_state import SessionDB

    home = tmp_path / "engine"
    home.mkdir()
    source_id = "source-open-turn"
    fork_id = "fork-open-turn"
    with SessionDB(db_path=home / "state.db") as db:
        db.ensure_session(source_id, "api_server")
        db.append_message(source_id, "user", content="run a tool")
        db.append_message(
            source_id,
            "assistant",
            content="",
            tool_calls=[{"id": "call-pending", "function": {"name": "x", "arguments": "{}"}}],
        )

    with pytest.raises(ValueError, match="open turn"):
        fork_session_through_turn(home, source_id, fork_id, 1)

    with SessionDB(db_path=home / "state.db") as db:
        assert db.get_session(fork_id) is None


def test_fork_allows_a_closed_turn(tmp_path):
    from atlas.engine.session_sync import fork_session_through_turn
    from atlas.engine.state.atlas_state import SessionDB

    home = tmp_path / "engine"
    home.mkdir()
    with SessionDB(db_path=home / "state.db") as db:
        db.ensure_session("source-closed-turn", "api_server")
        db.append_message("source-closed-turn", "user", content="hello")
        db.append_message("source-closed-turn", "assistant", content="hi")

    fork_session_through_turn(home, "source-closed-turn", "fork-closed-turn", 1)

    with SessionDB(db_path=home / "state.db") as db:
        assert [message["content"] for message in db.get_messages("fork-closed-turn")] == [
            "hello", "hi",
        ]
        seed = db._conn.execute(
            "SELECT event_type, payload_json FROM session_events WHERE session_id = ?",
            ("fork-closed-turn",),
        ).fetchone()
        assert seed is not None
        assert seed["event_type"] == "session/end-seed"
        assert '"inherited":true' in seed["payload_json"]


def test_existing_schema_database_upgrades_to_fork_event_schema(tmp_path):
    from atlas.engine.state.atlas_state import SessionDB
    from atlas.engine.state.atlas_state_common import SCHEMA_VERSION

    db_path = tmp_path / "state.db"
    with SessionDB(db_path=db_path):
        pass
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TRIGGER IF EXISTS session_events_no_update")
        conn.execute("DROP TRIGGER IF EXISTS session_events_no_delete")
        conn.execute("DROP TABLE session_events")
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION - 1,))

    with SessionDB(db_path=db_path) as db:
        version = db._conn.execute("SELECT version FROM schema_version").fetchone()[0]
        table = db._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'session_events'"
        ).fetchone()

    assert version == SCHEMA_VERSION
    assert table is not None


def test_session_event_append_api_persists_an_immutable_event(tmp_path):
    from atlas.engine.state.atlas_state import SessionDB

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("event-session", "api_server")
        seq = db.append_session_event(
            "event-session", "approval/asked", {"request_id": "approval-1"},
        )
        row = db._conn.execute(
            "SELECT seq, event_type, payload_json FROM session_events WHERE session_id = ?",
            ("event-session",),
        ).fetchone()

    assert row["seq"] == seq
    assert row["event_type"] == "approval/asked"
    assert row["payload_json"] == '{"request_id":"approval-1"}'


def test_session_event_reader_supports_sequence_cursor(tmp_path):
    from atlas.engine.state.atlas_state import SessionDB

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("event-cursor", "api_server")
        first = db.append_session_event("event-cursor", "inbox/queued", {"text": "a"})
        second = db.append_session_event("event-cursor", "inbox/queued", {"text": "b"})
        events = db.list_session_events("event-cursor", after_seq=first)

    assert [event["seq"] for event in events] == [second]
    assert events[0]["payload"] == {"text": "b"}


def test_session_sync_event_helpers_share_the_sessiondb_store(tmp_path):
    from atlas.engine.session_sync import append_session_event, read_session_events
    from atlas.engine.state.atlas_state import SessionDB

    home = tmp_path / "engine"
    home.mkdir()
    with SessionDB(db_path=home / "state.db") as db:
        db.ensure_session("wrapper-event", "api_server")

    seq = append_session_event(home, "wrapper-event", "approval/decided", {"allow": True})
    events = read_session_events(home, "wrapper-event", after_seq=seq - 1)

    assert events == [{
        "seq": seq,
        "session_id": "wrapper-event",
        "event_type": "approval/decided",
        "payload": {"allow": True},
        "created_at": events[0]["created_at"],
    }]
