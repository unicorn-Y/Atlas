import asyncio
import json
import posixpath
import threading
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from atlas.lsp.client import LSPClient
from atlas.lsp.protocol import encode_message
from atlas.ssh import SSHWorkspaceManager, _SSHBridgeProcess

pytestmark = pytest.mark.unit


class _OwnerLoopStdin:
    def __init__(self, allow_drain: asyncio.Event):
        self.allow_drain = allow_drain
        self.drain_entered = asyncio.Event()
        self.data = bytearray()
        self.eof = False

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    def write_eof(self) -> None:
        self.eof = True

    async def drain(self) -> None:
        self.drain_entered.set()
        await self.allow_drain.wait()


class _OwnerLoopProcess:
    def __init__(self, allow_drain: asyncio.Event):
        self.stdin = _OwnerLoopStdin(allow_drain)
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.closed = asyncio.Event()
        self.exit_status = None
        self.terminated = False

    def terminate(self):
        self.terminated = True
        self.exit_status = 0
        self.closed.set()

    async def wait_closed(self):
        await self.closed.wait()


@pytest.mark.asyncio
async def test_raw_ssh_lsp_bridge_keeps_bytes_and_backpressure_across_loops():
    owner_loop = asyncio.get_running_loop()
    allow_drain = asyncio.Event()
    process = _OwnerLoopProcess(allow_drain)
    released = []
    adapter = _SSHBridgeProcess(owner_loop, process, released.append)
    inbound = b"Content-Length: 7\r\n\r\n\x00\xff\xe2\x98\x83!"
    outbound = b"Content-Length: 4\r\n\r\n\x00\xff\xe2\x98"

    def client_loop_round_trip():
        async def _round_trip():
            adapter.stdin.write(outbound)
            await adapter.stdin.drain()
            adapter.stdin.close()
            await adapter.stdin.drain()
            return await adapter.stdout.readexactly(len(inbound))

        return asyncio.run(_round_trip())

    task = asyncio.create_task(asyncio.to_thread(client_loop_round_trip))
    await asyncio.wait_for(process.stdin.drain_entered.wait(), timeout=1.0)
    assert not task.done()  # remote drain is backpressured; the SSH owner loop remains usable
    allow_drain.set()
    process.stdout.feed_data(inbound[:13])
    await asyncio.sleep(0)
    process.stdout.feed_data(inbound[13:])
    assert await asyncio.wait_for(task, timeout=2.0) == inbound
    assert bytes(process.stdin.data) == outbound
    assert process.stdin.eof is True  # write_eof is synchronous in the AsyncSSH API
    await asyncio.to_thread(asyncio.run, adapter.kill())
    assert process.terminated is True
    assert released == [adapter]


class _FakeLSPStdin:
    def __init__(self, stdout: asyncio.StreamReader, process):
        self.stdout = stdout
        self.process = process
        self.messages = []
        self._closing = False

    def is_closing(self):
        return self._closing

    def write(self, data: bytes):
        header, body = data.split(b"\r\n\r\n", 1)
        message = json.loads(body[:int(header.split(b": ", 1)[1])])
        self.messages.append(message)
        if message.get("method") == "initialize":
            result = {"capabilities": {"textDocumentSync": 1}}
        elif message.get("method") == "shutdown":
            result = None
        else:
            result = None
        if "id" in message:
            self.stdout.feed_data(encode_message({
                "jsonrpc": "2.0", "id": message["id"], "result": result,
            }))
        if message.get("method") == "exit":
            self.process.returncode = 0
            self.stdout.feed_eof()
            self.process.stderr.feed_eof()
            self.process.exited.set()

    async def drain(self):
        await asyncio.sleep(0)


class _FakeLSPProcess:
    remote = True
    pid = None

    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.exited = asyncio.Event()
        self.returncode = None
        self.stdin = _FakeLSPStdin(self.stdout, self)

    async def wait(self):
        await self.exited.wait()
        return self.returncode

    async def kill(self):
        self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.exited.set()


@pytest.mark.asyncio
async def test_lsp_client_injected_remote_process_uses_target_uri_and_null_process_id(monkeypatch, tmp_path):
    process = _FakeLSPProcess()
    factory_calls = []

    async def process_factory(command, cwd, env):
        factory_calls.append((command, cwd, env))
        return process

    remote_root = "/srv/project with space"
    remote_file = posixpath.join(remote_root, "src", "café.py")
    to_uri = lambda path: "file://" + quote(path, safe="/:@")
    from_uri = lambda uri: uri.removeprefix("file://")
    reads = []

    async def read_document(path):
        reads.append(path)
        return "remote source body"

    def forbidden_local_kill(*_args, **_kwargs):
        raise AssertionError("remote process cleanup called host PID-tree killer")

    monkeypatch.setattr("atlas.lsp.client.kill_process_tree", forbidden_local_kill)
    client = LSPClient(
        server_id="fixture-lsp", workspace_root=remote_root,
        command=["pyright-langserver", "--stdio"], cwd=remote_root,
        process_factory=process_factory, uri_for_path=to_uri,
        path_from_uri=from_uri, normalize_path=posixpath.normpath,
        read_document=read_document, process_id=None,
    )
    await client.start()
    await client.open_file(remote_file, language_id="python")
    initialize = next(msg for msg in process.stdin.messages if msg.get("method") == "initialize")
    assert initialize["params"]["processId"] is None
    assert initialize["params"]["rootUri"] == to_uri(remote_root)
    assert initialize["params"]["workspaceFolders"][0]["uri"] == to_uri(remote_root)
    opened = next(msg for msg in process.stdin.messages if msg.get("method") == "textDocument/didOpen")
    assert opened["params"]["textDocument"] == {
        "uri": to_uri(remote_file), "languageId": "python", "version": 0,
        "text": "remote source body",
    }
    assert reads == [remote_file]
    assert factory_calls == [(["pyright-langserver", "--stdio"], remote_root, {})]
    await client.shutdown()
    assert client._exit_code == 0


@pytest.mark.asyncio
async def test_cancelled_remote_spawn_disposes_late_process_and_releases_lease():
    owner_loop = asyncio.get_running_loop()
    manager = SSHWorkspaceManager()
    create_entered = asyncio.Event()
    allow_create = asyncio.Event()
    process = _OwnerLoopProcess(asyncio.Event())

    class Connection:
        active_leases = 0
        last_used = 0.0
        client = None

    connection = Connection()

    class SSHClient:
        async def create_process(self, *_args, **_kwargs):
            create_entered.set()
            await allow_create.wait()
            return process

    connection.client = SSHClient()
    manager._process_cwd = lambda workspace, cwd: ("host", "/srv/project")
    async def process_command(*_args, **_kwargs):
        return "fixture-lsp --stdio"
    manager._process_command = process_command
    async def connect(_host, **_kwargs):
        return connection
    manager._connect = connect

    factory = manager.make_lsp_process_factory("ssh://host/srv/project", owner_loop)
    spawn = asyncio.create_task(factory(["fixture-lsp", "--stdio"], "/srv/project", {}))
    await asyncio.wait_for(create_entered.wait(), timeout=1)
    spawn.cancel()
    allow_create.set()
    with pytest.raises(asyncio.CancelledError):
        await spawn

    async def disposed():
        while manager._lsp_processes or connection.active_leases:
            await asyncio.sleep(0.005)
    await asyncio.wait_for(disposed(), timeout=1)
    assert connection.active_leases == 0
    assert process.terminated is True


@pytest.mark.asyncio
async def test_completed_spawn_cancelled_before_client_delivery_schedules_cleanup_on_owner_loop(monkeypatch):
    owner_loop = asyncio.get_running_loop()
    previous_debug = owner_loop.get_debug()
    owner_loop.set_debug(True)
    manager = SSHWorkspaceManager()
    process = _OwnerLoopProcess(asyncio.Event())

    class Connection:
        active_leases = 0
        last_used = 0.0
        client = None

    connection = Connection()

    class SSHClient:
        async def create_process(self, *_args, **_kwargs):
            return process

    connection.client = SSHClient()
    manager._process_cwd = lambda workspace, cwd: ("host", "/srv/project")
    async def process_command(*_args, **_kwargs):
        return "fixture-lsp --stdio"
    manager._process_command = process_command
    async def connect(_host, **_kwargs):
        return connection
    manager._connect = connect

    completed = threading.Event()
    release_delivery = threading.Event()
    cancelled = threading.Event()
    original_wrap_future = asyncio.wrap_future

    def delayed_wrap_future(concurrent_future, loop=None):
        target_loop = loop or asyncio.get_running_loop()
        target = target_loop.create_future()

        def deliver(done):
            completed.set()

            async def wait_then_deliver():
                while not release_delivery.is_set():
                    await asyncio.sleep(0.002)
                if target.done():
                    return
                try:
                    value = done.result()
                except BaseException as exc:
                    target.set_exception(exc)
                else:
                    target.set_result(value)

            target_loop.call_soon_threadsafe(target_loop.create_task, wait_then_deliver())

        concurrent_future.add_done_callback(deliver)
        return target

    monkeypatch.setattr("atlas.ssh.asyncio.wrap_future", delayed_wrap_future)
    factory = manager.make_lsp_process_factory("ssh://host/srv/project", owner_loop)
    client_loop = asyncio.new_event_loop()
    client_task = None

    async def call_factory():
        try:
            await factory(["fixture-lsp", "--stdio"], "/srv/project", {})
        except asyncio.CancelledError:
            cancelled.set()

    def run_client_loop():
        nonlocal client_task
        asyncio.set_event_loop(client_loop)
        client_task = client_loop.create_task(call_factory())
        client_loop.run_forever()
        client_loop.close()

    thread = threading.Thread(target=run_client_loop, daemon=True)
    thread.start()
    try:
        assert await asyncio.to_thread(completed.wait, 1.0)
        # The owner-side concurrent future is complete, while its client-loop result
        # remains deliberately gated.  Cancel precisely inside that delivery window.
        assert connection.active_leases == 1
        client_loop.call_soon_threadsafe(client_task.cancel)
        assert await asyncio.to_thread(cancelled.wait, 1.0)
        release_delivery.set()

        async def cleaned():
            while manager._lsp_processes or connection.active_leases:
                await asyncio.sleep(0.005)

        await asyncio.wait_for(cleaned(), timeout=1.0)
        assert process.terminated is True
        assert connection.active_leases == 0
        assert not manager._lsp_processes
    finally:
        release_delivery.set()
        if thread.is_alive():
            client_loop.call_soon_threadsafe(client_loop.stop)
            await asyncio.to_thread(thread.join, 1.0)
        owner_loop.set_debug(previous_debug)
        asyncio.wrap_future = original_wrap_future


@pytest.mark.asyncio
async def test_remote_client_retains_process_handle_after_unconfirmed_cleanup_for_retry():
    class RetryableRemoteProcess:
        remote = True
        pid = None
        stdout = None
        stderr = None

        def __init__(self):
            self.returncode = None
            self.kill_calls = 0

        async def kill(self):
            self.kill_calls += 1
            if self.kill_calls == 1:
                raise TimeoutError("remote channel closure not confirmed")
            self.returncode = 0

    process = RetryableRemoteProcess()
    client = LSPClient(server_id="retry", workspace_root="/remote", command=["lsp"])
    client._proc = process

    with pytest.raises(TimeoutError, match="not confirmed"):
        await client._cleanup_process()
    assert client._proc is process
    assert client._exit_code is None

    client._stopping = True
    await client.shutdown()
    assert process.kill_calls == 2
    assert client._proc is None
    assert client._exit_code == 0


@pytest.mark.asyncio
async def test_terminal_manager_close_bounds_unacknowledged_spawn_and_cleans_late_handle():
    manager = SSHWorkspaceManager()

    class LateTerminalProcess:
        def __init__(self):
            self.exit_status = None
            self.close_calls = 0
            self.closed = asyncio.Event()

        def close(self):
            self.close_calls += 1
            self.closed.set()

        async def wait_closed(self):
            await self.closed.wait()

    process = LateTerminalProcess()

    class Client:
        def __init__(self):
            self.create_entered = asyncio.Event()
            self.return_late_handle = asyncio.Event()
            self.transport_closed = asyncio.Event()
            self.close_calls = 0

        async def create_process(self, *_args, **_kwargs):
            self.create_entered.set()
            await self.return_late_handle.wait()
            return process

        def close(self):
            self.close_calls += 1
            self.transport_closed.set()
            self.return_late_handle.set()

        async def wait_closed(self):
            await self.transport_closed.wait()

    class Connection:
        authority_id = "authority-terminal"
        active_leases = 0
        last_used = 0.0

        def __init__(self):
            self.client = Client()

    connection = Connection()
    manager._process_cwd = lambda _workspace, _cwd: ("alias", "/srv/project")

    async def resolve_authority(_host):
        return SimpleNamespace(id=connection.authority_id)

    async def connect(_host, **_kwargs):
        manager._pool[connection.authority_id] = connection
        return connection

    async def terminal_command(*_args, **_kwargs):
        return "fixture-shell"

    manager.resolve_authority = resolve_authority
    manager._connect = connect
    manager._terminal_command = terminal_command

    opening = asyncio.create_task(manager.open_terminal("ssh://alias/srv/project"))
    await asyncio.wait_for(connection.client.create_entered.wait(), timeout=1.0)
    await asyncio.wait_for(manager.close(), timeout=1.0)
    opened = await asyncio.wait_for(asyncio.gather(opening, return_exceptions=True), timeout=1.0)

    assert isinstance(opened[0], ConnectionError)
    assert connection.client.close_calls == 1
    assert process.close_calls == 1
    assert process.exit_status is None  # Local channel cleanup is not remote exit proof.
    assert connection.active_leases == 0
    assert manager._terminal_sessions == set()
    assert manager._terminal_cleanup_tasks == set()
