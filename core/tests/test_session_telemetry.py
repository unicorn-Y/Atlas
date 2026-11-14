"""Session lifecycle telemetry commits with the event and deduplicates replay."""

import sqlite3

import pytest

from atlas.engine.state.atlas_state_portability import _append_session_event_row
from atlas.session_telemetry import mirror_session_event

pytestmark = pytest.mark.unit


def _connection(path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS session_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT, event_type TEXT, payload_json TEXT, created_at TEXT
    )""")
    conn.commit()
    return conn


def test_mirror_deduplicates_same_identity_after_reopen(tmp_path):
    path = tmp_path / "state.db"
    with _connection(path) as conn:
        first = _append_session_event_row(conn, "session-a", "turn/start", {"prompt": "private"})
        second = _append_session_event_row(conn, "session-a", "turn/end", {})
    conn.close()
    with _connection(path) as conn:
        mirror_session_event(conn, first)
        mirror_session_event(conn, second)
        rows = conn.execute("SELECT session_id,format_version,seq,event_type FROM session_telemetry ORDER BY seq").fetchall()
        assert rows == [("session-a", 1, first, "turn/start"), ("session-a", 1, second, "turn/end")]
        assert "private" not in str(rows)
    conn.close()


def test_event_and_mirror_share_rollback(tmp_path):
    conn = _connection(tmp_path / "state.db")
    _append_session_event_row(conn, "initial", "turn/start", {})
    conn.commit()
    _append_session_event_row(conn, "rolled-back", "turn/start", {})
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM session_events").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM session_telemetry").fetchone()[0] == 1
    conn.close()


def test_first_observation_backfills_preexisting_lifecycle_events(tmp_path):
    conn = _connection(tmp_path / "state.db")
    conn.execute("INSERT INTO session_events VALUES (1,'old','turn/start','{}','2026-01-01')")
    conn.commit()
    _append_session_event_row(conn, "new", "turn/start", {})
    conn.commit()
    assert conn.execute("SELECT session_id FROM session_telemetry ORDER BY seq").fetchall() == [("old",), ("new",)]
    conn.close()
