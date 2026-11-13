from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_search_returns_classification_and_monotonic_sequence_cursor(tmp_path):
    from atlas.engine.state.atlas_state import SessionDB

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("search-cursor", "api_server")
        first = db.append_message("search-cursor", "user", content="needle current")
        second = db.append_message("search-cursor", "assistant", content="needle later")
        later = db.search_messages(
            "needle", include_inactive=True, after_seq=first,
            fields={"id", "seq", "classification"},
        )

    assert later == [{
        "id": second,
        "seq": second,
        "classification": "current",
    }]


def test_search_classifies_shadowed_and_log_only_rows(tmp_path):
    from atlas.engine.state.atlas_state import SessionDB

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("search-classes", "api_server")
        shadowed = db.append_message("search-classes", "assistant", content="needle shadowed")
        log_only = db.append_message("search-classes", "user", content="needle log-only")
        db._execute_write(lambda conn: conn.execute(
            "UPDATE messages SET active = 0, compacted = 1 WHERE id = ?", (shadowed,),
        ))
        db._execute_write(lambda conn: conn.execute(
            "UPDATE messages SET active = 0, compacted = 0 WHERE id = ?", (log_only,),
        ))
        rows = db.search_messages(
            "needle", include_inactive=True, fields={"id", "classification"},
        )

    assert {row["id"]: row["classification"] for row in rows} == {
        shadowed: "shadowed",
        log_only: "log-only",
    }
