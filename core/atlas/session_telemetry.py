"""Durable metadata mirror of Atlas's version-one session lifecycle events."""

from __future__ import annotations

import sqlite3

FORMAT_VERSION = 1


def mirror_session_event(conn: sqlite3.Connection, seq: int) -> None:
    """Mirror a canonical row inside its existing transaction without re-entry.

    The source cursor owns commit and rollback. Re-observing the same event is
    idempotent, including after reconnect or process restart.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_telemetry'",
    ).fetchone()
    conn.execute("""CREATE TABLE IF NOT EXISTS session_telemetry (
        session_id TEXT NOT NULL,
        format_version INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (session_id, format_version, seq)
    )""")
    selection = " WHERE seq=?" if exists else ""
    conn.execute(
        "INSERT OR IGNORE INTO session_telemetry "
        "(session_id,format_version,seq,event_type,created_at) "
        "SELECT session_id,?,seq,event_type,created_at FROM session_events" + selection,
        (FORMAT_VERSION, seq) if exists else (FORMAT_VERSION,),
    )
