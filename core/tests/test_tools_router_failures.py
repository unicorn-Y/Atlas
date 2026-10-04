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
