from __future__ import annotations

import sqlite3

import pytest

pytestmark = pytest.mark.unit


def test_require_checkpoint_persists_or_raises(tmp_path, monkeypatch):
    import atlas.run_checkpoints as checkpoints

    monkeypatch.setattr(checkpoints, "DATA_ROOT", tmp_path)
    assert checkpoints.require_checkpoint(
        "run-safe", kind="phase", phase="running", sequence=1,
    ) is True
    assert checkpoints.latest_checkpoint("run-safe")["phase"] == "running"

    def fail_connect():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(checkpoints, "_connect", fail_connect)
    with pytest.raises(checkpoints.CheckpointWriteError, match="durable checkpoint"):
        checkpoints.require_checkpoint("run-locked", kind="phase", phase="running")


def test_require_checkpoint_rejects_missing_run_id():
    import atlas.run_checkpoints as checkpoints

    with pytest.raises(checkpoints.CheckpointWriteError, match="run_id"):
        checkpoints.require_checkpoint("", kind="phase", phase="running")


def test_required_checkpoint_emits_a_production_span(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from atlas import telemetry
    import atlas.run_checkpoints as checkpoints

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
    monkeypatch.setattr(checkpoints, "DATA_ROOT", tmp_path)
    monkeypatch.setitem(telemetry._state, "tracer", tracer)

    checkpoints.require_checkpoint("run-traced", kind="tool_dispatch", phase="execution")

    assert [name for name, _span in tracer.spans] == ["atlas.run_checkpoint.write"]
    attributes = tracer.spans[0][1].attributes
    assert attributes["checkpoint.kind"] == "tool_dispatch"
    assert attributes["checkpoint.persisted"] is True
