"""Hermetic behavioral checks for U24 channel and device flows.

No real provider, Electron window, screenshot, or external service is used.
"""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
import atlas.api.device_router as device_router_module
from atlas.api.device_router import router as device_router
from atlas.channels.catalog import channels_with_registry
from atlas.channels.contract import MessageEvent
from atlas.channels.adapters import register_builtin_channels
from atlas.devices import DeviceRegistry
from atlas.gateway_service import GatewayBridge, SessionMapper


class FakeChannelManager:
    registry = {"telegram": object(), "slack": object()}
    configs = {"telegram": {"account": "primary"}, "slack": {"account": "primary"}}

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, dict[str, Any]]] = []

    def set_control_handler(self, _handler) -> None: ...

    def set_delivery_failure_handler(self, _handler) -> None: ...

    async def send(self, channel: str, chat_id: str, content: str, **kwargs: Any) -> str:
        self.sent.append((channel, chat_id, content, kwargs))
        return f"delivery-{len(self.sent)}"


def check_cross_channel_binding(root: Path) -> None:
    mapper = SessionMapper(root / "sessions.sqlite")
    key = "agent:main:telegram:primary:direct:customer-17"
    mapper.link(key, "conversation-existing", linked_by="local-user")
    assert mapper.get(key) == "conversation-existing"
    assert mapper.links()[0]["linked_by"] == "local-user"
    try:
        mapper.link(key, "conversation-other", linked_by="local-user")
    except ValueError:
        pass
    else:
        raise AssertionError("existing external identity was silently rebound")
    assert mapper.unlink(key) is True and mapper.get(key) is None
    mapper.close()


def check_human_takeover(root: Path) -> None:
    async def exercise() -> None:
        manager = FakeChannelManager()
        bridge = GatewayBridge(
            manager=manager, db_path=root / "handoff.sqlite",
            submit_run=lambda *_: asyncio.sleep(0), get_run=lambda _run_id: None,
            read_answer=lambda _conversation_id: asyncio.sleep(0, result=""),
            create_conversation=lambda *_: asyncio.sleep(0, result="conversation-1"),
        )
        origin = MessageEvent(channel="telegram", account="primary", event_id="origin-1",
                              chat_id="customer-17", sender_id="customer", text="/takeover 2001")
        key = bridge.build_session_key(origin, None)
        assert await bridge._handle_handoff_command(origin, key)
        handoff = bridge.sessions.handoffs()[0]
        assert handoff["state"] == "human" and handoff["human_chat"] == "2001"
        handoff_id = handoff["handoff_id"]
        human = MessageEvent(channel="telegram", account="primary", event_id="human-1",
                             chat_id="2001", sender_id="operator", text=f"/reply {handoff_id} shipped")
        assert await bridge._handle_handoff_command(human, bridge.build_session_key(human, None))
        assert any(row[1] == "customer-17" and row[2] == "shipped" for row in manager.sent)
        resume = MessageEvent(channel="telegram", account="primary", event_id="human-2",
                              chat_id="2001", sender_id="operator", text=f"/resume {handoff_id}")
        assert await bridge._handle_handoff_command(resume, bridge.build_session_key(resume, None))
        assert bridge.sessions.get_handoff(handoff_id)["state"] == "agent"
        assert [event["event"] for event in bridge.sessions.handoff_events(handoff_id)] == ["takeover", "agent"]
        bridge.sessions.close()

    asyncio.run(exercise())


def check_device_transfer(root: Path) -> None:
    payload = (b"U24 paired file transfer\n" * 1500) + b"end"
    digest = hashlib.sha256(payload).hexdigest()
    registry = DeviceRegistry(root / "devices.json")
    registry.register_self()
    registry.add("phone-24", "U24 test phone", trusted=True)
    app = FastAPI()
    app.state.services = AppServices(device_registry=registry)
    app.include_router(device_router)
    client = TestClient(app)
    assert client.put("/api/devices/phone-24/node-capabilities",
                      json={"capabilities": ["files.receive"]}).status_code == 200
    assert client.post("/api/devices/phone-24/node-capabilities/files.receive/approve").status_code == 200
    receiver_token = client.post("/api/devices/phone-24/file-transfer-credential").json()["token"]
    source_token = client.post("/api/devices/self/file-transfer-credential").json()["token"]
    source_auth = {"Authorization": f"Bearer {source_token}"}
    receiver_auth = {"Authorization": f"Bearer {receiver_token}"}
    rejected = client.post("/api/devices/file-transfers", json={
        "source_device_id": "self", "target_device_id": "phone-24", "filename": "payload.bin",
        "size": len(payload), "sha256": digest,
    })
    assert rejected.status_code == 403, "requests without a device credential should be refused"
    created = client.post("/api/devices/file-transfers", headers=source_auth, json={
        "source_device_id": "self", "target_device_id": "phone-24", "filename": "payload.bin",
        "size": len(payload), "sha256": digest,
    })
    assert created.status_code == 200, created.text
    transfer_id = created.json()["transfer"]["id"]
    assert client.post(f"/api/devices/file-transfers/{transfer_id}/accept?device_id=phone-24",
                       headers=source_auth).status_code == 403
    assert client.post(f"/api/devices/file-transfers/{transfer_id}/accept?device_id=phone-24",
                       headers=receiver_auth).status_code == 200
    first = payload[:1024]
    partial = client.put(f"/api/devices/file-transfers/{transfer_id}/chunks/0?device_id=self",
                         headers=source_auth, content=first)
    assert partial.status_code == 200 and partial.json()["progress"] > 0
    second = payload[len(first):]
    uploaded = client.put(f"/api/devices/file-transfers/{transfer_id}/chunks/{len(first)}?device_id=self",
                          headers=source_auth, content=second)
    assert uploaded.status_code == 200 and uploaded.json()["transfer"]["state"] == "ready"
    downloaded = client.get(f"/api/devices/file-transfers/{transfer_id}/download?device_id=phone-24",
                            headers=receiver_auth)
    assert downloaded.status_code == 200 and downloaded.content == payload
    listed = client.get("/api/devices/file-transfers?device_id=phone-24", headers=receiver_auth).json()["transfers"]
    assert listed[0]["state"] == "completed"
    assert [event["event"] for event in listed[0]["events"]][:3] == ["requested", "accepted", "progress"]

    store = device_router_module._transfer_store(registry)
    expiring = store.create("self", "phone-24", "old.bin", 1, hashlib.sha256(b"x").hexdigest())
    with store._db:
        store._db.execute("UPDATE transfers SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                          (expiring["id"],))
    assert store.get(expiring["id"])["state"] == "expired"
    assert store.events(expiring["id"])[-1]["event"] == "expired"
    store.close()
    device_router_module._transfer_stores.clear()


def check_channel_directory() -> None:
    registered: dict[str, object] = {}
    register_builtin_channels(lambda name, factory: registered.update({name: factory}))
    assert {"telegram", "email", "webhook"}.issubset(registered)
    rows = channels_with_registry(registered)
    by_id = {str(row["id"]): row for row in rows}
    assert by_id["feishu"]["inbound"] is True and "app_secret" in by_id["feishu"]["credentials"]
    assert by_id["matrix"]["status"] == "not_implemented"
    assert all("docs" in row and "setup" in row for row in rows)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="atlas-u24-") as temp:
        root = Path(temp)
        check_cross_channel_binding(root)
        check_human_takeover(root)
        check_device_transfer(root)
        check_channel_directory()
    print("U24 CHECK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
