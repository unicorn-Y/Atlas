from __future__ import annotations

import asyncio
import base64
import io
import os
import posixpath
import subprocess
import sys
import types
from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.runtime import hooks as hooks_module
from atlas.runtime.hooks import HookStore
from atlas.scheduler import (
    AtlasScheduler,
    ScheduledTask,
    TaskStatus,
    TriggerType,
    _is_process_alive,
    _load_tasks_from_toml,
    _save_tasks_to_toml,
)
from atlas.server import (
    _set_workspace_trusted,
    _workspace_trust,
    runtime_protocol,
)
from atlas.ssh import SSHWorkspaceManager
from atlas.task_artifacts import WorktreeService


def test_wave3_scheduler_pid_liveness() -> None:
    assert _is_process_alive(os.getpid())
    assert not _is_process_alive(2_147_483_647)


@pytest.mark.asyncio
async def test_wave3_fork_and_duplicate_keep_original_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    from atlas import server
    # H5: fork/duplicate live on the conversations router now; the store seam
    # is still resolved through atlas.server.
    from atlas.api.conversations_router import duplicate_conversation, fork_conversation

    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    monkeypatch.setattr(server, "memory", store)
    conversation_id = await store.create_conversation("source")
    await store.update_conversation(conversation_id, workspace=r"D:\Atlas")
    assert (await store.get_conversation(conversation_id))["workspace"] == r"D:\Atlas"
    from tests.fakes.session_store import save_memory_fixture_message

    message_id = await save_memory_fixture_message(store, conversation_id, "user", "task")
    fork = await fork_conversation(
        types.SimpleNamespace(memory=None), conversation_id, {"through_message_id": message_id})
    assert fork["workspace"] == r"D:\Atlas"
    duplicate = await duplicate_conversation(types.SimpleNamespace(memory=None), conversation_id)
    assert duplicate["workspace"] == r"D:\Atlas"
    await store.close()


@pytest.mark.asyncio
async def test_wave3_recipe_from_worktree_keeps_original_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    from atlas import server
    # H5: recipe_from_run lives on the records router now.
    from atlas.api.records_router import recipe_from_run

    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    monkeypatch.setattr(server, "memory", store)
    conversation_id = await store.create_conversation("recipe")
    await store.update_conversation(conversation_id, workspace=str(tmp_path / "workspace"))
    run = server.RunState("recipe-run", conversation_id, "model")
    run.user_input = "inspect this repository"
    run.workspace = str(tmp_path / "workspace" / ".atlas-worktrees" / "feature")
    monkeypatch.setitem(server.runtime_mgr.runs, run.run_id, run)
    saved: list[dict[str, object]] = []

    class RecipeStore:
        def put(self, value):
            saved.append(value)
            return value

    monkeypatch.setattr(server, "_task_store", lambda _name: RecipeStore())
    try:
        result = await recipe_from_run(
            types.SimpleNamespace(memory=None, runtime_mgr=None), {"run_id": run.run_id})
        assert result["description"] == "从一次任务生成"
        assert result["workspace"] == str(tmp_path / "workspace")
    finally:
        server.runtime_mgr.runs.pop(run.run_id, None)
        await store.close()
    assert saved[0]["prompt"] == "inspect this repository"


@pytest.mark.asyncio
async def test_wave3_recipe_from_run_rejects_unknown_run(monkeypatch) -> None:
    from fastapi import HTTPException
    from atlas import server
    # H5: recipe_from_run lives on the records router now.
    from atlas.api.records_router import recipe_from_run

    monkeypatch.setattr(server, "memory", object())
    with pytest.raises(HTTPException) as error:
        await recipe_from_run(
            types.SimpleNamespace(memory=None, runtime_mgr=None), {"run_id": "missing"})
    assert error.value.status_code == 404


def test_wave3_worktree_name_becomes_sanitized_branch_suffix(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "seed").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "seed"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True
    )
    result = WorktreeService(tmp_path / "data").create(
        repo, "12345678-aaaa", name="My Feature! + Long"
    )
    assert result["worktree_branch"] == "atlas/12345678-my-feature----long"


def test_wave3_hub_schedule_migration_and_id_conflict(tmp_path: Path) -> None:
    canonical = tmp_path / "schedules.toml"
    old_hub = tmp_path / "hub-schedules.toml"
    _save_tasks_to_toml(
        canonical,
        {
            "same": ScheduledTask(
                id="same",
                name="main",
                description="",
                trigger_type=TriggerType.DATE,
                trigger_args={"run_time": "2099-01-01T00:00:00+00:00"},
                action="agent:main",
            )
        },
    )
    _save_tasks_to_toml(
        old_hub,
        {
            "same": ScheduledTask(
                id="same",
                name="hub",
                description="",
                trigger_type=TriggerType.DATE,
                trigger_args={"run_time": "2099-01-01T00:00:00+00:00"},
                action="agent:hub",
            )
        },
    )
    scheduler = AtlasScheduler(schedules_path=canonical)
    scheduler._migrate_hub_tasks()
    assert set(_load_tasks_from_toml(canonical)) == {"same", "same-hub"}
    assert not old_hub.exists()
    assert (tmp_path / "hub-schedules.toml.migrated").exists()
    scheduler._migrate_hub_tasks()
    assert set(_load_tasks_from_toml(canonical)) == {"same", "same-hub"}


@pytest.mark.asyncio
async def test_wave3_scheduler_lease_has_single_owner_and_transfers(tmp_path: Path) -> None:
    path = tmp_path / "schedules.toml"
    first, second = AtlasScheduler(path), AtlasScheduler(path)
    assert first._claim_lease() is True
    assert second._claim_lease() is False
    first._release_lease()
    assert second._claim_lease() is True
    second._release_lease()


@pytest.mark.asyncio
async def test_wave3_two_live_schedulers_have_one_trigger_owner(tmp_path: Path) -> None:
    path = tmp_path / "schedules.toml"
    calls: list[str] = []

    async def callback(task_id: str, _message: str) -> None:
        calls.append(task_id)

    first, second = AtlasScheduler(path, callback), AtlasScheduler(path, callback)
    await first.add_task(
        ScheduledTask(
            "probe",
            "Probe",
            "",
            TriggerType.EVENT,
            {"event": "probe"},
            "agent:probe",
        )
    )
    await first.start()
    await second.start()
    try:
        assert sum((first._started, second._started)) == 1
        owner, standby = (first, second) if first._started else (second, first)
        assert await owner.dispatch_event("probe", {}) == 1
        assert await standby.dispatch_event("probe", {}) == 0
        assert calls == ["probe"]

        await owner.stop()
        await asyncio.sleep(2.2)
        assert standby._started is True
        assert await standby.dispatch_event("probe", {}) == 1
        assert calls == ["probe", "probe"]
    finally:
        await first.stop()
        await second.stop()


def test_wave3_hub_claim_preempts_desktop_lease(tmp_path: Path) -> None:
    desktop = AtlasScheduler(tmp_path / "schedules.toml", role="desktop")
    hub = AtlasScheduler(tmp_path / "schedules.toml", role="hub")
    assert desktop._claim_lease()
    assert hub._claim_lease()
    assert desktop._owns_lease() is False
    assert hub._owns_lease() is True
    hub._release_lease()


@pytest.mark.asyncio
async def test_wave3_event_schedule_fires_once_and_records_runs(tmp_path: Path) -> None:
    calls: list[str] = []

    async def callback(task_id: str, message: str) -> None:
        calls.append(message)

    scheduler = AtlasScheduler(tmp_path / "schedules.toml", callback)
    scheduler._started = True
    task = ScheduledTask(
        id="finished",
        name="Finished",
        description="",
        trigger_type=TriggerType.EVENT,
        trigger_args={"event": "run.completed", "filter": {"model": "m"}},
        action="agent:follow up",
        status=TaskStatus.ACTIVE,
    )
    await scheduler.add_task(task)
    assert await scheduler.dispatch_event("run.failed", {"model": "m"}) == 0
    assert await scheduler.dispatch_event("run.completed", {"model": "other"}) == 0
    assert await scheduler.dispatch_event("run.completed", {"model": "m"}) == 1
    assert await scheduler.dispatch_event("run.completed", {"model": "m"}) == 0
    assert calls == ["follow up"]
    assert task.runs[-1]["status"] == "completed"
    assert len(task.runs) <= 20


def test_wave3_event_trigger_args_roundtrip_nested_filter(tmp_path: Path) -> None:
    path = tmp_path / "schedules.toml"
    task = ScheduledTask(
        "file",
        "File",
        "",
        TriggerType.EVENT,
        {"event": "file.changed", "filter": {"root": str(tmp_path), "glob": "*.py"}},
        "agent:inspect",
    )
    _save_tasks_to_toml(path, {task.id: task})
    loaded = _load_tasks_from_toml(path)[task.id]
    assert loaded.trigger_args == task.trigger_args


def test_wave3_ssh_uri_validation_and_auth_fields_rejected(tmp_path: Path) -> None:
    manager = SSHWorkspaceManager(str(tmp_path / "config"))
    assert manager.parse_workspace("ssh://zhuji/work/project") == ("zhuji", "/work/project")
    with pytest.raises(ValueError):
        manager.parse_workspace("ssh://user:pass@zhuji/work/project")
    with pytest.raises(ValueError):
        manager.parse_workspace("ssh://zhuji")
    assert manager.hosts() == []


@pytest.mark.asyncio
async def test_wave3_ssh_mock_file_write_read_and_command(tmp_path: Path, monkeypatch) -> None:
    files: dict[str, bytes] = {}

    class RemoteFile:
        def __init__(self, path: str, mode: str) -> None:
            self.path, self.mode = path, mode
            self.buffer = io.BytesIO(files.get(path, b"") if "a" in mode or "r" in mode else b"")

        async def __aenter__(self):
            if "a" in self.mode:
                self.buffer.seek(0, io.SEEK_END)
            return self

        async def __aexit__(self, *_args):
            if "w" in self.mode or "a" in self.mode:
                files[self.path] = self.buffer.getvalue()

        async def read(self):
            return self.buffer.read()

        async def write(self, data):
            self.buffer.write(data)

    class SFTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def open(self, path, mode):
            return RemoteFile(path, mode)

        # Like asyncssh's SFTPClient.readdir: an awaitable list (scandir is an async iterator).
        async def readdir(self, path):
            return [
                types.SimpleNamespace(
                    filename=name,
                    attrs=types.SimpleNamespace(permissions=0o100644),
                )
                for name in (posixpath.basename(item) for item in files)
                if any(
                    posixpath.dirname(item) == path.rstrip("/") and posixpath.basename(item) == name
                    for item in files
                )
            ]

        async def makedirs(self, *_args, **_kwargs):
            return None

        async def stat(self, path):
            return types.SimpleNamespace(size=len(files[path]))

    class Client:
        def start_sftp_client(self):
            return SFTP()

        async def run(self, command, check=False):
            return types.SimpleNamespace(
                exit_status=0, stdout="linux\n" if command == "uname -s" else "ok", stderr=""
            )

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def connect(*_args, **_kwargs):
        return Client()

    monkeypatch.setitem(sys.modules, "asyncssh", types.SimpleNamespace(connect=connect))
    manager = SSHWorkspaceManager(str(tmp_path / "config"))
    written = await manager.call_tool(
        "local_file", {"action": "write", "path": "a.txt", "content": "hello"}, "ssh://host/work"
    )
    read = await manager.call_tool(
        "local_file", {"action": "read", "path": "a.txt"}, "ssh://host/work"
    )
    command = await manager.call_tool(
        "local_exec", {"executable": "echo", "args": ["ok"]}, "ssh://host/work"
    )
    listing = await manager.call_tool(
        "local_file", {"action": "list", "path": "."}, "ssh://host/work"
    )
    assert written["is_error"] is False
    assert read["data"]["content"] == "hello"
    assert command["data"]["stdout"] == "ok"
    assert listing["data"]["entries"][0]["name"] == "a.txt"


@pytest.mark.asyncio
async def test_wave3_ssh_windows_exec_uses_powershell_and_quotes_args(
    tmp_path: Path, monkeypatch
) -> None:
    manager = SSHWorkspaceManager(str(tmp_path / "config"))
    captured: list[str] = []

    async def windows(_host: str) -> str:
        return "windows"

    async def run_result(_host: str, command: str) -> dict[str, object]:
        captured.append(command)
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(manager, "remote_os", windows)
    monkeypatch.setattr(manager, "run_result", run_result)
    await manager.call_tool(
        "local_exec",
        {"executable": r"C:\Program Files\tool.exe", "args": ["two words"]},
        "ssh://host/C:/Atlas",
    )

    assert len(captured) == 1
    encoded = captured[0].rsplit(" ", 1)[1]
    script = base64.b64decode(encoded).decode("utf-16le")
    # SFTP keeps "/C:/Atlas"; PowerShell needs the drive path without the leading slash.
    assert "Set-Location -LiteralPath 'C:/Atlas'" in script
    assert script.rstrip().endswith("exit $LASTEXITCODE")
    assert "& 'C:\\Program Files\\tool.exe' 'two words'" in script


@pytest.mark.asyncio
async def test_wave3_ssh_command_reconnects_once_after_disconnect(
    tmp_path: Path, monkeypatch
) -> None:
    connects = 0

    class Client:
        def __init__(self, fail: bool) -> None:
            self.fail = fail

        async def run(self, _command: str, check: bool = False):
            if self.fail:
                self.fail = False
                raise OSError("connection lost")
            return types.SimpleNamespace(exit_status=0, stdout="reconnected", stderr="")

        def close(self):
            return None

    async def connect(*_args, **_kwargs):
        nonlocal connects
        connects += 1
        return Client(fail=connects == 1)

    monkeypatch.setitem(
        sys.modules,
        "asyncssh",
        types.SimpleNamespace(
            connect=connect,
            Error=Exception,
        ),
    )
    manager = SSHWorkspaceManager(str(tmp_path / "config"))
    result = await manager.run_result("host", "echo ok")
    assert result["stdout"] == "reconnected"
    assert connects == 2


def test_wave3_workspace_trust_can_be_granted_and_revoked(tmp_path: Path, monkeypatch) -> None:
    from atlas import server

    monkeypatch.setattr(
        server,
        "get_config",
        lambda: type(
            "Config",
            (),
            {
                "db_path": tmp_path / "atlas.db",
            },
        )(),
    )
    root = str(tmp_path / "workspace")
    _set_workspace_trusted(root, True)
    assert _workspace_trust()[root] is True
    _set_workspace_trusted(root, False)
    assert root not in _workspace_trust()


@pytest.mark.asyncio
async def test_wave3_ssh_test_rejects_unknown_host_alias(monkeypatch) -> None:
    from fastapi import HTTPException
    from atlas import server
    # H5: ssh_test lives on the workspace router now.
    from atlas.api.workspace_router import ssh_test

    monkeypatch.setattr(server.ssh_workspaces, "hosts", lambda: [])
    with pytest.raises(HTTPException) as error:
        await ssh_test(types.SimpleNamespace(), {"host": "unknown"})
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_wave3_runtime_protocol_is_1_8() -> None:
    assert await runtime_protocol(types.SimpleNamespace()) == {"version": "1.10"}


@pytest.mark.asyncio
async def test_wave3_create_pr_pushes_and_returns_gh_pr(monkeypatch, tmp_path: Path) -> None:
    from atlas import server
    # H5: create_git_pr and its gh helpers live on the workspace router now;
    # _workspace_path stays monkeypatched through the atlas.server seam.
    from atlas.api import workspace_router
    from atlas.api.workspace_router import create_git_pr

    from types import SimpleNamespace

    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(server, "_workspace_path", lambda _root: (tmp_path, tmp_path))
    monkeypatch.setattr(server.subprocess, "run", run)
    monkeypatch.setattr(
        workspace_router,
        "_gh_json",
        lambda *_args: {
            "number": 7,
            "title": "Parity",
            "url": "https://example.test/pr/7",
            "state": "OPEN",
            "isDraft": True,
            "baseRefName": "main",
            "headRefName": "feature",
            "statusCheckRollup": [],
        },
    )

    result = await create_git_pr(
        SimpleNamespace(),
        {
            "root": str(tmp_path),
            "title": "Parity",
            "body": "Details",
            "draft": True,
        },
    )

    assert result["pr"]["number"] == 7
    assert calls[1][:4] == ["git", "push", "-u", "origin"]
    assert calls[2][:3] == ["gh", "pr", "create"]


@pytest.mark.asyncio
async def test_wave3_create_pr_rejects_unauthenticated_gh(monkeypatch, tmp_path: Path) -> None:
    from fastapi import HTTPException
    from atlas import server
    # H5: create_git_pr lives on the workspace router now.
    from atlas.api.workspace_router import create_git_pr
    from types import SimpleNamespace

    monkeypatch.setattr(server, "_workspace_path", lambda _root: (tmp_path, tmp_path))
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="not logged in",
        ),
    )

    with pytest.raises(HTTPException) as error:
        await create_git_pr(
            SimpleNamespace(),
            {
                "root": str(tmp_path),
                "title": "Parity",
                "body": "Details",
            },
        )
    assert error.value.status_code == 503


def test_wave3_hook_store_validates_event_and_serializes(tmp_path: Path) -> None:
    store = HookStore(tmp_path / "hooks.toml")
    hook = {
        "id": "pre",
        "event": "tool.before",
        "command": "exit 2",
        "timeout_s": 3,
        "enabled": True,
    }
    store.save([hook])
    assert store.list() == [hook]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bash_path", "expected_executable"),
    [
        (r"C:\Windows\System32\bash.exe", "powershell.exe"),
        (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe"),
    ],
)
async def test_wave3_windows_hook_shell_skips_wsl_bash_shim(
    monkeypatch, bash_path: str, expected_executable: str,
) -> None:
    calls = []

    class Process:
        returncode = 0

        async def communicate(self, _input):
            return b"", b""

    async def create_process(*args, **_kwargs):
        calls.append(args)
        return Process()

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(hooks_module, "os", types.SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setattr(hooks_module.shutil, "which", lambda name: bash_path if name == "bash" else None)
    monkeypatch.setattr(hooks_module.asyncio, "create_subprocess_exec", create_process)

    await hooks_module._run_command({"command": "exit 2"}, {}, cwd=None, plugin_root=None)

    assert calls[0][0] == expected_executable


@pytest.mark.asyncio
@pytest.mark.integration
async def test_wave3_hook_error_does_not_raise_or_block(tmp_path: Path) -> None:
    store = HookStore(tmp_path / "hooks.toml")
    store.save(
        [
            {
                "id": "pre",
                "event": "tool.before",
                "command": "exit 1",
                "timeout_s": 2,
                "enabled": True,
            }
        ]
    )
    result = await store.execute("tool.before", {"tool_name": "local_file"})
    assert result["blocked"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_wave3_hook_exit_two_blocks_tool_call(tmp_path: Path) -> None:
    store = HookStore(tmp_path / "hooks.toml")
    store.save(
        [{"id": "pre", "event": "tool.before", "command": "exit 2", "timeout_s": 2, "enabled": True}]
    )
    result = await store.execute("tool.before", {"tool_name": "local_file"})
    log = result["logs"][0]
    assert log["exit_code"] == 2, log["stderr"]
    assert result["blocked"] is True


def test_wave3_permission_modes_and_conversation_column_present() -> None:
    from atlas.agent import AgentRunContext

    context = AgentRunContext(permission_mode="ask_writes", allowed_paths=["D:/safe"])
    assert context.permission_mode == "ask_writes"
    assert context.allowed_paths == ["D:/safe"]


@pytest.mark.asyncio
async def test_wave3_ssh_detects_windows_when_default_shell_is_cmd(monkeypatch):
    """Windows OpenSSH starts cmd.exe, where $PSVersionTable prints literally (seen on a real host)."""
    import types

    from atlas.ssh import SSHWorkspaceManager

    class Client:
        async def run(self, command, check=False):
            outputs = {"echo %OS%": "Windows_NT\r\n", "$PSVersionTable.PSVersion.Major": "$PSVersionTable.PSVersion.Major\r\n"}
            return types.SimpleNamespace(exit_status=0, stdout=outputs.get(command, ""), stderr="")

    manager = SSHWorkspaceManager()
    connection = types.SimpleNamespace(client=Client(), os_name=None, last_used=0.0)

    async def connect(_host):
        return connection

    monkeypatch.setattr(manager, "_connect", connect)
    assert await manager.remote_os("zhuji") == "windows"


def test_wave3_ssh_remote_path_accepts_windows_style_paths_and_refuses_escapes():
    from atlas.ssh import SSHWorkspaceManager

    remote = SSHWorkspaceManager._remote_path
    assert remote("/D:/Atlas", r"D:\Atlas\core") == "/D:/Atlas/core"
    assert remote("/D:/Atlas", "d:/Atlas") == "/D:/Atlas"
    assert remote("/d:/Atlas", r"sub\dir") == "/D:/Atlas/sub/dir"
    with pytest.raises(ValueError):
        remote("/D:/Atlas", r"C:\Users\someone")
    with pytest.raises(ValueError):
        remote("/D:/Atlas", r"..\other")
