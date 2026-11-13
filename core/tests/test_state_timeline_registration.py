from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.unit


def test_session_db_exposes_turn_outline_projection(tmp_path):
    from atlas.engine.state.atlas_state import SessionDB

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("timeline-test", "cli")
        row_id = db.append_message("timeline-test", "user", content="What changed?")

        result = db.get_session_timeline("timeline-test")
        around = db.get_session_messages_around("timeline-test", row_id)

    assert result["entries"] == [
        {"row_id": row_id, "preview": "What changed?", "timestamp": result["entries"][0]["timestamp"]}
    ]
    assert result["pagination"]["total"] == 1
    assert around["messages"][0]["id"] == row_id


def test_turn_outline_projection_emits_otel_span(tmp_path, monkeypatch):
    from atlas import telemetry
    from atlas.engine.state.atlas_state import SessionDB

    class CurrentSpan:
        def __init__(self):
            self.attributes = {}

        def set_attribute(self, key, value):
            self.attributes[key] = value

    class Tracer:
        def __init__(self):
            self.spans = []

        @contextmanager
        def start_as_current_span(self, name):
            current = CurrentSpan()
            self.spans.append((name, current))
            yield current

    tracer = Tracer()
    monkeypatch.setitem(telemetry._state, "tracer", tracer)
    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("timeline-traced", "cli")
        db.append_message("timeline-traced", "user", content="Trace this outline")
        result = db.get_session_timeline("timeline-traced", limit=10)

    assert len(result["entries"]) == 1
    assert len(tracer.spans) == 1
    name, span = tracer.spans[0]
    assert name == "atlas.session.turn_outline"
    assert span.attributes == {"timeline.limit": 10, "timeline.returned": 1, "timeline.total": 1}
