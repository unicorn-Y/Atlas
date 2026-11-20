"""LSP tool integration for authority-scoped SSH workspaces."""
from __future__ import annotations

import asyncio
import json
import posixpath
import time
from urllib.parse import quote

import pytest
from types import SimpleNamespace

from atlas.engine.kernel.loop import AtlasKernel
from atlas.lsp.manager import LSPService
from atlas.lsp.protocol import encode_message
from atlas.lsp.servers import custom_servers
from atlas.ssh import SSHLspWorkspace
from atlas.tools.workspace_lsp import query_lsp

pytestmark = pytest.mark.unit


class _LspProcess:
    remote = True
    pid = None

    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode = None
        self.exited = asyncio.Event()
        self.stdin = _LspStdin(self)

    async def wait(self):
        await self.exited.wait()
        return self.returncode

    async def kill(self):
        self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.exited.set()


class _LspStdin:
    def __init__(self, process):
        self.process = process
        self.messages = []

    def is_closing(self):
        return False

    def write(self, data):
        header, body = data.split(b"\r\n\r\n", 1)
        length = int(header.split(b": ", 1)[1])
        message = json.loads(body[:length])
        self.messages.append(message)
        if "id" in message:
            result = {"capabilities": {"textDocumentSync": 1}} if message["method"] == "initialize" else {"contents": "remote hover"}
            self.process.stdout.feed_data(encode_message({"jsonrpc": "2.0", "id": message["id"], "result": result}))
        if message.get("method") in {"textDocument/didOpen", "textDocument/didChange"}:
            document = message["params"]["textDocument"]
            self.process.stdout.feed_data(encode_message({
                "jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                "params": {"uri": document["uri"], "version": document["version"],
                           "diagnostics": [{"range": {"start": {"line": 0, "character": 0},
                                                       "end": {"line": 0, "character": 1}},
                                           "severity": 2, "message": "remote fixture diagnostic"}]},
            }))
        if message.get("method") == "exit":
            self.process.returncode = 0
            self.process.stdout.feed_eof()
            self.process.stderr.feed_eof()
            self.process.exited.set()

    async def drain(self):
        await asyncio.sleep(0)


class _RemoteWorld:
    trusted = True
    root = "/srv/project"
    authority_id = "authority-42"
    host = "fixture-host"
    workspace = "ssh://fixture-host/srv/project"
    authority_key = "ssh://authority-42@fixture-host"

    def __init__(self):
        self.calls = []
        self.process = None
        self.uri_for_path = lambda path: "file://" + quote(path, safe="/:@")
        self.path_from_uri = lambda uri: uri.removeprefix("file://")
        self.normalize_path = posixpath.normpath

    def cache_key(self, root):
        return f"ssh://{self.authority_id}@{self.host}{root}"

    def workspace_file(self, raw_path):
        path = str(raw_path)
        if not path.startswith("/"):
            path = posixpath.join(self.root, path)
        path = posixpath.normpath(path)
        if posixpath.commonpath((self.root, path)) != self.root:
            raise PermissionError("outside workspace")
        return self.root, path

    async def resolve_root(self, server, file_path, workspace_root):
        self.calls.append(("root", server.server_id, file_path, workspace_root))
        assert server.root_markers == ("fixture.toml",)
        return "/srv/project/packages/app"

    def resolve_binary(self, server_id, override, candidates):
        self.calls.append(("binary", server_id, tuple(candidates)))
        return "/usr/bin/fixture-lsp"

    async def process_factory(self, command, cwd, env):
        self.calls.append(("spawn", tuple(command), cwd, env))
        self.process = _LspProcess()
        return self.process

    async def read_document(self, path):
        self.calls.append(("read", path))
        return "remote fixture source"


@pytest.mark.asyncio
async def test_workspace_lsp_query_uses_authority_scoped_remote_root_and_process(monkeypatch):
    remote = _RemoteWorld()
    extra = custom_servers({"fixture-lsp": {
        "extensions": [".fixture"], "command": ["fixture-lsp"],
        "root_markers": ["fixture.toml"],
    }})
    service = LSPService(enabled=True, idle_timeout=0, extra_servers=extra, exclude_roots=[])
    monkeypatch.setattr("atlas.lsp.get_service", lambda: service)
    try:
        result = await asyncio.to_thread(
            query_lsp, "ssh://fixture-host/srv/project", operation="hover",
            path="packages/app/src/main.fixture", line=0, character=0,
            remote_world=remote,
        )
        assert result == {"available": True, "result": {"contents": "remote hover"}, "path": "packages/app/src/main.fixture"}
        key = ("fixture-lsp", remote.cache_key("/srv/project/packages/app"))
        client = service._clients[key]
        initialize = next(m for m in remote.process.stdin.messages if m.get("method") == "initialize")
        assert initialize["params"]["processId"] is None
        assert initialize["params"]["rootUri"] == remote.uri_for_path("/srv/project/packages/app")
        opened = next(m for m in remote.process.stdin.messages if m.get("method") == "textDocument/didOpen")
        assert opened["params"]["textDocument"]["text"] == "remote fixture source"
        assert ("spawn", ("/usr/bin/fixture-lsp",), "/srv/project/packages/app", {}) in remote.calls
        assert client._proc is remote.process
    finally:
        service.shutdown()


@pytest.mark.asyncio
async def test_ssh_lsp_workspace_resolves_per_language_root_through_remote_markers():
    class Manager:
        def parse_workspace(self, uri):
            return "fixture-host", uri.removeprefix("ssh://fixture-host")

        def make_lsp_process_factory(self, *_args, **_kwargs):
            return lambda *_args: None

    manager = Manager()
    workspace = SSHLspWorkspace(
        manager, "ssh://fixture-host/srv/project", asyncio.get_running_loop(),
        "authority-42", True,
    )
    existing = {
        "/srv/project/.git", "/srv/project/packages/app/src/main.py",
        "/srv/project/packages/app/pyproject.toml", "/srv/project/pyproject.toml",
    }

    async def exists(path, *, directory=None):
        return path in existing

    workspace._exists = exists
    _, remote_path = await asyncio.to_thread(workspace.workspace_file, "packages/app/src/main.py")
    from atlas.lsp.servers import find_server_for_file
    server = find_server_for_file(remote_path)
    assert server is not None
    assert await workspace.resolve_root(server, remote_path, workspace.root) == "/srv/project/packages/app"
    assert workspace.cache_key("/srv/project/packages/app").startswith("ssh://authority-42@fixture-host/")


@pytest.mark.asyncio
async def test_ssh_lsp_remote_marker_io_runs_on_ssh_owner_loop_from_separate_lsp_loop():
    owner_loop = asyncio.get_running_loop()
    owner_calls = []
    existing = {
        "/srv/project/.git", "/srv/project/packages/app/src/main.py",
        "/srv/project/packages/app/pyproject.toml",
    }

    class Sftp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def stat(self, path):
            owner_calls.append(asyncio.get_running_loop())
            if path not in existing:
                raise FileNotFoundError(path)
            return SimpleNamespace(permissions=0o100000)

    class Client:
        def start_sftp_client(self):
            owner_calls.append(asyncio.get_running_loop())
            return Sftp()

    class Manager:
        def parse_workspace(self, uri):
            return "fixture-host", uri.removeprefix("ssh://fixture-host")

        def make_lsp_process_factory(self, *_args, **_kwargs):
            return lambda *_args: None

        async def _connect(self, _host, *, expected_authority_id=None):
            assert expected_authority_id == "authority-42"
            assert asyncio.get_running_loop() is owner_loop
            owner_calls.append(asyncio.get_running_loop())
            return SimpleNamespace(client=Client())

    workspace = SSHLspWorkspace(
        Manager(), "ssh://fixture-host/srv/project", owner_loop, "authority-42", True,
    )
    from atlas.lsp.servers import find_server_for_file
    server = find_server_for_file("/srv/project/packages/app/src/main.py")
    assert server is not None
    root = await asyncio.to_thread(
        lambda: asyncio.run(workspace.resolve_root(
            server, "/srv/project/packages/app/src/main.py", workspace.root,
        ))
    )
    assert root == "/srv/project/packages/app"
    assert owner_calls
    assert all(loop is owner_loop for loop in owner_calls)


@pytest.mark.asyncio
async def test_kernel_lsp_tool_and_read_file_diagnostics_forward_ssh_workspace(monkeypatch, tmp_path):
    kernel = AtlasKernel(data_dir=tmp_path, config={})
    runtime = SimpleNamespace(
        workspace="ssh://fixture-host/srv/project", workspace_trusted=True,
        tool_mode="native", run_id="lsp-ssh-run", conversation_id="lsp-ssh-run",
    )
    world = _RemoteWorld()
    made = []

    async def make_world(workspace, *, trusted):
        made.append((workspace, trusted))
        return world

    extra = custom_servers({"fixture-lsp": {
        "extensions": [".fixture"], "command": ["fixture-lsp"],
        "root_markers": ["fixture.toml"],
    }})
    service = LSPService(enabled=True, idle_timeout=0, extra_servers=extra,
                         exclude_roots=[], wait_timeout=1.0)
    monkeypatch.setattr("atlas.lsp.get_service", lambda: service)
    monkeypatch.setattr("atlas.ssh.ssh_workspaces.make_lsp_workspace", make_world)
    try:
        result = await kernel._dispatch(
            object(), runtime, "lsp-1", "lsp_hover",
            {"path": "packages/app/src/main.fixture", "line": 0, "character": 0},
            asyncio.Queue(), nested=True,
        )
        assert result["outcome"] == "completed"
        assert json.loads(result["content"])["result"] == {"contents": "remote hover"}
        assert made == [(runtime.workspace, True)]

        async def execute_tools(_state):
            return {"pending_events": [{
                "type": "tool_result", "id": "read-1", "is_error": False,
                "content": [{"type": "text", "text": "remote file contents"}], "data": {},
            }], "messages": []}

        reader_agent = SimpleNamespace(_execute_tools_node=execute_tools)
        read_result = await kernel._dispatch(
            reader_agent, runtime, "read-1", "read_file",
            {"path": "packages/app/src/main.fixture"}, asyncio.Queue(), nested=True,
        )
        assert "remote file contents" in read_result["content"]
        assert "remote fixture diagnostic" in read_result["content"]
        assert made == [(runtime.workspace, True), (runtime.workspace, True)]
    finally:
        service.shutdown()


@pytest.mark.asyncio
async def test_ssh_lsp_world_rejects_alias_authority_drift_for_fs_binary_and_spawn():
    from atlas.ssh import SSHAuthority, SSHWorkspaceManager

    authority_a = SSHAuthority(
        alias="fixture", hostname="192.0.2.10", port=22, username="atlas",
        identity_files=(), host_key_alias="fixture", known_hosts=(), config_digest="authority-a",
    )
    authority_b = SSHAuthority(
        alias="fixture", hostname="192.0.2.11", port=22, username="atlas",
        identity_files=(), host_key_alias="fixture", known_hosts=(), config_digest="authority-b",
    )
    manager = SSHWorkspaceManager()

    async def current_options(_alias):
        return authority_b, {}

    manager._resolve_authority_options = current_options
    world = SSHLspWorkspace(
        manager, "ssh://fixture/srv/project", asyncio.get_running_loop(), authority_a.id, True,
    )
    try:
        assert world.cache_key("/srv/project").startswith(f"ssh://{authority_a.id}@fixture/")
        with pytest.raises(PermissionError, match="authority changed"):
            await world._exists("/srv/project/.git")
        with pytest.raises(PermissionError, match="authority changed"):
            await world.read_document("/srv/project/main.py")
        with pytest.raises(PermissionError, match="authority changed"):
            await asyncio.to_thread(world.resolve_binary, "fixture-lsp", None, ["fixture-lsp"])
        with pytest.raises(PermissionError, match="authority changed"):
            await world.process_factory(["fixture-lsp"], "/srv/project", {})
        assert not manager._pool
    finally:
        if manager._reaper is not None:
            manager._reaper.cancel()
            await asyncio.gather(manager._reaper, return_exceptions=True)


@pytest.mark.asyncio
async def test_remote_release_is_authority_scoped_and_reaper_skips_local_path_probe(monkeypatch):
    from atlas.lsp.manager import LSPService
    from atlas.ssh import SSHAuthority, ssh_workspaces
    from urllib.parse import quote

    authority_a = SSHAuthority(
        alias="fixture", hostname="192.0.2.10", port=22, username="atlas",
        identity_files=(), host_key_alias="fixture", known_hosts=(), config_digest="authority-a",
    )
    authority_b = SSHAuthority(
        alias="fixture", hostname="192.0.2.11", port=22, username="atlas",
        identity_files=(), host_key_alias="fixture", known_hosts=(), config_digest="authority-b",
    )

    async def resolve(_alias):
        return authority_b

    monkeypatch.setattr(ssh_workspaces, "resolve_authority", resolve)
    service = LSPService(enabled=False, idle_timeout=60, exclude_roots=[])

    class Client:
        server_id = "fixture-lsp"
        workspace_root = "/srv/project/packages/app"
        workspace_folders = [workspace_root]

        def __init__(self, authority):
            self.remote_workspace_uri = "ssh://fixture/srv/project"
            self.remote_authority_key = f"ssh://{quote(authority.id, safe='')}@fixture"
            self.closed = 0

        async def shutdown(self):
            self.closed += 1

    key_a = ("fixture-lsp", f"ssh://{quote(authority_a.id, safe='')}@fixture/srv/project/packages/app")
    key_b = ("fixture-lsp", f"ssh://{quote(authority_b.id, safe='')}@fixture/srv/project/packages/app")
    client_a, client_b = Client(authority_a), Client(authority_b)
    service._clients.update({key_a: client_a, key_b: client_b})
    service._last_used.update({key_a: time.time(), key_b: time.time()})
    service._broken.update({key_a: float("inf"), key_b: float("inf")})
    service._missing.update({key_a, key_b})
    service._missing_checked_at.update({key_a: 1.0, key_b: 1.0})
    done_a = asyncio.get_running_loop().create_future()
    done_a.set_result(client_a)
    done_b = asyncio.get_running_loop().create_future()
    done_b.set_result(client_b)
    service._spawning.update({key_a: done_a, key_b: done_b})

    monkeypatch.setattr("atlas.lsp.manager.os.path.isdir", lambda _path: False)
    # An active remote root must not be tested against this machine's filesystem.
    await service._reap_idle_once()
    assert service._clients == {key_a: client_a, key_b: client_b}
    assert client_a.closed == client_b.closed == 0

    assert await service._release_remote_async("ssh://fixture/srv/project") == 1
    assert service._clients == {key_a: client_a}
    assert service._last_used == {key_a: service._last_used[key_a]}
    assert key_a in service._broken and key_b not in service._broken
    assert key_a in service._missing and key_b not in service._missing
    assert key_a in service._missing_checked_at and key_b not in service._missing_checked_at
    assert key_a in service._spawning and key_b not in service._spawning
    assert client_a.closed == 0 and client_b.closed == 1


@pytest.mark.asyncio
async def test_local_release_does_not_detach_remote_clients_with_same_posix_root():
    from atlas.lsp.manager import LSPService

    service = LSPService(enabled=False, idle_timeout=60, exclude_roots=[])

    class Client:
        server_id = "fixture-lsp"
        workspace_root = "/srv/project"
        workspace_folders = [workspace_root]
        remote_workspace_uri = None
        remote_authority_key = None

        def __init__(self):
            self.closed = 0

        async def shutdown(self):
            self.closed += 1

    local = Client()
    remote_a, remote_b = Client(), Client()
    remote_a.remote_workspace_uri = "ssh://fixture/srv/project"
    remote_a.remote_authority_key = "ssh://authority-a@fixture"
    remote_b.remote_workspace_uri = "ssh://fixture/srv/project"
    remote_b.remote_authority_key = "ssh://authority-b@fixture"
    local_key = ("fixture-lsp", "/srv/project")
    remote_key_a = ("fixture-lsp", "ssh://authority-a@fixture/srv/project")
    remote_key_b = ("fixture-lsp", "ssh://authority-b@fixture/srv/project")
    service._clients.update({local_key: local, remote_key_a: remote_a, remote_key_b: remote_b})
    service._last_used.update({local_key: 1.0, remote_key_a: 2.0, remote_key_b: 3.0})
    service._broken.update({local_key: 1.0, remote_key_a: 2.0, remote_key_b: 3.0})
    service._missing.update({local_key, remote_key_a, remote_key_b})
    service._missing_checked_at.update({local_key: 1.0, remote_key_a: 2.0, remote_key_b: 3.0})

    assert await service._release_async("/srv/project") == 1
    assert service._clients == {remote_key_a: remote_a, remote_key_b: remote_b}
    assert local.closed == 1 and remote_a.closed == remote_b.closed == 0
    assert set(service._last_used) == {remote_key_a, remote_key_b}
    assert set(service._broken) == {remote_key_a, remote_key_b}
    assert service._missing == {remote_key_a, remote_key_b}
    assert set(service._missing_checked_at) == {remote_key_a, remote_key_b}


@pytest.mark.asyncio
async def test_lsp_cache_missing_and_broken_state_are_isolated_by_remote_authority():
    from atlas.lsp.manager import LSPService

    server = custom_servers({"fixture-lsp": {
        "extensions": [".fixture"], "command": ["fixture-lsp"],
        "root_markers": ["fixture.toml"],
    }})
    service = LSPService(enabled=False, idle_timeout=0, extra_servers=server, exclude_roots=[])
    authority_a, authority_b = _RemoteWorld(), _RemoteWorld()
    authority_b.authority_id = "authority-43"
    authority_b.authority_key = "ssh://authority-43@fixture-host"
    authority_a.resolve_binary = lambda *_args: None

    file_path = "/srv/project/packages/app/src/main.fixture"
    key_a = ("fixture-lsp", authority_a.cache_key("/srv/project/packages/app"))
    key_b = ("fixture-lsp", authority_b.cache_key("/srv/project/packages/app"))
    assert key_a != key_b
    assert await service._get_or_spawn(file_path, remote_world=authority_a) is None
    service._broken[key_a] = float("inf")
    assert await service._get_or_spawn(file_path, remote_world=authority_a) is None
    assert key_a in service._broken
    assert key_a in service._missing  # missing probe state is authority-scoped too

    client_b = await service._get_or_spawn(file_path, remote_world=authority_b)
    assert client_b is not None
    assert await service._get_or_spawn(file_path, remote_world=authority_b) is client_b
    assert service._clients == {key_b: client_b}
    assert key_b not in service._broken and key_b not in service._missing
    await service._shutdown_async()
