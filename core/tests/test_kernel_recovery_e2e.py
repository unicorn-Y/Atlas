"""Crash a real isolated backend after a tool side effect, then resume over WS."""

from __future__ import annotations

import asyncio
import shutil

import pytest

from tests.fakes.fake_llm_provider import Error, FakeLLMServer, Text, ToolCall
from tests.fakes.k1_harness import RestartableBackend, ws_run
from tests.test_c1_websocket_acceptance import IsolatedBackend

pytestmark = pytest.mark.integration


def assert_paired(messages):
    pending = set()
    for message in messages:
        if message["role"] == "tool":
            call_id = message.get("tool_call_id")
            assert call_id in pending, "orphan or duplicate tool result reached provider"
            pending.remove(call_id)
        else:
            assert not pending, "a non-tool message split the tool call/result group"
            pending.update(call["id"] for call in message.get("tool_calls", []))
    assert not pending, "unanswered tool calls reached provider"


@pytest.mark.asyncio
@pytest.mark.skipif(__import__("sys").platform != "win32", reason="PowerShell crash scenario")
async def test_backend_crash_recovers_tool_history_without_replaying_side_effect(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = workspace / "side-effect.txt"
    dispatched = False

    def responder(record):
        nonlocal dispatched
        try:
            assert_paired(record["body"]["messages"])
        except AssertionError as exc:
            return Error(400, str(exc))
        if not dispatched:
            dispatched = True
            return ToolCall("local_shell", {"shell": "powershell", "command":
                f"Add-Content -LiteralPath '{marker}' -Value started; Start-Sleep -Seconds 120"})
        return Text("RECOVERY_COMPLETED_WITHOUT_REPLAY")

    with FakeLLMServer(responder) as fake:
        first_root = tmp_path / "before-crash"
        server = IsolatedBackend(first_root, fake)
        active = None
        try:
            await server.ready()
            conversation = await server.conversation()
            active = asyncio.create_task(ws_run(server, "Perform the isolated task",
                conversation=conversation, workspace=str(workspace), permission_mode="full_access"))
            async with asyncio.timeout(60):
                while not marker.exists():
                    if active.done():
                        pytest.fail(f"Run stopped before executing tool: {active.result()}")
                    await asyncio.sleep(0.1)
            assert marker.read_text(encoding="utf-8-sig").splitlines() == ["started"]
        finally:
            # On Windows terminate is an abrupt process exit. close also removes
            # this backend's owned tool descendants, never machine-wide processes.
            await server.close()
            if active is not None:
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)

        second_root = tmp_path / "after-crash"
        shutil.copytree(first_root / "atlas", second_root / "atlas")
        restarted = RestartableBackend(second_root, fake)
        restarted.root, restarted.fake = second_root, fake
        try:
            await restarted.ready()
            before = len(fake.main_requests())
            _, events = await ws_run(restarted, "Continue after the interruption",
                conversation=conversation, workspace=str(workspace), permission_mode="full_access")
            assert events[-1]["event"] == "run.completed", events[-1]
            request = fake.main_requests()[before]
            assert_paired(request["messages"])
            tools = [m for m in request["messages"] if m["role"] == "tool"]
            assert len(tools) == 1
            assert "unknown" in tools[0]["content"].lower()
            assert "safe to retry" not in tools[0]["content"].lower()
            assert marker.read_text(encoding="utf-8-sig").splitlines() == ["started"]
            assert any(e["event"] == "message.completed" and
                       "RECOVERY_COMPLETED_WITHOUT_REPLAY" in str(e["data"].get("content"))
                       for e in events)
        finally:
            await restarted.close()
