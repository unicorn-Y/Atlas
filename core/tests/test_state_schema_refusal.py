"""An older Atlas must refuse a store written by a newer one.

Every migration in the state layer is a forward backfill (``current_version < N``).
An older build therefore runs *none* of them against a newer store and then
writes rows shaped for a schema it does not know — corrupting a file that a newer
Atlas still owns. DSH models the same rule as a ``status:'unsupported'`` refusal;
here the open itself is what must fail, loudly and before any write.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from atlas.engine.state.atlas_state_common import SCHEMA_VERSION
from atlas.engine.state.atlas_state_errors import SchemaTooNewError

pytestmark = pytest.mark.unit


def _make_store(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


def _stamp_version(db_path: Path, version: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS schema_version")
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.commit()
    finally:
        conn.close()


def test_current_version_is_accepted(tmp_path):
    from atlas.engine.state.atlas_state import SessionDB

    db_path = _make_store(tmp_path)
    db = SessionDB(db_path)
    try:
        version = db._conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert int(version) == SCHEMA_VERSION
    finally:
        db.close()


def test_newer_store_is_refused_before_any_write(tmp_path):
    from atlas.engine.state.atlas_state import SessionDB

    db_path = _make_store(tmp_path)
    # Build a valid store first, then age it forward as if a newer Atlas had.
    db = SessionDB(db_path)
    db.close()
    _stamp_version(db_path, SCHEMA_VERSION + 7)

    with pytest.raises(SchemaTooNewError) as caught:
        SessionDB(db_path)

    message = str(caught.value)
    assert str(SCHEMA_VERSION + 7) in message
    assert str(SCHEMA_VERSION) in message
    assert "Upgrade Atlas" in message


def test_refused_store_keeps_its_recorded_version(tmp_path):
    """The refusal must not "repair" the version downwards; the file stays owned by the newer build."""
    from atlas.engine.state.atlas_state import SessionDB

    db_path = _make_store(tmp_path)
    db = SessionDB(db_path)
    db.close()
    newer = SCHEMA_VERSION + 3
    _stamp_version(db_path, newer)

    with pytest.raises(SchemaTooNewError):
        SessionDB(db_path)

    conn = sqlite3.connect(db_path)
    try:
        stored = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    finally:
        conn.close()
    assert int(stored) == newer
