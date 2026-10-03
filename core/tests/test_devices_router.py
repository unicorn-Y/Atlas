"""Router contract tests — full /api/devices surface on an isolated tmp_path store.

Builds a bare FastAPI app with only the device router (lane discipline: no
server.py involvement) and injects registry/takeover singletons per test.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import atlas.api.device_router as device_router_module
from atlas.api.device_router import router as device_router
from atlas.devices import DeviceRegistry
from atlas.devices.takeover import TakeoverStateMachine


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


PROBE: dict[str, Any] = {"computer": True, "browser": True, "provider_generation": 1}


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    registry = DeviceRegistry(tmp_path / "devices.json", clock=FakeClock(),
                              probe=lambda: dict(PROBE))
    registry.register_self()
    machine = TakeoverStateMachine(device_id="self", clock=FakeClock())
    device_router_module.set_registry(registry)
    device_router_module.set_takeover(machine)
    app = FastAPI()
    app.include_router(device_router)
    yield TestClient(app)
    device_router_module.set_registry(None)
    device_router_module.set_takeover(None)


# ---------------------------------------------------------------------------
# Device CRUD
# ---------------------------------------------------------------------------
def test_list_devices_includes_self(client: TestClient) -> None:
    res = client.get("/api/devices")
    assert res.status_code == 200
    body = res.json()
    assert body["self"] == "self"
    ids = {device["device_id"] for device in body["devices"]}
    assert "self" in ids
    laptop = next(d for d in body["devices"] if d["device_id"] == "self")
    assert laptop["kind"] == "atlas-laptop"
    assert laptop["online"] is True


def test_ingress_registration_crud(client: TestClient) -> None:
    created = client.post("/api/devices", json={
        "device_id": "phone-1", "display_name": "我的手机", "os": "iOS 18",
        "notes": "仅接收", "capabilities": {"computer": False, "browser": True},
    })
    assert created.status_code == 200
    device = created.json()
    assert device["kind"] == "ingress"
    assert device["online"] is False

    assert client.post("/api/devices", json={
        "device_id": "phone-1", "display_name": "重复"}).status_code == 409
    assert client.post("/api/devices", json={
        "device_id": "self", "display_name": "内置本机"}).status_code == 409
    assert client.post("/api/devices", json={
        "device_id": "bad id!", "display_name": "非法"}).status_code == 422

    fetched = client.get("/api/devices/phone-1")
    assert fetched.status_code == 200
    assert fetched.json()["display_name"] == "我的手机"
    assert client.get("/api/devices/ghost").status_code == 404

    patched = client.patch("/api/devices/phone-1", json={
        "display_name": "客厅手机", "trusted": True,
        "capabilities": {"computer": True, "browser": True}})
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "客厅手机"
    assert patched.json()["generation"] == 2  # capability change revoked the pairing
    assert client.patch("/api/devices/ghost", json={"notes": "x"}).status_code == 404

    deleted = client.delete("/api/devices/phone-1")
    assert deleted.status_code == 200
    assert client.get("/api/devices/phone-1").status_code == 404
    assert client.delete("/api/devices/phone-1").status_code == 404
    assert client.delete("/api/devices/self").status_code == 409  # the laptop stays


def test_presence_beat_and_online_projection(client: TestClient) -> None:
    assert client.post("/api/devices", json={
        "device_id": "phone-1", "display_name": "手机"}).status_code == 200
    assert client.get("/api/devices/phone-1").json()["online"] is False
    beat = client.put("/api/devices/phone-1/presence",
                      json={"activity": "解锁了屏幕"})
    assert beat.status_code == 200
    assert beat.json()["online"] is True
    assert beat.json()["presence"]["state"] == "online"
    assert client.put("/api/devices/ghost/presence", json={}).status_code == 404
    assert client.put("/api/devices/phone-1/presence",
                      json={"last_seen": -1}).status_code == 422


# ---------------------------------------------------------------------------
# Takeover
# ---------------------------------------------------------------------------
def test_takeover_full_matrix_over_http(client: TestClient) -> None:
    assert client.get("/api/devices/takeover").json()["state"] == "FREE"

    bad = client.post("/api/devices/takeover", json={"action": "agent_take"})
    assert bad.status_code == 422  # agent_take without agent_id
    bad = client.post("/api/devices/takeover", json={"action": "agent_take", "agent_id": "user"})
    assert bad.status_code == 422  # "user" is the human, not an agent id
    bad = client.post("/api/devices/takeover", json={"action": "explode"})
    assert bad.status_code == 422

    granted = client.post("/api/devices/takeover",
                          json={"action": "agent_take", "agent_id": "agent:coder"})
    assert granted.status_code == 200
    body = granted.json()
    assert body["state"] == "AGENT" and body["holder"] == "agent:coder"
    assert body["needs_observation"] is True

    preempt = client.post("/api/devices/takeover", json={"action": "human_take", "note": "人来了"})
    assert preempt.status_code == 200
    assert preempt.json()["state"] == "HUMAN"

    denied = client.post("/api/devices/takeover",
                         json={"action": "agent_take", "agent_id": "agent:coder"})
    assert denied.status_code == 409  # agent may not take while human holds
    assert client.get("/api/devices/takeover").json()["state"] == "HUMAN"

    released = client.post("/api/devices/takeover", json={"action": "release"})
    assert released.status_code == 200  # HUMAN release needs no agent_id
    assert released.json()["state"] == "FREE"

    empty = client.post("/api/devices/takeover", json={"action": "release"})
    assert empty.status_code == 409  # nothing to release


def test_takeover_agent_release_requires_agent_id(client: TestClient) -> None:
    assert client.post("/api/devices/takeover",
                       json={"action": "agent_take", "agent_id": "agent:coder"}).status_code == 200
    missing = client.post("/api/devices/takeover", json={"action": "release"})
    assert missing.status_code == 422
    wrong = client.post("/api/devices/takeover",
                        json={"action": "release", "agent_id": "agent:other"})
    assert wrong.status_code == 409
    ok = client.post("/api/devices/takeover",
                     json={"action": "release", "agent_id": "agent:coder"})
    assert ok.status_code == 200
    assert ok.json()["state"] == "FREE"


# ---------------------------------------------------------------------------
# Activity + handoff
# ---------------------------------------------------------------------------
def test_activity_endpoint(client: TestClient) -> None:
    client.post("/api/devices/takeover", json={"action": "human_take"})
    client.post("/api/devices/takeover", json={"action": "release"})
    feed = client.get("/api/devices/activity")
    assert feed.status_code == 200
    events = feed.json()["activity"]
    actions = [e["action"] for e in events]
    assert "control_changed" in actions and "control_released" in actions
    limited = client.get("/api/devices/activity?limit=1").json()["activity"]
    assert len(limited) == 1
    assert limited[0]["seq"] == events[-1]["seq"]  # newest tail
    assert client.get("/api/devices/activity?limit=-1").status_code == 422


def test_handoff_endpoints_lifecycle(client: TestClient) -> None:
    opened = client.post("/api/devices/handoff",
                         json={"action": "open", "note": "请确认支付验证码"})
    assert opened.status_code == 200
    card = opened.json()
    assert card["status"] == "PENDING"

    listed = client.get("/api/devices/handoff").json()["cards"]
    assert [c["card_id"] for c in listed] == [card["card_id"]]
    assert client.get("/api/devices/handoff?status=PENDING").json()["cards"]
    assert client.get("/api/devices/handoff?status=done").json()["cards"] == []

    bad = client.post("/api/devices/handoff", json={"action": "done"})
    assert bad.status_code == 422  # resolution needs card_id
    unknown = client.post("/api/devices/handoff",
                          json={"action": "done", "card_id": "handoff-9999"})
    assert unknown.status_code == 404
    assert client.post("/api/devices/handoff", json={"action": "nonsense"}).status_code == 422

    resolved = client.post("/api/devices/handoff",
                           json={"action": "done", "card_id": card["card_id"]})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "done"
    again = client.post("/api/devices/handoff",
                        json={"action": "give_up", "card_id": card["card_id"]})
    assert again.status_code == 409  # already terminal
    assert client.get("/api/devices/handoff?status=PENDING").json()["cards"] == []


def test_static_routes_do_not_shadow_device_id(client: TestClient) -> None:
    # /takeover, /activity and /handoff must resolve as routes, never as an id.
    for segment in ("takeover", "activity", "handoff"):
        assert client.get(f"/api/devices/{segment}").status_code == 200
    assert client.get("/api/devices/self").status_code == 200
