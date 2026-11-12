from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from atlas.engine.kernel.loop import AtlasKernel
from atlas.origin_guard import OriginGuard
from atlas.runtime.external_process import ExternalProcessAdapter

pytestmark = pytest.mark.unit


async def test_external_close_terminates_real_child_and_removes_session():
    adapter = ExternalProcessAdapter(
        "audit-child", sys.executable, ["-u", "-c", "import time; time.sleep(60)"],
    )
    session = await adapter.start_session()
    state = adapter._sessions[session.id]
    try:
        await asyncio.wait_for(adapter.close(session), timeout=8)
        assert state.process.returncode is not None
        assert session.id not in adapter._sessions
        assert all(task.done() for task in state.readers)
        await adapter.close(session)
    finally:
        if state.process.returncode is None:
            state.process.kill()
            await state.process.wait()
        for task in state.readers:
            task.cancel()
        await asyncio.gather(*state.readers, return_exceptions=True)


async def test_tool_history_is_limited_and_isolated_per_runtime():
    kernel = AtlasKernel.__new__(AtlasKernel)
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "call-1", "function": {
            "name": "local_shell", "arguments": '{"command":"echo test"}',
        }}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "test"},
    ]
    runtime = SimpleNamespace(tool_history_callback=lambda: list(messages))
    result = await kernel._dispatch(
        SimpleNamespace(), runtime, "history", "read_tool_history", {"limit": 1}, asyncio.Queue(),
    )
    assert result["data"]["items"] == [{"kind": "result", "id": "call-1", "content": "test"}]
    other = SimpleNamespace(tool_history_callback=lambda: [])
    result = await kernel._dispatch(
        SimpleNamespace(), other, "history", "read_tool_history", {}, asyncio.Queue(),
    )
    assert result["data"]["items"] == []
    missing = await kernel._dispatch(
        SimpleNamespace(), SimpleNamespace(), "history", "read_tool_history", {}, asyncio.Queue(),
    )
    assert missing["is_error"] is True


@pytest.mark.parametrize("host", ["192.0.2.15", "2001:db8::15"])
async def test_remote_http_requires_token_even_with_allowed_origin(monkeypatch, host):
    async def ok(request):
        return PlainTextResponse("ok")

    app = OriginGuard(Starlette(routes=[Route("/", ok)]))
    transport = ASGITransport(app=app, client=(host, 50000))
    async with AsyncClient(transport=transport, base_url="http://atlas") as client:
        monkeypatch.delenv("ATLAS_API_TOKEN", raising=False)
        assert (await client.get("/")).status_code == 403
        assert (await client.get("/", headers={"Origin": "http://localhost:5173"})).status_code == 403
        monkeypatch.setenv("ATLAS_API_TOKEN", "secret")
        assert (await client.get("/", headers={"X-Atlas-Api-Token": "wrong"})).status_code == 403
        assert (await client.get("/", headers={"X-Atlas-Api-Token": "secret"})).status_code == 200


@pytest.mark.parametrize("authorized", [False, True])
async def test_remote_websocket_requires_token_before_application(monkeypatch, authorized):
    monkeypatch.setenv("ATLAS_API_TOKEN", "secret")
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    sent = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    headers = [(b"x-atlas-api-token", b"secret")] if authorized else []
    await OriginGuard(app)({
        "type": "websocket", "headers": headers, "client": ("192.0.2.15", 50000),
    }, receive, send)
    assert called is authorized
    if not authorized:
        assert sent[0]["type"] == "websocket.close"
        assert sent[0]["code"] == 1008
