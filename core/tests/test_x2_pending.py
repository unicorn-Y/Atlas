"""X2 pending-resolution registry tests — the single card resolution channel.

Covers: wait→resolve happy path, timeout → "" (confirm_foreground reads deny),
cancel_run → "give_up" (asyncio + threading events), multi-writer delivery,
double-resolve safety, the registration wiring (run-scoped waits bypass
input_callback; empty run_id keeps the fallback), and BOTH frontend endpoints
(``POST /api/computer/foreground``, ``POST /api/browser/handoff``) resolving a
blocked X2 wait.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from atlas.tools.x2 import pending as x2pending
from atlas.tools.x2 import registration as x2registration
from atlas.tools.x2.context import X2Context


@pytest.fixture(autouse=True)
def clean_registry():
    """No test may leak waiters into another test."""
    for run_id in x2pending.pending_runs():
        x2pending.cancel_run(run_id)
    yield
    for run_id in x2pending.pending_runs():
        x2pending.cancel_run(run_id)


async def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


class FakeBoundContext:
    """Stand-in for the bound Atlas AgentContext (run-scoped fields only)."""

    def __init__(self, run_id: str = "run-1") -> None:
        self.run_id = run_id
        self.conversation_id = "conv-1"
        self.event_queue = None
        self.input_callback = None
        self.approval_callback = None
        self.cancel_event = asyncio.Event()


# ---------------------------------------------------------------------------
# Registry primitives
# ---------------------------------------------------------------------------
async def test_wait_then_resolve_happy_path() -> None:
    task = asyncio.create_task(
        x2pending.wait_for_resolution("run-1", "需要人工处理", ["open_panel", "done", "give_up"]))
    await wait_for(lambda: "run-1" in x2pending.pending_runs())

    assert x2pending.resolve("run-1", "done") is True
    assert await asyncio.wait_for(task, timeout=2.0) == "done"
    assert x2pending.pending_runs() == []  # waiter deregistered


async def test_resolve_delivers_to_every_waiter_of_the_run() -> None:
    first = asyncio.create_task(x2pending.wait_for_resolution("run-1", "a", ["x"]))
    second = asyncio.create_task(x2pending.wait_for_resolution("run-1", "b", ["x"]))
    await wait_for(lambda: x2pending.pending_runs().count("run-1") == 1)

    assert x2pending.resolve("run-1", "done") is True
    assert await asyncio.wait_for(first, timeout=2.0) == "done"
    assert await asyncio.wait_for(second, timeout=2.0) == "done"


async def test_resolve_unknown_run_returns_false() -> None:
    assert x2pending.resolve("run-404", "done") is False


async def test_timeout_returns_empty_and_foreground_reads_it_as_deny() -> None:
    started = time.monotonic()
    value = await x2pending.wait_for_resolution(
        "run-t", "需要切到前台", ["allow", "deny"], timeout_seconds=0.05)
    assert value == ""
    assert time.monotonic() - started < 2.0
    assert x2pending.pending_runs() == []

    # Caller-side semantics: confirm_foreground treats "" as NOT allowed.
    ctx = X2Context(run_id="run-t", wait_input=lambda p, o: x2pending.wait_for_resolution(
        "run-t", p, o, timeout_seconds=0.05))
    assert await ctx.confirm_foreground("需要前台") is False


async def test_cancel_run_resolves_pending_with_give_up() -> None:
    task = asyncio.create_task(
        x2pending.wait_for_resolution("run-c", "等待中", ["done"], timeout_seconds=30))
    await wait_for(lambda: "run-c" in x2pending.pending_runs())

    x2pending.cancel_run("run-c")
    assert await asyncio.wait_for(task, timeout=2.0) == x2pending.GIVE_UP


async def test_cancel_event_asyncio_and_threading_variants() -> None:
    async_ev = asyncio.Event()
    task = asyncio.create_task(x2pending.wait_for_resolution(
        "run-a", "q", ["done"], cancel_event=async_ev, timeout_seconds=30))
    await wait_for(lambda: "run-a" in x2pending.pending_runs())
    async_ev.set()
    assert await asyncio.wait_for(task, timeout=2.0) == x2pending.GIVE_UP

    thread_ev = threading.Event()  # non-asyncio events are polled
    task = asyncio.create_task(x2pending.wait_for_resolution(
        "run-b", "q", ["done"], cancel_event=thread_ev, timeout_seconds=30))
    await wait_for(lambda: "run-b" in x2pending.pending_runs())
    thread_ev.set()
    assert await asyncio.wait_for(task, timeout=2.0) == x2pending.GIVE_UP


async def test_cancel_event_already_set_returns_immediately() -> None:
    ev = asyncio.Event()
    ev.set()
    assert await x2pending.wait_for_resolution(
        "run-x", "q", ["done"], cancel_event=ev, timeout_seconds=30) == x2pending.GIVE_UP


async def test_double_resolve_is_safe_and_reports_no_waiter() -> None:
    task = asyncio.create_task(x2pending.wait_for_resolution("run-d", "q", ["done"]))
    await wait_for(lambda: "run-d" in x2pending.pending_runs())

    assert x2pending.resolve("run-d", "open_panel") is True
    assert await asyncio.wait_for(task, timeout=2.0) == "open_panel"
    assert x2pending.resolve("run-d", "done") is False  # nothing pending anymore


async def test_resolve_from_foreign_thread_delivers() -> None:
    """Resolutions come from the server loop/thread — delivery must be thread-safe."""
    task = asyncio.create_task(x2pending.wait_for_resolution("run-f", "q", ["done"]))
    await wait_for(lambda: "run-f" in x2pending.pending_runs())
    result: dict[str, Any] = {}

    def from_thread() -> None:
        result["ok"] = x2pending.resolve("run-f", "done")

    await asyncio.to_thread(from_thread)
    assert result["ok"] is True
    assert await asyncio.wait_for(task, timeout=2.0) == "done"


# ---------------------------------------------------------------------------
# Registration wiring
# ---------------------------------------------------------------------------
async def test_run_scoped_wait_input_bypasses_input_callback() -> None:
    def must_not_be_called(call_id: str, prompt: str, options: Any) -> str:
        raise AssertionError("input_callback must not be used for run-scoped X2 waits")

    bound = FakeBoundContext("run-9")
    bound.input_callback = must_not_be_called
    ctx = x2registration.build_x2_context(bound)

    task = asyncio.create_task(ctx.request_handoff("登录验证", "https://example.com"))
    await wait_for(lambda: "run-9" in x2pending.pending_runs())
    assert x2pending.resolve("run-9", "open_panel")
    assert await asyncio.wait_for(task, timeout=2.0) == "open_panel"


async def test_empty_run_id_falls_back_to_input_callback() -> None:
    prompts: list[str] = []

    def input_callback(call_id: str, prompt: str, options: Any) -> str:
        prompts.append(prompt)
        return "deny"

    bound = FakeBoundContext("")
    bound.input_callback = input_callback
    ctx = x2registration.build_x2_context(bound)

    assert await ctx.confirm_foreground("需要前台") is False
    assert prompts and "前台" in prompts[0]
    assert x2pending.pending_runs() == []


async def test_run_cancel_event_is_honored_by_wait_input(monkeypatch) -> None:
    bound = FakeBoundContext("run-z")
    ctx = x2registration.build_x2_context(bound)
    task = asyncio.create_task(ctx.confirm_foreground("需要前台"))
    await wait_for(lambda: "run-z" in x2pending.pending_runs())
    bound.cancel_event.set()  # run cancelled while the card is open
    assert await asyncio.wait_for(task, timeout=2.0) is False


async def test_sync_handler_times_out_with_chinese_error(monkeypatch) -> None:
    monkeypatch.setattr(x2registration, "_TOOL_CALL_TIMEOUT_SECONDS", 0.05)
    bound = FakeBoundContext("run-1")
    loop = asyncio.get_running_loop()

    async def slow_bridge(name: str, args: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(1.0)
        return {"ok": True}

    handler = x2registration._make_sync_handler(
        "browser_navigate", slow_bridge, lambda session_id: (None, bound, loop))
    result = json.loads(handler({}))
    assert "超时" in result["error"] and "310" not in result["error"]


# ---------------------------------------------------------------------------
# Frontend endpoints resolve a blocked wait (the fix's contract)
# ---------------------------------------------------------------------------
def build_app() -> FastAPI:
    from atlas.api import browser_router as browser_router_module
    from atlas.api import computer_router as computer_router_module

    app = FastAPI()
    app.include_router(browser_router_module.router)
    app.include_router(computer_router_module.router)
    return app


async def test_foreground_endpoint_resolves_blocked_confirmation() -> None:
    bound = FakeBoundContext("run-1")
    ctx = x2registration.build_x2_context(bound)
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="test://x") as client:
        nobody = await client.post("/api/computer/foreground", json={"run_id": "run-404", "approve": True})
        assert nobody.status_code == 404

        bad = await client.post("/api/computer/foreground", json={"run_id": "  ", "approve": True})
        assert bad.status_code == 422

        approved = asyncio.create_task(ctx.confirm_foreground("需要接管前台"))
        await wait_for(lambda: "run-1" in x2pending.pending_runs())
        ok = await client.post("/api/computer/foreground", json={"run_id": "run-1", "approve": True})
        assert ok.status_code == 200 and ok.json()["status"] == "ok"
        assert await asyncio.wait_for(approved, timeout=2.0) is True

        denied = asyncio.create_task(ctx.confirm_foreground("再次接管"))
        await wait_for(lambda: "run-1" in x2pending.pending_runs())
        ok = await client.post("/api/computer/foreground", json={"run_id": "run-1", "approve": False})
        assert ok.status_code == 200
        assert await asyncio.wait_for(denied, timeout=2.0) is False


async def test_handoff_endpoint_resolves_blocked_request_handoff() -> None:
    bound = FakeBoundContext("run-1")
    ctx = x2registration.build_x2_context(bound)
    async with AsyncClient(transport=ASGITransport(app=build_app()), base_url="test://x") as client:
        bad = await client.post("/api/browser/handoff", json={"run_id": "run-1", "resolution": "maybe"})
        assert bad.status_code == 422

        task = asyncio.create_task(ctx.request_handoff("支付确认", "https://pay.example.com"))
        await wait_for(lambda: "run-1" in x2pending.pending_runs())
        ok = await client.post("/api/browser/handoff", json={"run_id": "run-1", "resolution": "done"})
        assert ok.status_code == 200
        assert await asyncio.wait_for(task, timeout=2.0) == "done"


async def test_shutdown_cancels_pending_waits() -> None:
    from atlas.tools.x2 import computer as x2computer

    x2computer.set_runtime(None)  # only the pending-wait cancellation is under test
    blocked = asyncio.create_task(x2pending.wait_for_resolution("run-s", "q", ["done"]))
    await wait_for(lambda: "run-s" in x2pending.pending_runs())

    await x2computer.shutdown()  # module hook: cancels pending waits, never raises
    assert await asyncio.wait_for(blocked, timeout=2.0) == x2pending.GIVE_UP
