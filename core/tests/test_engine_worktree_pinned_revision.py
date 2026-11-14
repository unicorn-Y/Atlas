"""E32: conversation worktree created from a pinned revision (commit SHA), enterable in-run.

DSH semantic: "Git worktree: 从固定 revision 创建，模型可'进入'而不必新开 run".
The git layer already accepts any commit-ish (``git worktree add -b <branch> <path> <sha>``)
and the model-facing schema advertises it; these tests pin both layers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from atlas.task_artifacts import WorktreeService


def _init_repo(repo: Path) -> str:
    """Two-commit repo; returns the FIRST commit's full sha (the pinned revision)."""
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True)
    pinned = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    (repo / "later.txt").write_text("later work", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "later.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "later"], check=True, capture_output=True)
    return pinned


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.mark.unit
def test_worktree_create_from_pinned_sha_checks_out_that_revision(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pinned = _init_repo(repo)

    service = WorktreeService(tmp_path / "data")
    created = service.create(repo, "12345678-aaaa-bbbb", base_branch=pinned)

    worktree = Path(created["worktree_path"])
    assert _head(worktree) == pinned  # pinned revision, NOT the branch tip
    assert created["base_branch"] == pinned
    assert (worktree / "seed.txt").exists()
    assert not (worktree / "later.txt").exists()  # the later commit is not included
    # status() stays meaningful with a sha base.
    status = service.status(repo, worktree, created["worktree_branch"], created["base_branch"])
    assert status["dirty"] is False


@pytest.mark.unit
def test_model_can_enter_the_created_worktree_within_the_same_run(tmp_path: Path) -> None:
    """Enter-without-new-run: the worktree is an ordinary local directory, so an
    in-run edit under ``worktree_path`` lands there and never in the base workspace."""
    repo = tmp_path / "repo"
    pinned = _init_repo(repo)

    service = WorktreeService(tmp_path / "data")
    created = service.create(repo, "12345678-cccc-dddd", base_branch=pinned)
    worktree = Path(created["worktree_path"])

    # The model writes with absolute paths inside the returned worktree.
    note = worktree / "notes" / "finding.txt"
    note.parent.mkdir()
    note.write_text("written from the same run", encoding="utf-8")

    assert note.read_text(encoding="utf-8") == "written from the same run"
    assert not (repo / "notes").exists()  # base workspace untouched
    status = service.status(repo, worktree, created["worktree_branch"], created["base_branch"])
    assert status["dirty"] is True and any(
        entry.startswith("notes/") for entry in status["changed_files"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_worktree_manage_create_passes_pinned_sha_to_the_service(tmp_path: Path) -> None:
    """The model tool surface forwards the pinned sha and persists it as base_branch."""
    from atlas.tools.workspace_workflows import workspace_workflow_dispatch

    repo = tmp_path / "repo"
    pinned = _init_repo(repo)
    received: dict[str, Any] = {}

    class RecordingService:
        def create(self, workspace: Path, conversation_id: str, base_branch: str | None,
                   name: str | None = None) -> dict[str, str]:
            received.update(workspace=str(workspace), conversation_id=conversation_id,
                            base_branch=base_branch, name=name)
            short = conversation_id.replace("-", "")[:8]
            path = tmp_path / ".atlas-worktrees" / "repo" / short
            path.mkdir(parents=True)  # like `git worktree add`, the directory exists afterwards
            return {"worktree_path": str(path), "worktree_branch": f"atlas/{short}",
                    "base_branch": base_branch or ""}

    class Memory:
        saved: dict[str, Any] = {}

        async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
            return {"conversation_id": conversation_id, "worktree_path": "",
                    "workspace": str(repo)}

        async def update_conversation(self, conversation_id: str, **changes: Any) -> bool:
            Memory.saved = {"conversation_id": conversation_id, **changes}
            return True

    runtime = SimpleNamespace(
        conversation_id="12345678-aaaa-bbbb",
        workspace=str(repo),
        permission_mode="full_access",
        read_only=False,
        mode="act",
        workspace_worktree_service=RecordingService(),
    )
    result = await workspace_workflow_dispatch(
        "workspace_worktree_manage",
        {"action": "create", "base_branch": pinned},
        SimpleNamespace(_memory=Memory()),
        runtime,
    )

    assert result["outcome"] == "completed"
    assert received["base_branch"] == pinned  # the sha reached the git layer unchanged
    assert Memory.saved["base_branch"] == pinned  # and is persisted on the conversation
    assert Memory.saved["worktree_branch"] == "atlas/12345678"
