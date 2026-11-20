"""SSH execution-world evidence (X30): a real asyncssh loopback server proves
that ``SSHWorkspaceManager``'s exec and fs channels travel the SSH wire —
run/exec, SFTP read/write/list, and remote edit — without an external host.

This exercises exactly the tool-level execution world Atlas has today
(``ssh.py``): local_file/local_edit/local_exec/local_git proxy to the remote
host while the workspace URI stays ``ssh://<alias>/<abs-path>``. It does not
claim the DSH "move fs/subprocess/sandbox wholesale" target, which is absent.
"""

import asyncio
import os
import posixpath
import threading
import time
from types import SimpleNamespace

import asyncssh
import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace

from atlas.ssh import SSHAuthority, SSHWorkspaceManager, _Connection
from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.engine.kernel.loop import AtlasKernel
from atlas.engine.kernel.exec import ExecManager

pytestmark = pytest.mark.unit

_LAST_LOOPBACK_CHILD: dict[str, object] = {}
_LOOPBACK_COMMANDS: list[dict[str, object]] = []
_LOOPBACK_COMMANDS_CHANGED = asyncio.Condition()


async def _serve_remote_command(process: asyncssh.SSHServerProcess) -> None:
    """Exec handler: run the requested command on this host (loopback stand-in
    for the remote machine) and return its streams over the SSH channel."""
    signal_event = asyncio.Event()
    command_record: dict[str, object] = {
        "kind": "terminal" if process.command.startswith("powershell.exe -NoLogo -NoProfile -NoExit") else "exec",
        "term_type": process.term_type,
        "term_size": process.term_size,
        "server_process": process,
    }
    async with _LOOPBACK_COMMANDS_CHANGED:
        _LOOPBACK_COMMANDS.append(command_record)
        _LOOPBACK_COMMANDS_CHANGED.notify_all()

    def _signal_received(_signal: str) -> None:
        signal_event.set()

    process.signal_received = _signal_received
    proc = await asyncio.create_subprocess_shell(
        process.command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "OS": "Windows_NT"},
    )
    _LAST_LOOPBACK_CHILD.clear()
    _LAST_LOOPBACK_CHILD.update({
        "pid": proc.pid,
        "returncode": proc.returncode,
        "stdin_closing": bool(proc.stdin and proc.stdin.is_closing()),
        "term_type": process.term_type,
        "term_size": process.term_size,
        "server_process": process,
    })

    async def _forward_output(reader, writer) -> None:
        try:
            while chunk := await reader.read(65536):
                writer.write(chunk.decode("utf-8", "replace"))
                await writer.drain()
        except (asyncio.CancelledError, OSError, asyncssh.Error):
            return

    async def _forward_input() -> None:
        try:
            async for chunk in process.stdin:
                if proc.stdin is None or proc.stdin.is_closing():
                    return
                proc.stdin.write(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
                await proc.stdin.drain()
        except (asyncio.CancelledError, OSError, asyncssh.Error):
            return
        finally:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
                await asyncio.wait_for(proc.stdin.wait_closed(), timeout=2.0)

    async def _terminate_fixture_tree() -> None:
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill.exe", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=3.0)
        else:
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except TimeoutError:
            if os.name != "nt":
                proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=3.0)

    output_tasks = [
        asyncio.create_task(_forward_output(proc.stdout, process.stdout)),
        asyncio.create_task(_forward_output(proc.stderr, process.stderr)),
        asyncio.create_task(_forward_input()),
    ]
    wait_task = asyncio.create_task(proc.wait())
    signal_task = asyncio.create_task(signal_event.wait())
    try:
        done, _ = await asyncio.wait({wait_task, signal_task}, return_when=asyncio.FIRST_COMPLETED)
        if signal_task in done and not wait_task.done():
            await _terminate_fixture_tree()
        return_code = await wait_task
        _LAST_LOOPBACK_CHILD["returncode"] = return_code
        input_task = output_tasks.pop()
        input_task.cancel()
        await asyncio.gather(input_task, return_exceptions=True)
        try:
            await asyncio.wait_for(asyncio.gather(*output_tasks, return_exceptions=True), timeout=2.0)
        except TimeoutError:
            states = []
            for task in output_tasks:
                frames = task.get_stack(limit=1)
                states.append({
                    "done": task.done(),
                    "top": frames[0].f_code.co_name if frames else None,
                })
            raise RuntimeError(
                "loopback output drain timeout "
                f"command_kind={'powershell' if process.command.startswith('powershell ') else 'other'} "
                f"return_code={return_code} tasks={states}"
            )
        process.exit(return_code or 0)
    finally:
        signal_task.cancel()
        if not wait_task.done():
            await _terminate_fixture_tree()
            await asyncio.gather(wait_task, return_exceptions=True)
        for task in output_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*output_tasks, return_exceptions=True)


class _LoopbackServer(asyncssh.SSHServer):
    def password_auth_supported(self) -> bool:
        return True

    def public_key_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == "z6" and password == "z6"

    def validate_public_key(self, username: str, _key: asyncssh.SSHKey) -> bool:
        return username == "z6"


class _ServerHarness:
    def __init__(self, tmp_path):
        self.root = tmp_path / "remote-root"
        self.root.mkdir(parents=True, exist_ok=True)
        self._key = asyncssh.generate_private_key("ssh-ed25519")
        self._acceptor = None
        self.client = None

    async def start(self):
        self._acceptor = await asyncssh.listen(
            "127.0.0.1", 0, server_host_keys=[self._key],
            server_factory=_LoopbackServer, process_factory=_serve_remote_command,
            sftp_factory=True, allow_scp=True,
        )
        listener = self._acceptor.sockets[0].getsockname()[1]
        self.client = await asyncssh.connect(
            "127.0.0.1", port=listener, known_hosts=None,
            username="z6", password="z6",
        )
        # Atlas keeps Windows SSH roots POSIX-style ("/C:/...", "/D:/...").
        self.workspace = f"ssh://z6looper/{self.root.as_posix()}"
        return self

    async def stop(self):
        if self.client is not None:
            self.client.close()
        if self._acceptor is not None:
            self._acceptor.close()
            await self._acceptor.wait_closed()


@pytest.fixture
async def ssh_world(tmp_path):
    harness = await _ServerHarness(tmp_path).start()
    try:
        yield harness
    finally:
        await harness.stop()


def _wired_manager(harness: _ServerHarness) -> SSHWorkspaceManager:
    """A manager whose connection pool is pre-wired to the loopback server."""
    mgr = SSHWorkspaceManager()
    authority = SSHAuthority(
        alias="z6looper", hostname="127.0.0.1", port=22, username="z6",
        identity_files=(), host_key_alias="z6looper", known_hosts=(), config_digest="loopback-fixture",
    )
    connection = _Connection(
        client=harness.client, last_used=time.monotonic(),
        authority_id=authority.id, authority=authority,
    )
    mgr._pool[authority.id] = connection

    async def _connect(_host: str, *, expected_authority_id: str | None = None) -> _Connection:
        if expected_authority_id is not None and expected_authority_id != authority.id:
            raise PermissionError("loopback fixture authority mismatch")
        connection.last_used = time.monotonic()
        return connection

    mgr._connect = _connect  # noqa: SLF001 - test wiring of the private pool seam
    return mgr


async def test_managed_ssh_process_streams_stdin_checks_owner_and_cancels(ssh_world):
    manager = _wired_manager(ssh_world)
    workspace = ssh_world.workspace
    authority_id = next(iter(manager._pool))
    connection = manager._pool[authority_id]
    started = await manager.call_process({
        "action": "start",
        "executable": "python",
        "args": ["-c", "import sys,time; print('ready',flush=True); print('input:'+sys.stdin.readline().strip(),flush=True); time.sleep(30)"],
        "cwd": workspace,
        "detached": False,
        "keep_stdin": True,
    }, workspace, run_id="ssh-owner-a")
    data = started["data"]
    execution_id = data["execution_id"]
    assert data["state"] == "running", started
    assert connection.active_leases == 1

    denied = await manager.call_process(
        {"action": "status", "execution_id": execution_id}, workspace, run_id="ssh-owner-b",
    )
    assert denied["is_error"] is True
    assert "different run" in denied["data"]["error"]

    record = manager._processes[execution_id]
    for _ in range(100):
        output = manager._read_process_output(record, "stdout", 0, 1024)["text"]
        if "ready" in output:
            break
        await asyncio.sleep(0.02)
    assert "ready" in output
    connection.last_used -= 301
    await manager._reap_idle_once()
    assert authority_id in manager._pool

    written = await manager.call_process({
        "action": "write_stdin", "execution_id": execution_id, "data": "payload\n",
    }, workspace, run_id="ssh-owner-a")
    assert written["data"]["bytes_written"] > 0
    await manager.cancel_run("ssh-owner-a")
    status = await manager.call_process(
        {"action": "status", "execution_id": execution_id}, workspace, run_id="ssh-owner-a",
    )
    assert status["data"]["state"] == "cancelled"
    assert connection.active_leases == 0
    final_output = manager._read_process_output(record, "stdout", 0, 1024)["text"]
    assert "input:payload" in final_output

    connection.last_used = time.monotonic() - 301
    await manager._reap_idle_once()
    assert authority_id not in manager._pool
    await manager.close()


class _EmptyRemoteReader:
    async def read(self, _size: int) -> bytes:
        return b""


class _FakeRemoteStdin:
    def __init__(self) -> None:
        self.closed = False

    def write(self, _data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def write_eof(self) -> None:
        self.closed = True


class _DelayedRemoteProcess:
    def __init__(self) -> None:
        self.exit_status = None
        self.exit_signal = None
        self.stdout = _EmptyRemoteReader()
        self.stderr = _EmptyRemoteReader()
        self.stdin = _FakeRemoteStdin()
        self.exited = asyncio.Event()
        self.terminate_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.exit_status = 143
        self.exited.set()

    def kill(self) -> None:
        self.exit_status = 137
        self.exited.set()

    async def wait(self, check: bool = False):
        await self.exited.wait()
        return SimpleNamespace(exit_status=self.exit_status)


class _DelayedRemoteClient:
    def __init__(self) -> None:
        self.create_entered = asyncio.Event()
        self.release_create = asyncio.Event()
        self.process = _DelayedRemoteProcess()
        self.create_calls = 0
        self.closed = False

    async def create_process(self, _command: str, **_kwargs):
        self.create_calls += 1
        self.create_entered.set()
        await self.release_create.wait()
        return self.process

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return


@pytest.mark.parametrize("cancel_mode", ["operation", "start_task"])
async def test_ssh_cancel_intent_applies_to_late_process_handle(cancel_mode):
    alias = "delayed"
    authority = SSHAuthority(
        alias=alias, hostname="127.0.0.1", port=22, username="z6", identity_files=(),
        host_key_alias=alias, known_hosts=(), config_digest="delayed-fixture",
    )
    client = _DelayedRemoteClient()
    connection = _Connection(
        client=client, last_used=time.monotonic(), os_name="windows",
        authority_id=authority.id, authority=authority,
    )
    manager = SSHWorkspaceManager()

    async def _connect(_host: str) -> _Connection:
        return connection

    manager._connect = _connect
    workspace = "ssh://delayed/C:/workspace"
    start_task = asyncio.create_task(manager.call_process({
        "action": "start", "executable": "python", "args": ["-c", "pass"],
        "cwd": workspace, "keep_stdin": True,
    }, workspace, run_id="owner"))
    await asyncio.wait_for(client.create_entered.wait(), timeout=1.0)
    record = next(iter(manager._processes.values()))
    cancel_task = None
    if cancel_mode == "operation":
        cancel_task = asyncio.create_task(manager.call_process({
            "action": "cancel", "execution_id": record.execution_id,
        }, workspace, run_id="owner"))
        await asyncio.sleep(0)
        assert record.cancel_requested is True
    else:
        start_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start_task

    client.release_create.set()
    if cancel_task is not None:
        await asyncio.wait_for(cancel_task, timeout=2.0)
        await asyncio.wait_for(start_task, timeout=2.0)
    for _ in range(100):
        if record.state == "cancelled":
            break
        await asyncio.sleep(0.01)
    assert record.state == "cancelled"
    assert client.process.terminate_calls == 1
    assert connection.active_leases == 0
    await manager.close()


async def test_ssh_active_process_lease_prevents_stale_pool_close(monkeypatch):
    alias = "leased"
    authority = SSHAuthority(
        alias=alias, hostname="127.0.0.1", port=22, username="z6", identity_files=(),
        host_key_alias=alias, known_hosts=(), config_digest="lease-fixture",
    )
    client = _DelayedRemoteClient()
    connection = _Connection(
        client=client, last_used=time.monotonic() - 301,
        authority_id=authority.id, authority=authority, active_leases=1,
    )
    manager = SSHWorkspaceManager()
    manager._pool[authority.id] = connection

    async def _resolve(_alias: str):
        return authority, object()

    monkeypatch.setattr(manager, "_resolve_authority_options", _resolve)
    selected = await manager._connect(alias)
    assert selected is connection
    assert client.closed is False
    assert authority.id in manager._pool
    await manager.close()


async def test_exec_manager_keeps_remote_unknown_as_terminal_without_restart(tmp_path):
    starts = 0

    async def dispatch(_name: str, arguments: dict[str, object]):
        nonlocal starts
        action = arguments.get("action")
        if action == "start":
            starts += 1
            return {"data": {"execution_id": "remote-unknown", "state": "running", "shell": "SSH"},
                    "is_error": False}
        if action == "status":
            return {"data": {"execution_id": "remote-unknown", "state": "unknown", "exit_code": None},
                    "is_error": True, "outcome": "unknown"}
        if action == "read":
            return {"data": {"text": "", "next_offset": int(arguments.get("offset", 0)),
                              "complete": True}, "is_error": False}
        raise AssertionError(f"unexpected remote action: {action}")

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner", local_runtime=None)
    result = await manager.execute("local_process", {
        "action": "start", "executable": "python", "args": ["-c", "pass"],
        "cwd": "ssh://leased/C:/workspace", "yield_time_ms": 250,
    })
    assert result["data"]["outcome"] == "unknown"
    assert result["outcome"] == "unknown"
    assert starts == 1
    await manager.shutdown()


class _SSHDispatchConfig(dict):
    def __init__(self, root):
        super().__init__({"delegation.max_spawn_depth": 4})
        self.db_path = root / "atlas.db"
        self.local_execution_permission_mode = "full_access"
        self.trajectory_reviewer_enabled = False
        self.trajectory_reviewer_backend = ""
        self.trajectory_reviewer_model = ""


class _LocalExecutionMustNotRun:
    async def call_tool(self, *_args, **_kwargs):
        raise AssertionError("SSH local_process fell through to the local runtime")


def _ssh_dispatch_agent():
    models = SimpleNamespace(current_model="test-model", current_litellm_model="test-model")
    agent = AgentOrchestrator(
        models, MagicMock(), mcp_client=MagicMock(),
        local_execution=_LocalExecutionMustNotRun(),
        trajectory_reviewer=SimpleNamespace(reviewer=None),
    )
    agent._model_facing_tools = lambda: []
    return agent


@pytest.mark.asyncio
async def test_kernel_tool_node_exec_manager_dispatches_ssh_process_without_local_fallback(
    ssh_world, tmp_path, monkeypatch,
):
    config = _SSHDispatchConfig(tmp_path)
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    kernel = AtlasKernel(data_dir=tmp_path, config={})
    agent = _ssh_dispatch_agent()
    runtime = AgentRunContext(
        workspace=ssh_world.workspace, run_id="kernel-ssh-run", conversation_id="kernel-ssh-run",
    )
    remote = _wired_manager(ssh_world)

    async def ssh_tool(name, arguments, owner_run_id=None):
        assert name == "local_process"
        return await remote.call_process(arguments, runtime.workspace, run_id=owner_run_id)

    runtime.ssh_tool_callback = ssh_tool

    async def dispatch(name, arguments):
        return await kernel._dispatch(
            agent, runtime, None, name, arguments, asyncio.Queue(),
            exec_manager=None, nested=True,
        )

    exec_manager = ExecManager(dispatch, output_dir=tmp_path / "tool-output",
                               run_id=runtime.run_id, local_runtime=None)
    try:
        result = await kernel._dispatch(
            agent, runtime, "kernel-ssh-tool-call", "local_process",
            {"action": "start", "executable": "python", "args": [
                "-c", "print('SSH_KERNEL_REMOTE_ONLY', flush=True)",
            ], "cwd": runtime.workspace, "detached": False,
                "keep_stdin": False, "yield_time_ms": 250}, asyncio.Queue(),
            exec_manager=exec_manager, nested=False,
        )
        execution_id = result["data"]["execution_id"]
        latest = result
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            latest = await exec_manager.poll(execution_id)
            handle = exec_manager.handles[execution_id]
            if handle.outcome != "running":
                break
            await asyncio.sleep(0.05)
        assert "SSH_KERNEL_REMOTE_ONLY" in str(latest), latest
        assert exec_manager.handles[execution_id].offsets["stdout"] >= len(
            "SSH_KERNEL_REMOTE_ONLY".encode("utf-8")
        )
        assert exec_manager.handles[execution_id].outcome == "completed", {
            "result": latest,
            "ssh_state": remote._processes[execution_id].state,
            "ssh_wait_done": bool(remote._processes[execution_id].wait_task
                                   and remote._processes[execution_id].wait_task.done()),
            "remote_child": dict(_LAST_LOOPBACK_CHILD),
        }
        assert exec_manager.handles[execution_id].exit_code == 0, latest
        assert remote._processes
        assert all(record.connection is not None for record in remote._processes.values())
    finally:
        await exec_manager.shutdown()
        await remote.close()


@pytest.mark.asyncio
async def test_ssh_bwrap_rejects_windows_loopback_without_starting_user_process(ssh_world):
    remote = _wired_manager(ssh_world)
    authority = next(iter(remote._pool.values())).authority
    async def resolve_authority(_host):
        assert authority is not None
        return authority
    remote.resolve_authority = resolve_authority
    before = len(_LOOPBACK_COMMANDS)
    try:
        with pytest.raises(RuntimeError, match="available only on Linux"):
            await remote.prepare_remote_sandbox(ssh_world.workspace)
        assert remote._processes == {}
        new_commands = _LOOPBACK_COMMANDS[before:]
        assert new_commands
        assert all("bwrap" not in str(item.get("command", "")) for item in new_commands)
    finally:
        await remote.close()


@pytest.mark.asyncio
async def test_kernel_child_ssh_process_owner_and_cancel_are_isolated(ssh_world, tmp_path, monkeypatch):
    config = _SSHDispatchConfig(tmp_path)
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    kernel = AtlasKernel(data_dir=tmp_path, config={})
    agent = _ssh_dispatch_agent()
    remote = _wired_manager(ssh_world)
    workspace = ssh_world.workspace
    parent = AgentRunContext(workspace=workspace, run_id="parent-run", conversation_id="parent-run")
    child = AgentRunContext(workspace=workspace, run_id="child-run", conversation_id="child-run")
    sibling = AgentRunContext(workspace=workspace, run_id="sibling-run", conversation_id="sibling-run")

    async def inherited_ssh_tool(name, arguments, owner_run_id=None):
        assert name == "local_process"
        # Child runs inherit this callback object, but their runtime run id is
        # passed separately and cannot be forged in the tool arguments.
        return await remote.call_process(arguments, workspace, run_id=owner_run_id)

    parent.ssh_tool_callback = inherited_ssh_tool
    child.ssh_tool_callback = parent.ssh_tool_callback
    sibling.ssh_tool_callback = parent.ssh_tool_callback

    async def dispatch(runtime, arguments):
        return await kernel._dispatch(
            agent, runtime, None, "local_process", arguments, asyncio.Queue(),
            exec_manager=None, nested=True,
        )

    async def start(runtime, run_id):
        arguments = {
            "action": "start", "executable": "python", "args": [
                "-c", "import time; print('SSH_OWNER_READY', flush=True); time.sleep(30)",
            ], "cwd": workspace, "detached": False, "keep_stdin": True,
            "yield_time_ms": 250,
        }
        if run_id == "child-run":
            arguments["_owner_run_id"] = "parent-run"  # Model-controlled spoof must be ignored.
        result = await dispatch(runtime, arguments)
        execution_id = result["data"]["execution_id"]
        record = remote._processes[execution_id]

        async def ready():
            while b"SSH_OWNER_READY" not in record.streams["stdout"]:
                await asyncio.sleep(0.02)

        await asyncio.wait_for(ready(), timeout=4.0)
        assert record.owner_run_id == run_id
        return execution_id, record

    try:
        parent_id, parent_record = await start(parent, "parent-run")
        sibling_id, sibling_record = await start(sibling, "sibling-run")
        child_id, child_record = await start(child, "child-run")

        assert len({parent_record.connection.authority_id, sibling_record.connection.authority_id,
                    child_record.connection.authority_id}) == 1

        denied = await dispatch(parent, {"action": "cancel", "execution_id": child_id})
        assert denied["is_error"] is True
        assert child_record.state == "running"

        await remote.cancel_run(child.run_id)
        assert child_record.state == "cancelled"
        assert parent_record.state == "running"
        assert sibling_record.state == "running"

        for runtime, execution_id in ((parent, parent_id), (sibling, sibling_id)):
            result = await dispatch(runtime, {"action": "cancel", "execution_id": execution_id})
            assert result["data"]["state"] == "cancelled"
    finally:
        await remote.close()


def _native_child_agent(tmp_path, monkeypatch, fake, remote, workspace):
    from atlas.memory import MemoryStore
    from atlas.tools.local_execution import LocalExecutionRuntime
    from tests.fakes.fake_llm_provider import write_atlas_home

    class FixtureConfig(dict):
        db_path = tmp_path / "config.db"
        raw = {}

    data_root = tmp_path / "atlas-data"
    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "tools.servers": {}, "tools.auto_start": [], "agent.verify_before_stop": True,
    }))
    monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(data_root))
    home = data_root / "engine"
    write_atlas_home(home, fake.base_url)
    monkeypatch.setenv("HERMES_HOME", str(home))
    model_rows = [{"id": "child-model", "litellm_model": "openai/child-model",
                   "max_output_tokens": 256}]
    def find_model(model_id):
        return next((item for item in model_rows if item["id"] == model_id), None)
    models = SimpleNamespace(
        current_model="child-model", current_litellm_model="openai/child-model",
        gateway_base_url=fake.base_url, gateway_api_key="sk-fake-e2e",
        list_models=lambda: model_rows,
        _find_model=find_model,
        provider_config=lambda _provider_id: {},
        resolve_api_key=lambda _provider_id: None,
        credential_pool=lambda _provider_id: None,
        get_api_mode_override=lambda _provider_id: None,
        output_tokens_for_model=lambda _model, _fallback, configured=None: configured or 256,
    )
    memory = MemoryStore(db_path=tmp_path / "memory.sqlite3")
    local = LocalExecutionRuntime()
    agent = AgentOrchestrator(
        models, memory, local_execution=local,
        agent_backend_host=SimpleNamespace(backends={}),
    )

    async def ssh_tool(name, arguments, owner_run_id=None):
        assert name == "local_process"
        return await remote.call_process(arguments, workspace, run_id=owner_run_id)

    return agent, memory, local, ssh_tool, home


def _long_process_start(workspace: str, marker: str) -> dict[str, object]:
    return {
        "action": "start", "executable": "python", "args": [
            "-c", f"import time; print('{marker}', flush=True); time.sleep(30)",
        ], "cwd": workspace, "detached": False, "keep_stdin": True,
        "yield_time_ms": 250,
    }


async def _start_owner_process(remote, workspace: str, owner: str, marker: str):
    result = await remote.call_process(_long_process_start(workspace, marker), workspace, run_id=owner)
    record = remote._processes[result["data"]["execution_id"]]

    async def ready():
        while marker.encode() not in record.streams["stdout"]:
            await asyncio.sleep(0.02)

    await asyncio.wait_for(ready(), timeout=4.0)
    return record


@pytest.mark.asyncio
async def test_real_atlas_child_finish_runs_child_process_cleanup_in_run_finally(
    ssh_world, tmp_path, monkeypatch,
):
    from atlas.memory import MemoryStore
    from atlas.tools.local_execution import LocalExecutionRuntime
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall

    remote = _wired_manager(ssh_world)
    monkeypatch.setattr("atlas.ssh.ssh_workspaces", remote)
    workspace = ssh_world.workspace
    parent_process = await _start_owner_process(remote, workspace, "parent-run", "PARENT_STAYS")
    sibling_process = await _start_owner_process(remote, workspace, "sibling-run", "SIBLING_STAYS")
    start_args = _long_process_start(workspace, "CHILD_FINISH_CLEANUP")

    with FakeLLMServer([
        ToolCall("local_process", start_args),
        Text("child task finished"),
    ]) as fake:
        agent, memory, local, ssh_tool, _home = _native_child_agent(
            tmp_path, monkeypatch, fake, remote, workspace,
        )
        await memory.init()
        try:
            result = await agent._delegation.delegate_task(
                "start the foreground fixture and finish", cwd=workspace,
                executor="atlas", _subtask_id="child-finish-run",
                atlas_options={
                    "model": "child-model", "permission_mode": "full_access",
                    "tool_allow": ["local_process"], "workspace_trusted": True,
                    "ssh_tool_callback": ssh_tool,
                },
            )
            assert result["status"] == "completed"
            child_records = [record for record in remote._processes.values()
                             if record.owner_run_id == "child-finish-run"]
            assert len(child_records) == 1
            child_process = child_records[0]
            assert child_process.state == "cancelled"
            assert child_process.wait_task and child_process.wait_task.done()
            assert child_process.lease_released is True
            assert parent_process.state == "running"
            assert sibling_process.state == "running"
        finally:
            await remote.cancel_run("parent-run")
            await remote.cancel_run("sibling-run")
            await remote.close()
            await local.shutdown()
            await memory.close()


@pytest.mark.asyncio
async def test_real_atlas_child_task_cancellation_runs_child_process_cleanup_in_run_finally(
    ssh_world, tmp_path, monkeypatch,
):
    from atlas.tools.local_execution import LocalExecutionRuntime
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall

    remote = _wired_manager(ssh_world)
    monkeypatch.setattr("atlas.ssh.ssh_workspaces", remote)
    workspace = ssh_world.workspace
    parent_process = await _start_owner_process(remote, workspace, "parent-run", "PARENT_CANCEL_STAYS")
    sibling_process = await _start_owner_process(remote, workspace, "sibling-run", "SIBLING_CANCEL_STAYS")
    second_request = threading.Event()
    release_response = threading.Event()
    calls = 0

    def responder(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ToolCall("local_process", _long_process_start(workspace, "CHILD_CANCEL_CLEANUP"))
        second_request.set()
        release_response.wait(8.0)
        return Text("late response after cancellation")

    with FakeLLMServer(responder) as fake:
        agent, memory, local, ssh_tool, _home = _native_child_agent(
            tmp_path, monkeypatch, fake, remote, workspace,
        )
        await memory.init()
        task = asyncio.create_task(agent._delegation.delegate_task(
            "start a foreground process then wait", cwd=workspace,
            executor="atlas", _subtask_id="child-cancel-run",
            atlas_options={
                "model": "child-model", "permission_mode": "full_access",
                "tool_allow": ["local_process"], "workspace_trusted": True,
                "ssh_tool_callback": ssh_tool,
            },
        ))
        try:
            assert await asyncio.to_thread(second_request.wait, 5.0)
            child_records = [record for record in remote._processes.values()
                             if record.owner_run_id == "child-cancel-run"]
            assert len(child_records) == 1
            child_process = child_records[0]
            assert child_process.state == "running"

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5.0)

            assert child_process.state == "cancelled"
            assert child_process.wait_task and child_process.wait_task.done()
            assert child_process.lease_released is True
            assert parent_process.state == "running"
            assert sibling_process.state == "running"
        finally:
            release_response.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await remote.cancel_run("parent-run")
            await remote.cancel_run("sibling-run")
            await remote.close()
            await local.shutdown()
            await memory.close()


@pytest.mark.asyncio
async def test_real_atlas_child_cancel_event_waits_for_run_finally_process_cleanup(
    ssh_world, tmp_path, monkeypatch,
):
    from atlas.tools.local_execution import LocalExecutionRuntime
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall

    remote = _wired_manager(ssh_world)
    monkeypatch.setattr("atlas.ssh.ssh_workspaces", remote)
    workspace = ssh_world.workspace
    parent_process = await _start_owner_process(remote, workspace, "parent-run", "PARENT_GATE_STAYS")
    sibling_process = await _start_owner_process(remote, workspace, "sibling-run", "SIBLING_GATE_STAYS")
    child_id = "child-cancel-event-run"
    second_request = threading.Event()
    release_response = threading.Event()
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_calls: list[str] = []
    original_cancel_run = remote.cancel_run

    async def gated_cancel_run(run_id: str):
        if run_id == child_id:
            cleanup_calls.append(run_id)
            cleanup_entered.set()
            await release_cleanup.wait()
        return await original_cancel_run(run_id)

    monkeypatch.setattr(remote, "cancel_run", gated_cancel_run)
    calls = 0

    def responder(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ToolCall("local_process", _long_process_start(workspace, "CHILD_CANCEL_EVENT_GATE"))
        second_request.set()
        release_response.wait(8.0)
        return Text("late response after cancel_event")

    with FakeLLMServer(responder) as fake:
        agent, memory, local, ssh_tool, _home = _native_child_agent(
            tmp_path, monkeypatch, fake, remote, workspace,
        )
        await memory.init()
        task = asyncio.create_task(agent._delegation.delegate_task(
            "start a foreground process then cancel via the child event", cwd=workspace,
            executor="atlas", _subtask_id=child_id,
            atlas_options={
                "model": "child-model", "permission_mode": "full_access",
                "tool_allow": ["local_process"], "workspace_trusted": True,
                "ssh_tool_callback": ssh_tool,
            },
        ))
        try:
            assert await asyncio.to_thread(second_request.wait, 5.0)
            child_records = [record for record in remote._processes.values()
                             if record.owner_run_id == child_id]
            assert len(child_records) == 1
            child_process = child_records[0]
            assert child_process.state == "running"

            assert agent._delegation.cancel_subtask(child_id) is True
            await asyncio.wait_for(cleanup_entered.wait(), timeout=5.0)
            assert cleanup_calls == [child_id]
            assert not task.done()
            assert child_process.state == "running"
            assert parent_process.state == "running"
            assert sibling_process.state == "running"

            release_cleanup.set()
            result = await asyncio.wait_for(task, timeout=5.0)
            assert result["status"] == "cancelled"
            assert child_process.state == "cancelled"
            assert child_process.wait_task and child_process.wait_task.done()
            assert child_process.lease_released is True
            assert parent_process.state == "running"
            assert sibling_process.state == "running"
        finally:
            release_cleanup.set()
            release_response.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await remote.cancel_run("parent-run")
            await remote.cancel_run("sibling-run")
            await remote.close()
            await local.shutdown()
            await memory.close()


@pytest.mark.asyncio
async def test_kernel_exec_manager_ssh_start_disconnect_is_unknown_without_retry(
    tmp_path, monkeypatch,
):
    config = _SSHDispatchConfig(tmp_path)
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    kernel = AtlasKernel(data_dir=tmp_path, config={})
    agent = _ssh_dispatch_agent()
    workspace = "ssh://leased/C:/remote-work"
    runtime = AgentRunContext(
        workspace=workspace, run_id="kernel-ssh-disconnect", conversation_id="kernel-ssh-disconnect",
    )
    authority = SSHAuthority(
        alias="leased", hostname="127.0.0.1", port=22, username="z6", identity_files=(),
        host_key_alias="leased", known_hosts=(), config_digest="disconnect-fixture",
    )

    class DroppedTransport:
        def __init__(self):
            self.create_calls = 0
            self.closed = False

        async def create_process(self, *_args, **_kwargs):
            self.create_calls += 1
            raise ConnectionResetError("fixture transport dropped after request")

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

    client = DroppedTransport()
    connection = _Connection(
        client=client, last_used=time.monotonic(), authority_id=authority.id, authority=authority,
    )
    remote = SSHWorkspaceManager()
    remote._pool[authority.id] = connection

    async def connect(_host):
        return connection

    async def process_command(_host, _cwd, _arguments):
        return "python -c side_effect()"

    remote._connect = connect
    remote._process_command = process_command

    async def ssh_tool(name, arguments, owner_run_id=None):
        assert name == "local_process"
        return await remote.call_process(arguments, runtime.workspace, run_id=owner_run_id)

    runtime.ssh_tool_callback = ssh_tool

    async def dispatch(name, arguments):
        return await kernel._dispatch(
            agent, runtime, None, name, arguments, asyncio.Queue(),
            exec_manager=None, nested=True,
        )

    exec_manager = ExecManager(dispatch, output_dir=tmp_path / "tool-output",
                               run_id=runtime.run_id, local_runtime=None)
    try:
        result = await kernel._dispatch(
            agent, runtime, "kernel-ssh-disconnect-call", "local_process",
            {"action": "start", "executable": "python", "args": ["-c", "side_effect()"],
             "cwd": workspace, "yield_time_ms": 250}, asyncio.Queue(),
            exec_manager=exec_manager, nested=False,
        )
        assert client.create_calls == 1
        assert "unknown" in str(result).lower()
        assert remote._processes
        assert next(iter(remote._processes.values())).state == "unknown"
    finally:
        await exec_manager.shutdown()
        await remote.close()
    assert client.closed is True


async def test_ssh_exec_channel_and_os_probe(ssh_world):
    mgr = _wired_manager(ssh_world)
    host, root = mgr.parse_workspace(ssh_world.workspace)
    assert root.startswith("/") and root[2] == ":"

    result = await mgr.run_result(host, "echo %OS%")
    assert result["exit_code"] == 0
    assert "windows_nt" in result["stdout"].lower()

    probe = await mgr.test(host)
    assert probe["ok"] is True
    assert probe["os"] == "windows"


async def test_real_connect_uses_configured_authority_and_known_hosts(ssh_world, tmp_path):
    alias = "loopback-atlas"
    port = ssh_world._acceptor.sockets[0].getsockname()[1]
    user_key = asyncssh.generate_private_key("ssh-ed25519")
    identity_file = tmp_path / "client-key"
    known_hosts = tmp_path / "known-hosts"
    config_file = tmp_path / "ssh-config"
    included_config = tmp_path / "included-hosts"
    identity_file.write_bytes(user_key.export_private_key("openssh"))
    host_key = ssh_world._key.export_public_key("openssh").decode("ascii").split()
    known_hosts.write_text(f"[{alias}]:{port} {host_key[0]} {host_key[1]}\n", encoding="utf-8")
    included_config.write_text(
        f"Host {alias}\n"
        " HostName 127.0.0.1\n"
        " User z6\n"
        f" IdentityFile {identity_file.as_posix()}\n"
        " IdentitiesOnly yes\n"
        f" UserKnownHostsFile {known_hosts.as_posix()}\n"
        f" HostKeyAlias {alias}\n",
        encoding="utf-8",
    )
    # The exact alias is declared only in an Include file. Match final supplies
    # the port which is absent from the initial Host pass (whose default is 22).
    config_file.write_text(
        f"Include {included_config.as_posix()}\n"
        "Match final host 127.0.0.1\n"
        f" Port {port}\n",
        encoding="utf-8",
    )
    manager = SSHWorkspaceManager(str(config_file))
    first_authority = await manager.resolve_authority(alias.upper())
    assert first_authority.alias == alias
    assert first_authority.hostname == "127.0.0.1"
    assert first_authority.port == port
    assert first_authority.username == "z6"
    assert first_authority.identity_files == (str(identity_file.resolve()).casefold(),)
    assert first_authority.known_hosts == (str(known_hosts.resolve()).casefold(),)
    with pytest.raises(ValueError, match="exact configured alias"):
        await manager.resolve_authority("not-configured")

    connection = await manager._connect(alias)
    result = await connection.client.run("echo authority-connected", check=False)
    assert result.exit_status == 0
    assert "authority-connected" in result.stdout
    assert connection.authority_id == first_authority.id
    assert connection.authority == first_authority
    assert list(manager._pool) == [first_authority.id]

    # Trust file contents and effective identity directives are part of the
    # authority version, even when the top-level Include line is unchanged.
    known_hosts.write_text(
        f"[{alias}]:{port} {host_key[0]} {host_key[1]} rotated\n", encoding="utf-8",
    )
    trust_changed = await manager.resolve_authority(alias)
    assert trust_changed.id != first_authority.id
    trust_connection = await manager._connect(alias)
    assert trust_connection is not connection
    assert trust_connection.authority_id == trust_changed.id
    known_hosts.write_text(f"[{alias}]:{port} {host_key[0]} {host_key[1]}\n", encoding="utf-8")
    included_config.write_text(
        included_config.read_text(encoding="utf-8").replace("IdentitiesOnly yes", "IdentitiesOnly no"),
        encoding="utf-8",
    )
    policy_changed = await manager.resolve_authority(alias)
    assert policy_changed.id != trust_changed.id
    policy_connection = await manager._connect(alias)
    assert policy_connection is not trust_connection
    assert policy_connection.authority_id == policy_changed.id

    # Rotating the configured identity changes the pool identity, so a cached
    # connection under the old credential domain cannot satisfy the new one.
    second_key = asyncssh.generate_private_key("ssh-ed25519")
    second_identity = tmp_path / "client-key-2"
    second_identity.write_bytes(second_key.export_private_key("openssh"))
    included_config.write_text(
        included_config.read_text(encoding="utf-8").replace(identity_file.as_posix(), second_identity.as_posix()),
        encoding="utf-8",
    )
    second_authority = await manager.resolve_authority(alias)
    assert second_authority.id != policy_changed.id
    second_connection = await manager._connect(alias)
    assert second_connection.authority_id == second_authority.id
    assert second_connection is not policy_connection
    assert len(manager._pool) == 4
    await manager.close()


@pytest.mark.asyncio
async def test_ssh_terminal_uses_real_authority_pty_input_resize_exit_and_disconnect(ssh_world, tmp_path):
    alias = "terminal-atlas"
    port = ssh_world._acceptor.sockets[0].getsockname()[1]
    user_key = asyncssh.generate_private_key("ssh-ed25519")
    identity_file = tmp_path / "terminal-client-key"
    known_hosts = tmp_path / "terminal-known-hosts"
    config_file = tmp_path / "terminal-ssh-config"
    identity_file.write_bytes(user_key.export_private_key("openssh"))
    host_key = ssh_world._key.export_public_key("openssh").decode("ascii").split()
    known_hosts.write_text(f"[{alias}]:{port} {host_key[0]} {host_key[1]}\n", encoding="utf-8")
    config_file.write_text(
        f"Host {alias}\n"
        " HostName 127.0.0.1\n"
        f" Port {port}\n"
        " User z6\n"
        f" IdentityFile {identity_file.as_posix()}\n"
        " IdentitiesOnly yes\n"
        f" UserKnownHostsFile {known_hosts.as_posix()}\n"
        f" HostKeyAlias {alias}\n",
        encoding="utf-8",
    )
    manager = SSHWorkspaceManager(str(config_file))
    workspace = f"ssh://{alias}/{ssh_world.root.as_posix()}"
    try:
        authority = await manager.resolve_authority(alias)
        async with _LOOPBACK_COMMANDS_CHANGED:
            first_terminal_index = len(_LOOPBACK_COMMANDS)
        session = await manager.open_terminal(workspace, rows=24, cols=80)
        async with _LOOPBACK_COMMANDS_CHANGED:
            await asyncio.wait_for(
                _LOOPBACK_COMMANDS_CHANGED.wait_for(
                    lambda: any(
                        item["kind"] == "terminal"
                        for item in _LOOPBACK_COMMANDS[first_terminal_index:]
                    )
                ),
                timeout=3.0,
            )
            terminal_record = next(
                item for item in _LOOPBACK_COMMANDS[first_terminal_index:]
                if item["kind"] == "terminal"
            )
        connection = manager._pool[authority.id]
        assert connection.active_leases == 1
        assert terminal_record["term_type"] == "xterm-256color"
        assert terminal_record["term_size"][:2] == (80, 24)

        resize_event = asyncio.Event()
        def _resized(width, height, pixwidth, pixheight):
            terminal_record["resized"] = (width, height, pixwidth, pixheight)
            resize_event.set()
        terminal_record["server_process"].terminal_size_changed = _resized
        await session.resize(41, 117)
        await asyncio.wait_for(resize_event.wait(), timeout=2.0)
        assert terminal_record["resized"] == (117, 41, 0, 0)

        await session.write(b"Write-Output 'SSH_TERMINAL_INPUT_OK'\r")
        async def _read_until(marker: bytes) -> bytes:
            result = bytearray()
            while marker not in result:
                chunk = await session.read(4096)
                if not chunk:
                    break
                result.extend(chunk)
            return bytes(result)
        output = await asyncio.wait_for(_read_until(b"SSH_TERMINAL_INPUT_OK"), timeout=6.0)
        assert b"SSH_TERMINAL_INPUT_OK" in output

        await session.write(b"exit\r")
        assert await asyncio.wait_for(session.wait_closed(), timeout=6.0) == 0
        assert connection.active_leases == 0
        assert session not in manager._terminal_sessions

        async with _LOOPBACK_COMMANDS_CHANGED:
            second_terminal_index = len(_LOOPBACK_COMMANDS)
        disconnected = await manager.open_terminal(workspace, rows=25, cols=90)
        async with _LOOPBACK_COMMANDS_CHANGED:
            await asyncio.wait_for(
                _LOOPBACK_COMMANDS_CHANGED.wait_for(
                    lambda: any(
                        item["kind"] == "terminal"
                        for item in _LOOPBACK_COMMANDS[second_terminal_index:]
                    )
                ),
                timeout=3.0,
            )
        connection = disconnected.connection
        assert connection.active_leases == 1
        assert await asyncio.wait_for(disconnected.close(), timeout=5.0) is True
        assert connection.active_leases == 0
        assert disconnected not in manager._terminal_sessions
        assert disconnected.process.exit_status is not None
    finally:
        await manager.close()


@pytest.mark.parametrize("uri", [
    "ssh://alias:2222/workspace", "ssh://user@alias/workspace", "ssh://alias/workspace?port=22",
    "ssh://alias/workspace#fragment",
])
def test_ssh_workspace_identity_rejects_uri_credentials_and_overrides(uri: str) -> None:
    with pytest.raises(ValueError):
        SSHWorkspaceManager.parse_workspace(uri)


async def test_ssh_file_round_trip_over_sftp(ssh_world):
    mgr = _wired_manager(ssh_world)
    target = ssh_world.root / "notes" / "z6.txt"

    written = await mgr.call_tool("local_file", {
        "action": "write", "path": str(target), "content": "z6-ssh-evidence",
    }, ssh_world.workspace)
    assert written["is_error"] is False
    assert target.read_text(encoding="utf-8") == "z6-ssh-evidence"

    read = await mgr.call_tool("local_file", {
        "action": "read", "path": str(target),
    }, ssh_world.workspace)
    assert read["data"]["content"] == "z6-ssh-evidence"
    assert read["data"]["size"] == len("z6-ssh-evidence")

    listing = await mgr.call_tool("local_file", {
        "action": "list", "path": ssh_world.root,
    }, ssh_world.workspace)
    names = {entry["name"] for entry in listing["data"]["entries"]}
    assert "notes" in names


async def test_ssh_read_file_is_confined_to_canonical_workspace(ssh_world):
    manager = _wired_manager(ssh_world)
    authority = next(iter(manager._pool.values())).authority

    async def resolve_fixture_authority(_alias):
        return authority

    manager.resolve_authority = resolve_fixture_authority
    inside = ssh_world.root / "inside.txt"
    outside = ssh_world.root.parent / "outside.txt"
    inside.write_text("SSH_READ_INSIDE_FIXTURE\nsecond fixture line\n", encoding="utf-8")
    outside.write_text("SSH_READ_OUTSIDE_SECRET_FIXTURE", encoding="utf-8")

    result = await manager.read_workspace_file(ssh_world.workspace, "inside.txt")
    assert result == "SSH_READ_INSIDE_FIXTURE\r\nsecond fixture line\r\n"
    assert await manager.read_workspace_file(
        ssh_world.workspace, "inside.txt", offset=1, limit=1,
    ) == "second fixture line\r\n"

    with pytest.raises(PermissionError, match="outside the active SSH workspace"):
        await manager.read_workspace_file(ssh_world.workspace, str(outside))


async def test_ssh_read_file_rejects_authority_change_before_sftp(ssh_world, monkeypatch):
    manager = _wired_manager(ssh_world)
    authority = next(iter(manager._pool.values())).authority

    async def changed_authority(_alias):
        return SSHAuthority(
            alias=authority.alias, hostname="192.0.2.99", port=authority.port,
            username=authority.username, identity_files=authority.identity_files,
            host_key_alias=authority.host_key_alias, known_hosts=authority.known_hosts,
            config_digest="changed-authority",
        )

    monkeypatch.setattr(manager, "resolve_authority", changed_authority)
    with pytest.raises(PermissionError, match="authority"):
        await manager.read_workspace_file(ssh_world.workspace, "inside.txt")


async def test_ssh_read_file_rejects_canonical_symlink_escape(ssh_world, monkeypatch):
    manager = SSHWorkspaceManager()
    authority = SSHAuthority(
        alias="z6looper", hostname="127.0.0.1", port=22, username="z6",
        identity_files=(), host_key_alias="z6looper", known_hosts=(), config_digest="canonical-test",
    )

    canonical_root = manager.parse_workspace(ssh_world.workspace)[1]

    class _SFTP:
        async def realpath(self, path, *, check):
            assert check == asyncssh.FXRP_STAT_ALWAYS
            if path == canonical_root:
                return canonical_root
            return posixpath.normpath(posixpath.join(canonical_root, "..", "outside.txt"))

    class _SFTPContext:
        async def __aenter__(self):
            return _SFTP()

        async def __aexit__(self, *_args):
            return False

    class _Client:
        def start_sftp_client(self):
            return _SFTPContext()

    connection = _Connection(
        client=_Client(), last_used=time.monotonic(), authority_id=authority.id,
        authority=authority,
    )

    async def resolve_fixture_authority(_alias):
        return authority

    async def connect_fixture_authority(_alias, *, expected_authority_id=None):
        assert expected_authority_id == authority.id
        return connection

    monkeypatch.setattr(manager, "resolve_authority", resolve_fixture_authority)
    monkeypatch.setattr(manager, "_connect", connect_fixture_authority)
    with pytest.raises(PermissionError, match="outside the active SSH workspace"):
        await manager.read_workspace_file(ssh_world.workspace, "link-to-outside.txt")


async def test_ssh_remote_exec_runs_in_workspace_root(ssh_world):
    mgr = _wired_manager(ssh_world)
    marker = ssh_world.root / "cwd-marker.txt"
    marker.write_text("", encoding="utf-8")

    outcome = await mgr.call_tool("local_exec", {
        "executable": "powershell",
        "args": ["-NoProfile", "-NonInteractive", "-Command",
                 "Get-ChildItem -Name | Set-Content cwd-listing.txt"],
        "cwd": str(ssh_world.root),
    }, ssh_world.workspace)
    assert outcome["is_error"] is False
    assert (ssh_world.root / "cwd-listing.txt").exists()


async def test_ssh_remote_edit_replaces_one_match_on_disk(ssh_world):
    mgr = _wired_manager(ssh_world)
    authority = next(iter(mgr._pool.values())).authority

    async def resolve_fixture_authority(_alias):
        return authority

    mgr.resolve_authority = resolve_fixture_authority
    target = ssh_world.root / "editable.txt"
    target.write_text("before: z6-old\n", encoding="utf-8")

    await mgr.read_workspace_file(
        ssh_world.workspace, str(target), observation_owner_id="conversation-edit-1",
    )

    edited = await mgr.call_tool("local_edit", {
        "path": str(target), "old_string": "z6-old", "new_string": "z6-new",
    }, ssh_world.workspace, run_id="run-edit-1", observation_owner_id="conversation-edit-1")
    assert edited["is_error"] is False
    assert target.read_text(encoding="utf-8") == "before: z6-new\n"

    # An ambiguous old_string must fail closed without touching the file.
    target.write_text("dup dup\n", encoding="utf-8")
    with pytest.raises(ValueError):
        await mgr.call_tool("local_edit", {
            "path": str(target), "old_string": "dup", "new_string": "x",
        }, ssh_world.workspace, run_id="run-edit-1", observation_owner_id="conversation-edit-1")
    assert target.read_text(encoding="utf-8") == "dup dup\n"


async def test_ssh_remote_edit_requires_read_by_same_conversation(ssh_world):
    manager = _wired_manager(ssh_world)
    authority = next(iter(manager._pool.values())).authority

    async def resolve_fixture_authority(_alias):
        return authority

    manager.resolve_authority = resolve_fixture_authority
    target = ssh_world.root / "owner-edit.txt"
    target.write_text("original value\n", encoding="utf-8")
    arguments = {"path": str(target), "old_string": "original", "new_string": "changed"}

    with pytest.raises(ValueError, match="READ_REQUIRED"):
        await manager.call_tool(
            "local_edit", {**arguments, "observation_owner_id": "conversation-reader"},
            ssh_world.workspace, run_id="run-unread",
        )
    assert target.read_text(encoding="utf-8") == "original value\n"

    await manager.read_workspace_file(
        ssh_world.workspace, str(target), observation_owner_id="conversation-reader",
    )
    with pytest.raises(ValueError, match="READ_REQUIRED"):
        await manager.call_tool(
            "local_edit", arguments, ssh_world.workspace, run_id="run-other",
            observation_owner_id="conversation-other",
        )
    assert target.read_text(encoding="utf-8") == "original value\n"

    await manager.read_workspace_file(
        ssh_world.workspace, str(target), observation_owner_id="conversation-reader",
    )
    edited = await manager.call_tool(
        "local_edit", arguments, ssh_world.workspace, run_id="run-reader",
        observation_owner_id="conversation-reader",
    )
    assert edited["is_error"] is False
    assert target.read_text(encoding="utf-8") == "changed value\n"

    next_edit = await manager.call_tool(
        "local_edit", {"path": str(target), "old_string": "changed", "new_string": "finished"},
        ssh_world.workspace, run_id="run-reader-2", observation_owner_id="conversation-reader",
    )
    assert next_edit["is_error"] is False
    assert target.read_text(encoding="utf-8") == "finished value\n"


async def test_ssh_remote_edit_rejects_stale_observation_without_mutation(ssh_world):
    manager = _wired_manager(ssh_world)
    authority = next(iter(manager._pool.values())).authority

    async def resolve_fixture_authority(_alias):
        return authority

    manager.resolve_authority = resolve_fixture_authority
    target = ssh_world.root / "stale-edit.txt"
    target.write_text("observed version\n", encoding="utf-8")
    await manager.read_workspace_file(
        ssh_world.workspace, str(target), observation_owner_id="conversation-stale",
    )
    target.write_text("external version\n", encoding="utf-8")

    with pytest.raises(ValueError, match="STALE_FILE"):
        await manager.call_tool(
            "local_edit", {"path": str(target), "old_string": "external", "new_string": "overwritten"},
            ssh_world.workspace, run_id="run-stale", observation_owner_id="conversation-stale",
        )
    assert target.read_text(encoding="utf-8") == "external version\n"


async def test_ssh_remote_edit_rejects_authority_change_before_target_write(ssh_world, monkeypatch):
    manager = _wired_manager(ssh_world)
    original_authority = next(iter(manager._pool.values())).authority

    async def resolve_original(_alias):
        return original_authority

    manager.resolve_authority = resolve_original
    target = ssh_world.root / "authority-edit.txt"
    target.write_text("authority A content\n", encoding="utf-8")
    await manager.read_workspace_file(
        ssh_world.workspace, str(target), observation_owner_id="conversation-authority",
    )

    async def resolve_changed(_alias):
        return SSHAuthority(
            alias=original_authority.alias, hostname="192.0.2.77", port=original_authority.port,
            username=original_authority.username, identity_files=original_authority.identity_files,
            host_key_alias=original_authority.host_key_alias,
            known_hosts=original_authority.known_hosts, config_digest="changed-edit-authority",
        )

    monkeypatch.setattr(manager, "resolve_authority", resolve_changed)
    with pytest.raises(PermissionError, match="authority"):
        await manager.call_tool(
            "local_edit", {"path": str(target), "old_string": "A", "new_string": "B"},
            ssh_world.workspace, run_id="run-authority", observation_owner_id="conversation-authority",
        )
    assert target.read_text(encoding="utf-8") == "authority A content\n"
