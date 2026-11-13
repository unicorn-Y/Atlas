import pytest

import atlas.run_checkpoints as checkpoints


@pytest.mark.unit
def test_required_checkpoint_surfaces_storage_failure(monkeypatch):
    def fail_connect():
        raise OSError("checkpoint store unavailable")

    monkeypatch.setattr(checkpoints, "_connect", fail_connect)

    with pytest.raises(checkpoints.CheckpointWriteError, match="required durable checkpoint failed"):
        checkpoints.require_checkpoint("run-1", kind="tool_dispatch")
