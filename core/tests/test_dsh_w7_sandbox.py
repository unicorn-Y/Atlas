"""W7 evidence for per-call Docker sandbox modes and enforcement reporting."""

import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_escalation_approval_is_one_call_with_justification():
    from atlas.engine.kernel.loop import authorize_local_sandbox_request

    approvals = []

    async def approve(call_id, tool_name, arguments):
        approvals.append((call_id, tool_name, arguments))
        return "allow_once"

    result = await authorize_local_sandbox_request(
        {"sandbox_permissions": "read-only", "justification": "Inspect generated output"},
        approve,
        tool_name="local_shell",
        tool_call_id="tool-w7-1",
        sandbox_executor_available=True,
    )

    assert result["approved"] is True
    assert result["sandbox_enforced"] is True
    assert result["request"] == {
        "sandbox_permissions": "read-only",
        "justification": "Inspect generated output",
    }
    assert len(approvals) == 1
    assert approvals[0][2]["justification"] == "Inspect generated output"
    assert approvals[0][2]["_approval_no_always"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_call_read_only_uses_read_only_workspace_mount_and_reports_mode(
    tmp_path, monkeypatch,
):
    import atlas.sandbox as sandbox_module
    from atlas.sandbox import DockerSandboxManager

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[1] == "run" and "-d" in command:
            return SimpleNamespace(returncode=0, stdout="container-1\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="read ok", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    manager = DockerSandboxManager()
    await manager.start("run-1", str(tmp_path), {"type": "docker"})

    result = await manager.call_tool("run-1", "local_shell", {
        "command": "cat input.txt", "cwd": str(tmp_path),
        "sandbox_permissions": "read-only",
    })

    invocation = calls[1]
    assert invocation[1:5] == ["run", "--rm", "--network", "none"]
    mount = invocation[invocation.index("--mount") + 1]
    assert mount.startswith("type=bind,source=")
    assert mount.endswith(",target=/workspace,readonly")
    assert "container-1" not in invocation
    assert result["data"]["sandbox_permissions"] == "read-only"
    assert result["data"]["sandbox_enforced"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_call_workspace_write_uses_existing_writable_container_and_reports_mode(
    tmp_path, monkeypatch,
):
    import atlas.sandbox as sandbox_module
    from atlas.sandbox import DockerSandboxManager

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[1] == "run" and "-d" in command:
            return SimpleNamespace(returncode=0, stdout="container-1\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="write ok", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    manager = DockerSandboxManager()
    await manager.start("run-1", str(tmp_path), {"type": "docker"})

    result = await manager.call_tool("run-1", "local_shell", {
        "command": "touch output.txt", "cwd": str(tmp_path),
        "sandbox_permissions": "workspace-write",
    })

    invocation = calls[1]
    assert invocation[1:5] == ["exec", "-w", "/workspace", "container-1"]
    assert "--mount" not in invocation
    assert result["data"]["sandbox_permissions"] == "workspace-write"
    assert result["data"]["sandbox_enforced"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_danger_full_access_is_rejected_without_running_a_command(tmp_path, monkeypatch):
    import atlas.sandbox as sandbox_module
    from atlas.sandbox import DockerSandboxManager

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="container-1\n", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    manager = DockerSandboxManager()
    await manager.start("run-1", str(tmp_path), {"type": "docker"})

    result = await manager.call_tool("run-1", "local_shell", {
        "command": "touch outside.txt", "cwd": str(tmp_path),
        "sandbox_permissions": "danger-full-access",
    })

    assert len(calls) == 1
    assert result["is_error"] is True
    assert result["data"]["sandbox_permissions"] == "danger-full-access"
    assert result["data"]["sandbox_enforced"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ssh_workspace_sandbox_fails_closed_before_local_backend_or_command(
    monkeypatch,
):
    import atlas.sandbox as sandbox_module
    from atlas.sandbox import DockerSandboxManager

    local_backend_calls = []
    monkeypatch.setattr(
        sandbox_module.shutil, "which",
        lambda name: local_backend_calls.append(("which", name)) or "docker-mock",
    )
    monkeypatch.setattr(
        sandbox_module.subprocess, "run",
        lambda *args, **kwargs: local_backend_calls.append(("run", args, kwargs)),
    )
    manager = DockerSandboxManager()

    with pytest.raises(RuntimeError, match="target-native confinement runner"):
        await manager.start("remote-run", "ssh://atlas-host/workspace", {"type": "docker"})

    async def job_fallback(*_args, **_kwargs):
        local_backend_calls.append(("job-fallback",))

    monkeypatch.setattr(manager, "_host_job_fallback", job_fallback)
    with pytest.raises(RuntimeError, match="target-native confinement runner"):
        await manager.call_tool("remote-run", "local_exec", {
            "executable": "id", "args": [], "cwd": "ssh://atlas-host/workspace",
        })

    assert local_backend_calls == []
    assert manager._containers == {}
    assert manager._roots == {}


@pytest.mark.unit
def test_ssh_bwrap_argv_enforces_workspace_mode_and_network_policy():
    from atlas.ssh import SSHWorkspaceManager

    writable = SSHWorkspaceManager._sandbox_bwrap_argv(
        "/usr/bin/bwrap", "/srv/work", "/home/agent/work", "/home/agent/work/src",
        "/usr/bin/python3", ["-c", "print('ok')"], mode="workspace-write",
        network=False, environment={"LANG": "C.UTF-8"},
    )
    assert writable[:3] == ["/usr/bin/bwrap", "--die-with-parent", "--unshare-all"]
    assert "--share-net" not in writable
    assert writable[writable.index("--bind") + 1:writable.index("--bind") + 3] == [
        "/srv/work", "/home/agent/work",
    ]
    assert writable[writable.index("--chdir") + 1] == "/home/agent/work/src"
    assert writable[-4:] == ["--", "/usr/bin/python3", "-c", "print('ok')"]
    assert writable[writable.index("--setenv") + 1:writable.index("--setenv") + 3] == [
        "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    ]

    readonly_networked = SSHWorkspaceManager._sandbox_bwrap_argv(
        "/usr/bin/bwrap", "/srv/work", "/home/agent/work", "/home/agent/work",
        "/usr/bin/git", ["status"], mode="read-only", network=True, environment={},
    )
    assert readonly_networked.count("--share-net") == 1
    assert readonly_networked[readonly_networked.index("--ro-bind") + 1:
                              readonly_networked.index("--ro-bind") + 3] == [
        "/srv/work", "/home/agent/work",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ssh_bwrap_preflight_rejects_windows_before_remote_command(monkeypatch):
    from atlas.ssh import SSHWorkspaceManager

    class RemoteClient:
        def __init__(self):
            self.commands = []

        async def run(self, command, **_kwargs):
            self.commands.append(command)
            return SimpleNamespace(exit_status=0, stdout="/usr/bin/bwrap\n")

    client = RemoteClient()
    connection = SimpleNamespace(client=client)
    manager = SSHWorkspaceManager.__new__(SSHWorkspaceManager)

    async def resolve_authority(_host):
        return SimpleNamespace(id="authority-1")

    async def connect(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-1"
        return connection

    async def remote_os(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-1"
        return "windows"

    monkeypatch.setattr(manager, "resolve_authority", resolve_authority)
    monkeypatch.setattr(manager, "_connect", connect)
    monkeypatch.setattr(manager, "remote_os", remote_os)

    with pytest.raises(RuntimeError, match="available only on Linux"):
        await manager.prepare_remote_sandbox("ssh://atlas-host/home/agent/work")
    assert client.commands == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ssh_bwrap_preflight_pins_authority_and_checks_runner_before_use(monkeypatch):
    from contextlib import asynccontextmanager
    from atlas.ssh import SSHWorkspaceManager

    class Sftp:
        async def realpath(self, path):
            return path

    class Client:
        def __init__(self):
            self.commands = []

        async def run(self, command, **_kwargs):
            self.commands.append(command)
            if command == "command -v bwrap":
                return SimpleNamespace(exit_status=0, stdout="/usr/bin/bwrap\n")
            if command.startswith("stat -c"):
                return SimpleNamespace(exit_status=0, stdout="0 4755\n")
            return SimpleNamespace(exit_status=0, stdout="")

        @asynccontextmanager
        async def start_sftp_client(self):
            yield Sftp()

    client = Client()
    manager = SSHWorkspaceManager.__new__(SSHWorkspaceManager)
    connection = SimpleNamespace(client=client)
    async def resolve_authority(_host):
        return SimpleNamespace(id="authority-linux-1")
    async def connect(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-linux-1"
        return connection
    async def remote_os(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-linux-1"
        return "linux"
    monkeypatch.setattr(manager, "resolve_authority", resolve_authority)
    monkeypatch.setattr(manager, "_connect", connect)
    monkeypatch.setattr(manager, "remote_os", remote_os)

    runner = await manager.prepare_remote_sandbox("ssh://atlas-host/srv/work")

    assert runner == {
        "host": "atlas-host", "authority_id": "authority-linux-1",
        "bwrap": "/usr/bin/bwrap", "workspace_source": "/srv/work",
        "workspace_target": "/srv/work",
    }
    assert client.commands[0] == "command -v bwrap"
    assert client.commands[1].startswith("stat -c")
    assert "--unshare-all" in client.commands[2]
    assert all("authority-linux-1" not in command for command in client.commands)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ssh_bwrap_process_uses_existing_managed_argv_consumer(monkeypatch):
    from contextlib import asynccontextmanager
    from atlas.ssh import SSHWorkspaceManager

    class Sftp:
        async def realpath(self, path):
            return path

    class Client:
        @asynccontextmanager
        async def start_sftp_client(self):
            yield Sftp()

    manager = SSHWorkspaceManager.__new__(SSHWorkspaceManager)
    manager._processes = {}
    connection = SimpleNamespace(client=Client())

    async def connect(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-1"
        return connection

    captured = {}

    async def call_process(arguments, workspace, run_id=None, *, expected_authority_id=None):
        captured.update(arguments=arguments, workspace=workspace, run_id=run_id,
                        authority_id=expected_authority_id)
        manager._processes["sandbox-exec-1"] = SimpleNamespace(
            sandbox_backend=None, sandbox_permissions=None,
        )
        return {"data": {"execution_id": "sandbox-exec-1", "state": "running"},
                "content": [], "is_error": False}

    monkeypatch.setattr(manager, "_connect", connect)
    monkeypatch.setattr(manager, "call_process", call_process)

    result = await manager.call_sandboxed_process(
        {"action": "start", "executable": "python3", "args": ["-c", "print('x')"],
         "cwd": "ssh://atlas-host/srv/work/src", "env": {"LANG": "C.UTF-8"},
         "pty": False, "keep_stdin": False},
        "ssh://atlas-host/srv/work", "run-1",
        runner={"host": "atlas-host", "authority_id": "authority-1", "bwrap": "/usr/bin/bwrap",
                "workspace_source": "/srv/work", "workspace_target": "/srv/work"},
        mode="workspace-write", network=False,
    )

    args = captured["arguments"]
    assert captured["authority_id"] == "authority-1"
    assert captured["run_id"] == "run-1"
    assert args["executable"] == "/usr/bin/bwrap"
    assert args["env"] == {}
    assert args["args"][:2] == ["--die-with-parent", "--unshare-all"]
    assert "--share-net" not in args["args"]
    assert args["args"][args["args"].index("--bind") + 1:
                         args["args"].index("--bind") + 3] == ["/srv/work", "/srv/work"]
    assert args["args"][-4:] == ["--", "python3", "-c", "print('x')"]
    assert result["data"]["sandbox_backend"] == "ssh-bwrap"
    assert result["data"]["sandbox_permissions"] == "workspace-write"
    assert manager._processes["sandbox-exec-1"].sandbox_backend == "ssh-bwrap"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kernel_ssh_sandbox_process_dispatch_precedes_local_exec_manager(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from langchain_core.messages import AIMessage
    from atlas.agent import AgentOrchestrator, AgentRunContext

    monkeypatch.setattr("atlas.agent.safety_review_enabled", lambda: False)
    agent = AgentOrchestrator(
        SimpleNamespace(current_model="fixture-model"), SimpleNamespace(),
    )
    ssh_call = AsyncMock(return_value={
        "data": {"execution_id": "remote-sandbox-1", "state": "running",
                 "sandbox_backend": "ssh-bwrap"},
        "content": [{"type": "text", "text": "started"}], "is_error": False,
    })
    local_exec = SimpleNamespace(execute=AsyncMock())
    context = AgentRunContext(
        run_id="sandbox-run", conversation_id="sandbox-conversation",
        workspace="ssh://atlas-host/srv/work", sandbox_enabled=True,
        ssh_tool_callback=ssh_call, permission_mode="full_access",
        tool_allow=["local_process"],
    )
    context.exec_manager = local_exec
    context.model = "fixture-model"
    context.sandbox_tool_callback = AsyncMock()
    state = {
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "local_process", "args": {
                "action": "start", "executable": "python3", "args": ["-c", "print(1)"],
            }, "id": "sandbox-tool-1", "type": "tool_call",
        }])],
        "pending_events": [], "runtime": context,
    }

    result = await agent._execute_tools_node(state)

    ssh_call.assert_awaited_once()
    assert ssh_call.await_args.args[0] == "local_process"
    assert ssh_call.await_args.args[2] == "sandbox-run"
    local_exec.execute.assert_not_awaited()
    context.sandbox_tool_callback.assert_not_awaited()
    assert "started" in result["messages"][0].content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_conversation_accepts_ssh_bwrap_only_for_ssh_workspace(tmp_path):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from atlas.api.conversations_router import ConversationUpdateRequest, update_conversation
    from atlas.memory import MemoryStore

    store = MemoryStore(tmp_path / "sandbox-conversation.sqlite3")
    await store.init()
    conversation_id = await store.create_conversation("remote sandbox")
    services = SimpleNamespace(memory=store)
    try:
        await update_conversation(
            services, conversation_id,
            ConversationUpdateRequest(workspace="ssh://atlas-host/srv/work"),
        )
        await update_conversation(
            services, conversation_id,
            ConversationUpdateRequest(sandbox={"type": "ssh-bwrap", "network": False}),
        )
        saved = await store.get_conversation(conversation_id)
        assert saved["sandbox"] == {"type": "ssh-bwrap", "network": False}

        with pytest.raises(HTTPException, match="workspace"):
            await update_conversation(
                services, conversation_id,
                ConversationUpdateRequest(sandbox={"type": "docker", "network": False}),
            )

        local_id = await store.create_conversation("local workspace")
        await store.update_conversation(local_id, workspace=str(tmp_path))
        with pytest.raises(HTTPException, match="workspace"):
            await update_conversation(
                services, local_id,
                ConversationUpdateRequest(sandbox={"type": "ssh-bwrap", "network": False}),
            )
    finally:
        await store.close()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("failure", "message", "commands_expected"),
    [
        ("missing", "does not provide bubblewrap", 1),
        ("path", "executable path is invalid", 1),
        ("permissions", "root-owned", 2),
        ("probe", "workspace/namespace probe failed", 3),
    ],
)
@pytest.mark.asyncio
async def test_ssh_bwrap_preflight_failure_categories_never_run_user_command(
    monkeypatch, failure, message, commands_expected,
):
    from contextlib import asynccontextmanager
    from atlas.ssh import SSHWorkspaceManager

    class Sftp:
        async def realpath(self, path):
            return path

    class Client:
        def __init__(self):
            self.commands = []

        async def run(self, command, **_kwargs):
            self.commands.append(command)
            if command == "command -v bwrap":
                if failure == "missing":
                    return SimpleNamespace(exit_status=1, stdout="")
                path = "/tmp/bwrap" if failure == "path" else "/usr/bin/bwrap"
                return SimpleNamespace(exit_status=0, stdout=f"{path}\n")
            if command.startswith("stat -c"):
                permissions = "0 0777" if failure == "permissions" else "0 4755"
                return SimpleNamespace(exit_status=0, stdout=permissions)
            return SimpleNamespace(exit_status=1, stdout="", stderr="probe failed")

        @asynccontextmanager
        async def start_sftp_client(self):
            yield Sftp()

    client = Client()
    manager = SSHWorkspaceManager.__new__(SSHWorkspaceManager)
    connection = SimpleNamespace(client=client)

    async def resolve_authority(_host):
        return SimpleNamespace(id="authority-linux")

    async def connect(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-linux"
        return connection

    async def remote_os(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-linux"
        return "linux"

    monkeypatch.setattr(manager, "resolve_authority", resolve_authority)
    monkeypatch.setattr(manager, "_connect", connect)
    monkeypatch.setattr(manager, "remote_os", remote_os)

    with pytest.raises(RuntimeError, match=message):
        await manager.prepare_remote_sandbox("ssh://atlas-host/srv/work")

    assert len(client.commands) == commands_expected
    assert all("touch" not in command and "user-command" not in command
               for command in client.commands)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ssh_bwrap_process_rejects_changed_authority_before_start(monkeypatch):
    from unittest.mock import AsyncMock
    from atlas.ssh import SSHWorkspaceManager

    manager = SSHWorkspaceManager.__new__(SSHWorkspaceManager)
    manager._processes = {}
    starts = AsyncMock()

    async def connect(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-pinned"
        raise PermissionError("SSH target authority changed during operation")

    monkeypatch.setattr(manager, "_connect", connect)
    monkeypatch.setattr(manager, "call_process", starts)

    with pytest.raises(PermissionError, match="authority changed"):
        await manager.call_sandboxed_process(
            {"action": "start", "executable": "python3", "args": ["-c", "user-command"],
             "cwd": "ssh://atlas-host/srv/work", "env": {}},
            "ssh://atlas-host/srv/work", "run-1",
            runner={"host": "atlas-host", "authority_id": "authority-pinned",
                    "bwrap": "/usr/bin/bwrap", "workspace_source": "/srv/work",
                    "workspace_target": "/srv/work"},
            mode="workspace-write", network=False,
        )
    starts.assert_not_awaited()
    assert manager._processes == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ssh_bwrap_process_rejects_canonical_cwd_escape_before_start(monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from atlas.ssh import SSHWorkspaceManager

    class Sftp:
        async def realpath(self, _path):
            return "/srv/private"

    class Client:
        @asynccontextmanager
        async def start_sftp_client(self):
            yield Sftp()

    manager = SSHWorkspaceManager.__new__(SSHWorkspaceManager)
    manager._processes = {}
    starts = AsyncMock()

    async def connect(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-pinned"
        return SimpleNamespace(client=Client())

    monkeypatch.setattr(manager, "_connect", connect)
    monkeypatch.setattr(manager, "call_process", starts)

    with pytest.raises(PermissionError, match="cwd resolves outside"):
        await manager.call_sandboxed_process(
            {"action": "start", "executable": "python3", "args": ["-c", "user-command"],
             "cwd": "ssh://atlas-host/srv/work/src", "env": {}},
            "ssh://atlas-host/srv/work", "run-1",
            runner={"host": "atlas-host", "authority_id": "authority-pinned",
                    "bwrap": "/usr/bin/bwrap", "workspace_source": "/srv/work",
                    "workspace_target": "/srv/work"},
            mode="workspace-write", network=False,
        )
    starts.assert_not_awaited()
    assert manager._processes == {}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("slow_stage", "error_stage", "commands_expected"),
    [
        ("os", "target OS detection", 0),
        ("probe", "workspace/namespace probe", 3),
    ],
)
@pytest.mark.asyncio
async def test_ssh_bwrap_preflight_has_one_bounded_deadline(
    monkeypatch, slow_stage, error_stage, commands_expected,
):
    from contextlib import asynccontextmanager
    from atlas.ssh import SSHWorkspaceManager

    class Sftp:
        async def realpath(self, path):
            return path

    class Client:
        def __init__(self):
            self.commands = []

        async def run(self, command, **_kwargs):
            self.commands.append(command)
            if command == "command -v bwrap":
                return SimpleNamespace(exit_status=0, stdout="/usr/bin/bwrap\n")
            if command.startswith("stat -c"):
                return SimpleNamespace(exit_status=0, stdout="0 4755\n")
            if slow_stage == "probe":
                await asyncio.sleep(1)
            return SimpleNamespace(exit_status=0, stdout="")

        @asynccontextmanager
        async def start_sftp_client(self):
            yield Sftp()

    client = Client()
    manager = SSHWorkspaceManager.__new__(SSHWorkspaceManager)
    manager._SANDBOX_PREFLIGHT_TIMEOUT_SECONDS = 0.1
    connection = SimpleNamespace(client=client)

    async def resolve_authority(_host):
        return SimpleNamespace(id="authority-linux")

    async def connect(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-linux"
        return connection

    async def remote_os(_host, *, expected_authority_id=None):
        assert expected_authority_id == "authority-linux"
        if slow_stage == "os":
            await asyncio.sleep(1)
        return "linux"

    monkeypatch.setattr(manager, "resolve_authority", resolve_authority)
    monkeypatch.setattr(manager, "_connect", connect)
    monkeypatch.setattr(manager, "remote_os", remote_os)

    with pytest.raises(RuntimeError, match=f"timed out during {error_stage}"):
        await manager.prepare_remote_sandbox("ssh://atlas-host/srv/work")

    assert len(client.commands) == commands_expected
