from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import atlas.api.device_router as device_router
from atlas.api.app_services import AppServices
from atlas.devices import DeviceRegistry
from atlas.devices.takeover import TakeoverStateMachine
from atlas.origin_guard import OriginGuard
from atlas.tools.nodes import dispatch_node_command


@pytest.fixture()
def paired_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ATLAS_API_TOKEN", "u41-test-local-atlas-token")
    registry = DeviceRegistry(tmp_path / "devices.json")
    registry.register_self()
    registry.add("phone-1", "Phone", kind="ingress", os="Android", trusted=True)
    registry.set_presence("phone-1", activity="paired")
    monkeypatch.setattr(device_router, "get_registry", lambda: registry)
    app = FastAPI()
    app.state.services = AppServices(device_registry=registry, takeover=TakeoverStateMachine(device_id="self"))
    app.include_router(device_router.router)
    app.add_middleware(OriginGuard)
    client = TestClient(app)
    token = device_router._pairing_store(registry).rotate_credential("phone-1")
    client.headers.update({"Authorization": f"Bearer {token}", "X-Atlas-Api-Token": "u41-test-local-atlas-token"})
    declaration = client.put("/api/devices/node/phone-1/capabilities", json={
        "capabilities": ["device.status", "notifications.send", "camera.capture", "location.read", "media.control"],
    }, headers={"Origin": "http://localhost:8765", "Sec-Fetch-Site": "same-origin"})
    assert declaration.status_code == 200
    # Approval is a separate Atlas-side action; a paired declaration alone is not executable.
    for capability in declaration.json()["declared"]:
        approved = client.post(f"/api/devices/phone-1/node-capabilities/{capability}/approve")
        assert approved.status_code == 200
    yield client
    client.close()


@pytest.mark.asyncio
async def test_agent_node_status_rpc_runs_through_authenticated_inbox(paired_client: TestClient) -> None:
    task = asyncio.create_task(dispatch_node_command("phone-1", "status", {}, timeout=8))
    command = None
    for _ in range(30):
        response = await asyncio.to_thread(paired_client.get, "/api/devices/node/phone-1/commands")
        assert response.status_code == 200
        if response.json()["commands"]:
            command = response.json()["commands"][0]
            break
        await asyncio.sleep(0.05)
    assert command is not None
    assert json.loads(command["prompt"]) == {"kind": "status", "arguments": {}}
    result = {"ok": True, "online": True, "platform": "test-device"}
    completed = await asyncio.to_thread(
        paired_client.post,
        f"/api/devices/node/phone-1/commands/{command['id']}/result",
        json={"result": json.dumps(result)},
    )
    assert completed.status_code == 200
    assert await task == result

    queued = paired_client.post("/api/devices/commands?device_id=phone-1", json={
        "kind": "notification", "arguments": {"title": "Test", "message": "Node RPC"},
    })
    assert queued.status_code == 200
    assert json.loads(queued.json()["prompt"]) == {
        "kind": "notification", "arguments": {"title": "Test", "message": "Node RPC"},
    }


@pytest.mark.asyncio
async def test_enrollment_page_loads_browser_executor_and_declares_native_capabilities(paired_client: TestClient) -> None:
    response = await device_router.pairing_enrollment_page("a" * 32)
    assert "/api/devices/node-client.js" in response.body.decode()
    assert "atlasNodeCapabilities" in response.body.decode()
    script_response = paired_client.get("/api/devices/node-client.js", headers={
        "Origin": "http://localhost:8765", "Sec-Fetch-Site": "same-origin",
    })
    assert script_response.status_code == 200
    assert "atlas-node-command" in script_response.text
    script = Path(device_router.__file__).parents[1] / "devices" / "node_client.js"
    source = script.read_text(encoding="utf-8")
    for feature in ("camera.capture", "location.read", "notifications.send", "media.control", "getUserMedia", "getCurrentPosition"):
        assert feature in source
    assert "在本机运行" in source
