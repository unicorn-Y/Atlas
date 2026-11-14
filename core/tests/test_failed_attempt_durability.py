"""A run that dies before writing a message must still be replayable.

An unknown model id, a provider that rejects the request — the run fails before
any transcript row exists. The failure used to live only in the live socket, so
a later replay showed a session with no events and no way to tell what was
attempted. The attempt is now its own durable event type.
"""

from __future__ import annotations

import pytest

from atlas.engine.session_sync import _open_db, record_failed_attempt

pytestmark = pytest.mark.unit


def test_failure_is_recorded_for_a_session_that_never_existed(tmp_path):
    home = tmp_path / "engine"
    seq = record_failed_attempt(
        home, "conv-new", category="model",
        detail="Model selection failed: Unknown model: nope",
        model="nope", run_id="run-1",
    )
    assert seq is not None
    with _open_db(home) as db:
        events = db.list_session_events("conv-new")
    assert [e["event_type"] for e in events] == ["attempt/failed"]
    payload = events[0]["payload"]
    assert payload["category"] == "model"
    assert "Unknown model" in payload["detail"]
    assert payload["model"] == "nope"
    assert payload["run_id"] == "run-1"


def test_blank_conversation_id_is_ignored_not_raised(tmp_path):
    assert record_failed_attempt(tmp_path / "e", "", category="x", detail="y") is None


def test_detail_is_bounded(tmp_path):
    """A provider that echoes a huge body must not bloat the event log."""
    home = tmp_path / "engine"
    record_failed_attempt(home, "conv-big", category="provider", detail="x" * 50_000)
    with _open_db(home) as db:
        payload = db.list_session_events("conv-big")[0]["payload"]
    assert len(payload["detail"]) <= 2000


def test_recording_failure_never_raises(tmp_path):
    """A failure report must not become a second failure."""
    # A path under a file is not a directory, so opening the store fails.
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x", encoding="utf-8")
    assert record_failed_attempt(blocked / "engine", "c", category="x", detail="y") is None
