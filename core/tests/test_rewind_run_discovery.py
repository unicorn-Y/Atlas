"""Rewind finds file checkpoints for engine-written turns (no run id in messages)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from atlas.agent.checkpoints import ShadowGitCheckpointStore

pytestmark = pytest.mark.unit


def _checkpoint(store: ShadowGitCheckpointStore, workspace, run_id: str, created_at: str) -> str:
    item = store.create_checkpoint(workspace, ["result.txt"], run_id=run_id)
    item["created_at"] = created_at
    (store.storage_dir / item["id"] / "manifest.json").write_text(json.dumps(item), encoding="utf-8")
    return item["id"]


@pytest.mark.asyncio
async def test_conversation_runs_contribute_only_checkpoints_after_the_rewind_point(
    tmp_path, monkeypatch,
):
    from atlas import server
    from atlas.api.conversations_router import _snapshot_rewind_files

    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.txt").write_text("v0", encoding="utf-8")
    earlier = _checkpoint(store, workspace, "run-old", "2026-01-01T00:00:00+00:00")
    later = _checkpoint(store, workspace, "run-new", "2026-01-02T00:00:00+00:00")
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(checkpoints=store))

    since = datetime(2026, 1, 1, 12, tzinfo=UTC)
    _files, checkpoints = await _snapshot_rewind_files(
        ["run-old", "run-new"], [str(workspace)], since, {"run-old", "run-new"},
    )
    assert [item["checkpoint_id"] for item in checkpoints] == [later]

    # Runs named by message metadata are taken whole, regardless of time.
    _files, checkpoints = await _snapshot_rewind_files(
        ["run-old"], [str(workspace)], since, set(),
    )
    assert [item["checkpoint_id"] for item in checkpoints] == [earlier]
