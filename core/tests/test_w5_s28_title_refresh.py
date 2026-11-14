"""W5 S28 — ``refresh()`` unpins a user rename so auto titles re-compete.

Ledger S28 (DSH `session-title/README.md:32`): three title sources, newest-wins,
a user rename pins, ``refresh()`` unpins. Atlas had the rank CAS
(``atlas_state_titles.py``) but no unpin path: once ``title_source='user'`` held
the row, every automatic writer was blocked forever. This file pins the new
``refresh_session_title`` (mixin + engine wrapper + API route exposure).
"""

from __future__ import annotations

import pytest

from atlas.engine.state.atlas_state import SessionDB

pytestmark = pytest.mark.unit


@pytest.fixture()
def db(tmp_path):
    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("sess-1", "api_server", cwd=str(tmp_path))
        yield db


def test_s28_user_rename_pins_and_blocks_auto_titles(db):
    assert db.set_session_title("sess-1", "My Session") is True
    assert db.get_session_title_source("sess-1") == "user"
    # llm and derived writes are both refused while the pin holds.
    assert db.set_auto_title("sess-1", "Auto LLM", source="llm") is False
    assert db.set_auto_title("sess-1", "Auto Derived", source="derived") is False
    assert db.get_session_title("sess-1") == "My Session"


def test_s28_refresh_unpins_and_llm_recompetes(db):
    db.set_session_title("sess-1", "My Session")
    assert db.refresh_session_title("sess-1") is True
    # Text kept, pin dropped to derived provenance.
    assert db.get_session_title("sess-1") == "My Session"
    assert db.get_session_title_source("sess-1") == "derived"
    # The blocked llm title now lands.
    assert db.set_auto_title("sess-1", "Auto LLM", source="llm") is True
    assert db.get_session_title("sess-1") == "Auto LLM"


def test_s28_refresh_returns_false_without_user_pin(db):
    # Untitled row: nothing to unpin.
    assert db.refresh_session_title("sess-1") is False
    # Auto-provenance row: not pinned, nothing to unpin.
    assert db.set_auto_title("sess-1", "Auto Derived", source="derived") is True
    assert db.refresh_session_title("sess-1") is False
    assert db.get_session_title_source("sess-1") == "derived"


def test_s28_refresh_missing_session_returns_false(db):
    assert db.refresh_session_title("nope") is False


def test_s28_engine_wrapper_refresh_user_title(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from atlas.engine.session_titles import refresh_user_title, set_user_title

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("sess-api", "api_server", cwd=str(tmp_path))
    assert set_user_title(tmp_path, "sess-api", "Pinned Name") is True
    assert refresh_user_title(tmp_path, "sess-api") is True
    with SessionDB(db_path=tmp_path / "state.db") as db:
        assert db.get_session_title_source("sess-api") == "derived"


def test_s28_title_generator_unpins_after_refresh(db, monkeypatch):
    """The engine titler's own user-pin guard stops refusing after refresh."""
    from atlas.engine.kernel.toolkit import title_generator

    db.set_session_title("sess-1", "My Session")
    assert title_generator._write_session_title(db, "sess-1", "New Auto", "llm") is None
    assert db.refresh_session_title("sess-1") is True
    assert title_generator._write_session_title(db, "sess-1", "New Auto", "llm") == "New Auto"
