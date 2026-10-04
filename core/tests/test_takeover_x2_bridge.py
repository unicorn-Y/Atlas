"""CLOSEOUT-6 — device-takeover handoff cards bridge to X2 pending resolution.

The fake E2E chain under test::

    original run blocks in x2_pending.wait_for_resolution(run_id)
      → POST /api/devices/handoff {action: open, run_id}  (card carries run_id)
      → 人工 settles the card (done | give_up)
      → the router bridges to atlas.tools.x2.pending
      → the blocked original run resumes ("done") or unwinds (GIVE_UP)

Also guards: no-waiter safety, double resolve → 409, run-less cards never
touch X2, and a pending-side failure can never turn a settled card into a 500.
Router-contract style follows test_devices_router.py (isolated singletons,
bare FastAPI app); HTTP runs on the test's own loop via httpx ASGITransport so
the X2 waiters live on the same event loop (see test_x2_pending.py).
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import atlas.api.device_router as device_router_module
from atlas.api.app_services import AppServices
from atlas.api.device_router import router as device_router
from atlas.devices import DeviceRegistry
from atlas.devices.takeover import TakeoverStateMachine
from atlas.tools.x2 import pending as x2_pending


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


PROBE: dict[str, object] = {"computer": True, "browser": True}


@pytest.fixture(autouse=True)
def clean_x2_registry():
    """No test may leak waiters into another test (same rule as test_x2_pending)."""
    for run_id in x2_pending.pending_runs():
        x2_pending.cancel_run(run_id)
    yield
    for run_id in x2_pending.pending_runs():
        x2_pending.cancel_run(run_id)


@pytest.fixture()
def takeover_stack(tmp_path: Path) -> tuple[DeviceRegistry, TakeoverStateMachine]:
    registry = DeviceRegistry(tmp_path / "devices.json", clock=FakeClock(),
                              probe=lambda: dict(PROBE))
    registry.register_self()
    machine = TakeoverStateMachine(device_id="self", clock=FakeClock())
    device_router_module.set_registry(registry)
    device_router_module.set_takeover(machine)
    yield registry, machine
    device_router_module.set_registry(None)
    device_router_module.set_takeover(None)


@pytest.fixture()
def machine(takeover_stack: tuple[DeviceRegistry, TakeoverStateMachine]) -> TakeoverStateMachine:
    return takeover_stack[1]


@pytest.fixture()
async def client(
    takeover_stack: tuple[DeviceRegistry, TakeoverStateMachine],
) -> AsyncClient:
    # H5 DI: the router reads its services from app.state (same pattern as
    # test_devices_router.py); the instances are the fixture's isolated ones.
    registry, machine = takeover_stack
    app = FastAPI()
    app.state.services = AppServices(device_registry=registry, takeover=machine)
    app.include_router(device_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="test://bridge") as c:
        yield c


async def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Card carries run_id (takeover surface, additive)
# ---------------------------------------------------------------------------
def test_open_handoff_stores_run_id(machine: TakeoverStateMachine) -> None:
    card = machine.open_handoff("2FA 等人工", run_id="run-bridge-1")
    assert card["run_id"] == "run-bridge-1"
    assert card["status"] == "PENDING"
    assert machine.resolve_handoff(card["card_id"], "done")["run_id"] == "run-bridge-1"

    plain = machine.open_handoff("无 run 的老式卡片")  # default keeps legacy shape
    assert plain["run_id"] == ""


# ---------------------------------------------------------------------------
# The fake E2E: blocked run → card → 人工 → x2 resolve → run resumes
# ---------------------------------------------------------------------------
async def test_done_resolution_resumes_the_blocked_original_run(client: AsyncClient) -> None:
    # (a) the fake original run blocks on its pending resolution, then resumes.
    resumed: dict[str, str] = {}

    async def original_run() -> str:
        value = await x2_pending.wait_for_resolution(
            "run-bridge-1", "登录 2FA", ["done", "give_up"], timeout_seconds=10)
        resumed["value"] = value
        return "re-observed-and-resumed"  # the run continues past the block

    run_task = asyncio.create_task(original_run())
    await wait_for(lambda: "run-bridge-1" in x2_pending.pending_runs())

    # (b) open the handoff card linked to the blocked run.
    opened = await client.post("/api/devices/handoff", json={
        "action": "open", "note": "2FA 等人工", "run_id": "run-bridge-1"})
    assert opened.status_code == 200
    card = opened.json()
    assert card["card_id"] and card["status"] == "PENDING"
    assert card["run_id"] == "run-bridge-1"

    listed = (await client.get("/api/devices/handoff?status=PENDING")).json()["cards"]
    assert [c["card_id"] for c in listed] == [card["card_id"]]
    assert listed[0]["run_id"] == "run-bridge-1"

    # (c) 人工 settles done → the router bridges → the blocked run receives "done".
    resolved = await client.post("/api/devices/handoff",
                                 json={"action": "done", "card_id": card["card_id"]})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "done"

    assert await asyncio.wait_for(run_task, timeout=2.0) == "re-observed-and-resumed"
    assert resumed["value"] == "done"
    assert x2_pending.pending_runs() == []  # waiter deregistered


async def test_give_up_resolution_cancels_the_blocked_run(client: AsyncClient) -> None:
    # (d) second blocked run; give_up unwinds it with the GIVE_UP sentinel.
    run_task = asyncio.create_task(x2_pending.wait_for_resolution(
        "run-bridge-2", "页面卡死", ["done", "give_up"], timeout_seconds=10))
    await wait_for(lambda: "run-bridge-2" in x2_pending.pending_runs())

    opened = await client.post("/api/devices/handoff", json={
        "action": "open", "note": "环境异常，放弃本次", "run_id": "run-bridge-2"})
    card = opened.json()

    resolved = await client.post("/api/devices/handoff",
                                 json={"action": "give_up", "card_id": card["card_id"]})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "give_up"

    assert await asyncio.wait_for(run_task, timeout=2.0) == x2_pending.GIVE_UP


# ---------------------------------------------------------------------------
# Safety / regression guards
# ---------------------------------------------------------------------------
async def test_resolve_card_with_no_pending_waiter_is_safe(client: AsyncClient) -> None:
    # (e) card whose run_id has no live waiter: settles fine, resolve → False.
    opened = await client.post("/api/devices/handoff", json={
        "action": "open", "note": "没人等这张卡", "run_id": "run-nobody"})
    card = opened.json()
    assert x2_pending.resolve("run-nobody", "done") is False  # precondition: truly no waiter

    resolved = await client.post("/api/devices/handoff",
                                 json={"action": "done", "card_id": card["card_id"]})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "done"
    assert x2_pending.pending_runs() == []


async def test_double_resolve_still_conflicts(client: AsyncClient) -> None:
    # (f) the bridge must not change the card terminal-once rule.
    opened = await client.post("/api/devices/handoff", json={
        "action": "open", "note": "n", "run_id": "run-double"})
    card = opened.json()
    first = await client.post("/api/devices/handoff",
                              json={"action": "done", "card_id": card["card_id"]})
    assert first.status_code == 200
    again = await client.post("/api/devices/handoff",
                              json={"action": "give_up", "card_id": card["card_id"]})
    assert again.status_code == 409


async def test_card_without_run_id_never_touches_x2(client: AsyncClient, monkeypatch) -> None:
    # (f) legacy cards keep the old behavior: zero x2.pending interaction.
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(x2_pending, "resolve",
                        lambda run_id, value: calls.append((run_id, value)) or False)
    monkeypatch.setattr(x2_pending, "cancel_run", lambda run_id: calls.append((run_id, "cancel")))

    opened = await client.post("/api/devices/handoff",
                               json={"action": "open", "note": "老式卡片，无 run"})
    card = opened.json()
    assert card["run_id"] == ""

    resolved = await client.post("/api/devices/handoff",
                                 json={"action": "done", "card_id": card["card_id"]})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "done"
    assert calls == []


async def test_pending_side_failure_never_breaks_the_settled_card(
        client: AsyncClient, monkeypatch) -> None:
    def explode(run_id: str, value: str) -> bool:
        raise RuntimeError("x2 registry exploded")

    monkeypatch.setattr(x2_pending, "resolve", explode)

    opened = await client.post("/api/devices/handoff", json={
        "action": "open", "note": "n", "run_id": "run-boom"})
    card = opened.json()

    resolved = await client.post("/api/devices/handoff",
                                 json={"action": "done", "card_id": card["card_id"]})
    assert resolved.status_code == 200  # logged and swallowed, card stays settled
    assert resolved.json()["status"] == "done"


async def test_bridge_targets_the_run_id_on_the_card(client: AsyncClient, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(x2_pending, "resolve",
                        lambda run_id, value: calls.append((run_id, value)) or False)
    monkeypatch.setattr(x2_pending, "cancel_run", lambda run_id: calls.append((run_id, "cancel")))

    opened = await client.post("/api/devices/handoff", json={
        "action": "open", "note": "n", "run_id": "run-spy"})
    card = opened.json()
    await client.post("/api/devices/handoff",
                      json={"action": "done", "card_id": card["card_id"]})
    assert calls == [("run-spy", "done")]  # done → resolve(run_id, "done"), nothing else
