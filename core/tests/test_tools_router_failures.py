from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from atlas.api.tools_router import ws_terminal


@pytest.mark.asyncio
async def test_terminal_pty_eof_emits_exit_without_background_task_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class ClosedPTY:
        def __init__(self) -> None:
            self.read_called = False
            self.exitstatus = 0

        def isalive(self) -> bool:
            return not self.read_called

        def read(self, _size: int) -> str:
            self.read_called = True
            raise EOFError("pty reached EOF")

        def terminate(self, *, force: bool) -> None:
            del force

    pty = ClosedPTY()
    monkeypatch.setitem(sys.modules, "winpty", SimpleNamespace(PtyProcess=SimpleNamespace(
        spawn=lambda *_args, **_kwargs: pty,
    )))

    class FakeWebSocket:
        messages: list[dict[str, object]]

        def __init__(self) -> None:
            self.messages = []

        async def accept(self) -> None:
            return None

        async def send_json(self, message: dict[str, object]) -> None:
            self.messages.append(message)

        async def receive_json(self) -> dict[str, object]:
            await asyncio.sleep(0.05)
            raise WebSocketDisconnect()

    websocket = FakeWebSocket()
    await ws_terminal(websocket, str(tmp_path))
    await asyncio.sleep(0)

    assert {"type": "exit", "code": 0} in websocket.messages


@pytest.mark.asyncio
@pytest.mark.unit
async def test_ssh_terminal_websocket_routes_protocol_to_ssh_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from atlas.api import tools_router

    class FakeSession:
        def __init__(self) -> None:
            self.writes: list[bytes] = []
            self.resizes: list[tuple[int, int]] = []
            self.closed = False
            self.reads = 0

        async def read(self, _size: int) -> bytes:
            self.reads += 1
            return b"remote output" if self.reads == 1 else b""

        async def wait_closed(self) -> int:
            return 0

        async def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def resize(self, rows: int, cols: int) -> None:
            self.resizes.append((rows, cols))

        async def close(self) -> bool:
            self.closed = True
            return True

    class FakeManager:
        def __init__(self) -> None:
            self.workspace: str | None = None
            self.session = FakeSession()

        async def open_terminal(self, workspace: str) -> FakeSession:
            self.workspace = workspace
            return self.session

    class FakeWebSocket:
        def __init__(self) -> None:
            self.accepted = False
            self.messages: list[dict[str, object]] = []
            self.output_sent = asyncio.Event()
            self.incoming = [
                {"type": "input", "data": "echo remote\r"},
                {"type": "resize", "rows": 41, "cols": 117},
            ]

        async def accept(self) -> None:
            self.accepted = True

        async def send_json(self, message: dict[str, object]) -> None:
            self.messages.append(message)
            if message.get("type") == "output":
                self.output_sent.set()

        async def close(self, *, code: int = 1000) -> None:
            self.messages.append({"type": "websocket.close", "code": code})

        async def receive_json(self) -> dict[str, object]:
            if self.incoming:
                return self.incoming.pop(0)
            await asyncio.wait_for(self.output_sent.wait(), timeout=2.0)
            raise WebSocketDisconnect()

    manager = FakeManager()
    monkeypatch.setattr(tools_router, "_server", lambda: SimpleNamespace(ssh_workspaces=manager))
    websocket = FakeWebSocket()
    workspace = "ssh://remote-alias/srv/project"

    await ws_terminal(websocket, workspace)

    assert websocket.accepted is True
    assert manager.workspace == workspace
    assert manager.session.writes == [b"echo remote\r"]
    assert manager.session.resizes == [(41, 117)]
    assert {"type": "output", "data": "remote output"} in websocket.messages
    assert {"type": "exit", "code": 0} in websocket.messages
    assert manager.session.closed is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_ssh_terminal_websocket_read_failure_cancels_input_and_closes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atlas.api import tools_router

    class FailedOutputSession:
        def __init__(self) -> None:
            self.read_entered = asyncio.Event()
            self.closed = False

        async def read(self, _size: int) -> bytes:
            self.read_entered.set()
            raise OSError("transport read failed")

        async def wait_closed(self) -> int | None:
            return None

        async def close(self) -> bool:
            self.closed = True
            return True

    class FakeManager:
        def __init__(self) -> None:
            self.session = FailedOutputSession()

        async def open_terminal(self, _workspace: str) -> FailedOutputSession:
            return self.session

    class WaitingWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []
            self.receive_cancelled = asyncio.Event()

        async def accept(self) -> None:
            return None

        async def send_json(self, message: dict[str, object]) -> None:
            self.messages.append(message)

        async def close(self, *, code: int = 1000) -> None:
            self.messages.append({"type": "websocket.close", "code": code})

        async def receive_json(self) -> dict[str, object]:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.receive_cancelled.set()
                raise

    manager = FakeManager()
    monkeypatch.setattr(tools_router, "_server", lambda: SimpleNamespace(ssh_workspaces=manager))
    websocket = WaitingWebSocket()

    await asyncio.wait_for(ws_terminal(websocket, "ssh://remote-alias/srv/project"), timeout=1.0)

    assert manager.session.read_entered.is_set()
    assert manager.session.closed is True
    assert websocket.receive_cancelled.is_set()
    assert {"type": "error", "error": "SSH terminal unavailable (OSError)"} in websocket.messages
    assert {"type": "websocket.close", "code": 1011} in websocket.messages
