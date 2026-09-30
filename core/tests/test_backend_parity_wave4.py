from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.ssh import SSHWorkspaceManager
from atlas.agent import _ssh_paths_allowed
from atlas.task_artifacts import DEFAULT_PROFILES, TomlRecordStore, seed_profiles
from atlas.server import RunState, _handle_rules_trust


def test_builtin_profile_names_and_descriptions_are_chinese() -> None:
    profiles = {profile["id"]: profile for profile in DEFAULT_PROFILES}
    assert set(profiles) >= {"default", "architect", "reviewer"}
    for profile_id in ("default", "architect", "reviewer"):
        assert any("\u4e00" <= char <= "\u9fff" for char in profiles[profile_id]["name"])
        assert any("\u4e00" <= char <= "\u9fff" for char in profiles[profile_id]["description"])


def test_profile_seeding_localizes_existing_builtin_records(tmp_path: Path) -> None:
    store = TomlRecordStore(tmp_path, "profiles")
    store.put({
        "id": "reviewer", "name": "Reviewer", "description": "Read-only code review",
        "instructions": "Review code for correctness, regressions, and security issues. Do not modify files.",
        "tools": {"allow": ["local_file"], "deny": []},
        "mode": "act", "active_skills": ["existing-skill"],
    })

    seed_profiles(store)
    reviewer = store.get("reviewer")
    assert reviewer["name"] == "审查员"
    assert reviewer["description"] == "只读代码审查"
    assert reviewer["tools"]["allow"] == ["local_file"]
    assert reviewer["active_skills"] == ["existing-skill"]


def test_allowed_paths_check_ssh_paths_after_remote_normalization() -> None:
    workspace = "ssh://host/D:/work/project"
    assert _ssh_paths_allowed(
        workspace, ["D:/work/project/src"], ["src/module.py"],
    )
    assert not _ssh_paths_allowed(
        workspace, ["D:/work/project/src"], ["../secrets.txt"],
    )


@pytest.mark.asyncio
async def test_conversation_runtime_settings_are_persisted(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conversation_id = await store.create_conversation("settings")
    await store.update_conversation(
        conversation_id,
        workspace=r"D:\Atlas",
        permission_mode="ask_writes",
        allowed_paths=[r"D:\Atlas\core"],
        executor="codex",
        sandbox={"type": "docker", "network": False},
        sandbox_set=True,
    )

    conversation = await store.get_conversation(conversation_id)
    assert conversation["workspace"] == r"D:\Atlas"
    assert conversation["permission_mode"] == "ask_writes"
    assert conversation["allowed_paths"] == [r"D:\Atlas\core"]
    assert conversation["executor"] == "codex"
    assert conversation["sandbox"] == {"type": "docker", "network": False}
    assert (await store.list_conversations())[0]["sandbox"] == {
        "type": "docker", "network": False,
    }
    await store.close()


@pytest.mark.asyncio
async def test_rules_trust_falls_back_to_run_id_and_errors_when_unmatched(monkeypatch) -> None:
    from atlas import server

    run = RunState("trust-run", "conversation", "model")
    run.trust_future = asyncio.get_running_loop().create_future()
    run.trust_event_id = "trust-run:2"
    monkeypatch.setitem(server.runtime_mgr.runs, run.run_id, run)
    sent: list[dict] = []

    async def send(conn_id: str, frame: dict) -> None:
        sent.append(frame)

    monkeypatch.setattr(server.runtime_mgr, "send", send)
    await _handle_rules_trust("conn", {
        "run_id": run.run_id, "event_id": "stale-event", "trust": False,
    })
    assert run.trust_future.result() is False

    await _handle_rules_trust("conn", {
        "run_id": "missing-run", "event_id": "stale-event", "trust": True,
    })
    assert sent[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_real_ssh_workspace_when_configured(monkeypatch) -> None:
    import os
    import uuid

    host = os.environ.get("ATLAS_SSH_TEST_HOST")
    root = os.environ.get("ATLAS_SSH_TEST_ROOT")
    if not host or not root:
        pytest.skip("set ATLAS_SSH_TEST_HOST and ATLAS_SSH_TEST_ROOT for a real SSH check")

    manager = SSHWorkspaceManager()
    workspace = f"ssh://{host}/{root.lstrip('/').replace(chr(92), '/')}"
    _host, remote_root = manager.parse_workspace(workspace)
    connection = await manager._connect(_host)
    assert connection.client
    remote_windows = await manager.remote_os(_host) == "windows"
    leaf = f"atlas-wave4-{uuid.uuid4().hex}"
    directory = manager._remote_path(remote_root, leaf)
    file_path = manager._remote_path(remote_root, f"{leaf}/roundtrip.txt")
    await manager.call_tool("local_file", {
        "action": "mkdir", "path": leaf,
    }, workspace)
    await manager.call_tool("local_file", {
        "action": "write", "path": f"{leaf}/roundtrip.txt", "content": "wave4",
    }, workspace)
    read = await manager.call_tool("local_file", {
        "action": "read", "path": f"{leaf}/roundtrip.txt",
    }, workspace)
    assert read["data"]["content"] == "wave4"

    nested = manager._remote_path(directory, "child")
    await manager.call_tool("local_file", {"action": "mkdir", "path": f"{leaf}/child"}, workspace)
    result = await manager.call_tool("local_shell", {
        "command": "Get-Location" if remote_windows else "pwd", "cwd": nested,
    }, workspace)
    assert result["data"]["exit_code"] == 0
    assert nested.casefold() in result["data"]["stdout"].replace("\\", "/").casefold()
    if remote_windows:
        windows_cwd = remote_root[1:] if remote_root.startswith("/") else remote_root
        cwd_result = await manager.call_tool("local_shell", {
            "command": "Get-Location", "cwd": windows_cwd,
        }, workspace)
        assert cwd_result["data"]["exit_code"] == 0
    with pytest.raises(ValueError):
        manager._remote_path(remote_root, "../outside")
    await manager.call_tool("local_file", {"action": "delete", "path": leaf}, workspace)

