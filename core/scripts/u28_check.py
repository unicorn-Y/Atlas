"""U28 end-to-end checks for the new preview, canvas, and device pairing flows."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))


def check_device_pairing() -> None:
    from atlas.api.app_services import AppServices
    import atlas.api.device_router as device_router
    from atlas.api.device_router import router
    from atlas.devices import DeviceRegistry

    with tempfile.TemporaryDirectory(prefix="atlas-u28-pairing-") as folder:
        registry = DeviceRegistry(Path(folder) / "devices.json")
        registry.register_self()
        app = FastAPI()
        app.state.services = AppServices(device_registry=registry)
        app.include_router(router)
        with TestClient(app) as client:
            challenge = client.post("/api/devices/pairing/challenge", json={
                "ttl_seconds": 120, "api_base_url": "http://127.0.0.1:8765",
            })
            assert challenge.status_code == 200, challenge.text
            data = challenge.json()
            assert "pairing/enroll?challenge_id=" in data["qr_payload"]
            enrollment = client.get(f"/api/devices/pairing/enroll?challenge_id={data['challenge_id']}")
            assert enrollment.status_code == 200 and "发送配对申请" in enrollment.text
            assert "Content-Security-Policy" in enrollment.headers
            claimed = client.post("/api/devices/pairing/claim", json={
                "challenge_id": data["challenge_id"], "code": data["code"],
                "device_id": "u28-phone", "display_name": "U28 phone", "os": "browser",
            })
            assert claimed.status_code == 200, claimed.text
            request = claimed.json()
            approved = client.post(f"/api/devices/pairing/requests/{request['request_id']}",
                                   json={"action": "approve"})
            assert approved.status_code == 200, approved.text
            poll_url = f"/api/devices/pairing/claim/{request['request_id']}?proof={request['proof']}"
            token = client.get(poll_url).json()["credential"]
            assert token and client.get(poll_url).json().get("credential") is None
            admin = client.post("/api/devices/commands?device_id=u28-phone",
                                json={"prompt": "U28 command"})
            assert admin.status_code == 200, admin.text
            command = admin.json()
            auth = {"Authorization": f"Bearer {token}"}
            delivered = client.get("/api/devices/node/u28-phone/commands", headers=auth)
            assert delivered.status_code == 200 and delivered.json()["commands"][0]["id"] == command["id"]
            returned = client.post(f"/api/devices/node/u28-phone/commands/{command['id']}/result",
                                   headers=auth, json={"result": "U28 result"})
            assert returned.status_code == 200, returned.text
            assert client.get("/api/devices/u28-phone/commands").json()["commands"][0]["result"] == "U28 result"
            assert client.post("/api/devices/u28-phone/pairing/revoke").status_code == 200
            assert client.get("/api/devices/node/u28-phone/commands", headers=auth).status_code == 403
        key = str(registry.path.resolve())
        for stores in (device_router._pairing_stores, device_router._transfer_stores):
            store = stores.pop(key, None)
            if store is not None and hasattr(store, "close"):
                store.close()


def check_real_browser() -> None:
    script = ROOT / "core" / "scripts" / "u28_browser_check.cjs"
    result = subprocess.run(["node", str(script)], cwd=ROOT, text=True,
                            encoding="utf-8", errors="replace", capture_output=True,
                            timeout=90, check=False)
    if result.returncode:
        raise AssertionError(f"Chrome UI scenario failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
    print(result.stdout.strip())


if __name__ == "__main__":
    check_device_pairing()
    print("DEVICE PAIRING ROUTE PASS")
    check_real_browser()
    print("U28 CHECK PASS")
