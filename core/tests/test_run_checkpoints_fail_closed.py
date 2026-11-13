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
