"""Session workspace invariants for the Atlas kernel runtime."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from atlas.engine.atlas_runtime import AtlasRuntime


@pytest.mark.unit
def test_session_workspace_helper_excludes_ssh_and_empty(tmp_path: Path) -> None:
    assert AtlasRuntime._session_workspace(str(tmp_path)) == str(tmp_path)
    assert AtlasRuntime._session_workspace("ssh://host/remote/path") == ""
    assert AtlasRuntime._session_workspace("  ") == ""
    assert AtlasRuntime._session_workspace(None) == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_move_persists_next_workspace_without_moving_active_run(tmp_path: Path) -> None:
    """Moving a session must not change the current run's fixed workspace."""
    from atlas.tools.workspace_workflows import workspace_workflow_dispatch

    current_workspace = tmp_path / "current"
    next_workspace = tmp_path / "next"
    current_workspace.mkdir()
    next_workspace.mkdir()

    class Memory:
        saved: dict[str, Any] | None = None

        async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
            return {"conversation_id": conversation_id, "worktree_path": ""}

        async def update_conversation(self, conversation_id: str, **changes: Any) -> bool:
            self.saved = {"conversation_id": conversation_id, **changes}
            return True

    memory = Memory()
    agent = SimpleNamespace(_memory=memory)
    runtime = SimpleNamespace(
        conversation_id="move-session-1",
        workspace=str(current_workspace),
        permission_mode="full_access",
        read_only=False,
        mode="act",
    )

    result = await workspace_workflow_dispatch(
        "workspace_session_manage",
        {"action": "move", "workspace": str(next_workspace)},
        agent,
        runtime,
    )

    assert result["outcome"] == "completed"
    assert memory.saved == {
        "conversation_id": "move-session-1",
        "workspace": str(next_workspace),
        "worktree_path": "",
        "worktree_branch": "",
        "base_branch": "",
    }
    assert result["data"]["applies_from_next_run"] is True
    assert result["data"]["active_run_workspace"] == str(current_workspace)
    assert runtime.workspace == str(current_workspace)
