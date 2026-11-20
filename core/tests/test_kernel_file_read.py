import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.engine.kernel.edit import EditManager
from atlas.engine.kernel.loop import AtlasKernel


@pytest.mark.unit
def test_read_file_page_records_full_or_partial_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "fixture.txt"
    target.write_bytes(b"first\nsecond\nthird\n")
    manager = EditManager(workspace, allowed_paths=[str(workspace)])

    page = manager.read_file_page("fixture.txt", offset=1, limit=1)

    assert page == "second\n"
    assert manager.reads[manager._key(target.resolve())].complete is False
    with pytest.raises(ValueError, match="READ_REQUIRED"):
        manager._existing(target.resolve())

    complete = manager.read_file_page(target, offset=0, limit=None)

    assert complete == "first\nsecond\nthird\n"
    assert manager.reads[manager._key(target.resolve())].complete is True
    assert manager._existing(target.resolve()).text == complete


@pytest.mark.unit
def test_read_file_page_rejects_paths_outside_authorized_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("do not read", encoding="utf-8")
    manager = EditManager(workspace, allowed_paths=[str(workspace)])

    with pytest.raises(PermissionError, match="outside the authorized paths"):
        manager.read_file_page(outside, offset=0, limit=None)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_kernel_read_file_routes_ssh_workspace_to_remote_seam(monkeypatch) -> None:
    kernel = object.__new__(AtlasKernel)
    runtime = SimpleNamespace(
        tool_mode="native", workspace="ssh://fixture.invalid/srv/project",
        conversation_id="trusted-conversation-42",
    )
    calls = []

    async def remote_read(workspace, path, *, offset=0, limit=None, observation_owner_id=None):
        calls.append((workspace, path, offset, limit, observation_owner_id))
        return "remote fixture content"

    from atlas.ssh import ssh_workspaces

    monkeypatch.setattr(ssh_workspaces, "read_workspace_file", remote_read)

    result = await kernel._dispatch(
        None, runtime, None, "read_file",
        {"path": "README.md", "offset": 5, "limit": 20}, asyncio.Queue(),
    )

    assert calls == [(
        "ssh://fixture.invalid/srv/project", "README.md", 5, 20,
        "trusted-conversation-42",
    )]
    assert result["outcome"] == "completed"
    assert result["content"] == "remote fixture content"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_kernel_read_file_fails_closed_without_workspace_file_manager(tmp_path: Path) -> None:
    kernel = object.__new__(AtlasKernel)
    runtime = SimpleNamespace(tool_mode="native", workspace=str(tmp_path))

    result = await kernel._dispatch(
        None, runtime, None, "read_file", {"path": "fixture.txt"}, asyncio.Queue(),
    )

    assert result["outcome"] == "denied"
    assert "no workspace-scoped file manager" in result["content"]
