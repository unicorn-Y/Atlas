from __future__ import annotations

import re
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from click.testing import CliRunner

from atlas.api.app_services import AppServices
from atlas.api.dashboard_router import router
from atlas.dashboard_access import create_access
from atlas.origin_guard import OriginGuard


class Memory:
    async def list_conversations(self, limit=100):
        return [{"id": "c1", "title": "Local session", "preview": "hello", "workspace": "C:/repo"}]


class Channels:
    def status(self):
        return {"channels": [{"name": "telegram", "enabled": True, "running": True}]}


class Devices:
    def list_devices(self):
        return [{"device_id": "phone", "display_name": "Phone", "trusted": True, "credential": "must-not-leak"}]


def dashboard_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(OriginGuard)
    app.include_router(router)
    app.state.services = AppServices(
        runtime_mgr=SimpleNamespace(runs={}),
        startup=SimpleNamespace(snapshot=lambda: {"api": "ready"}),
        memory=Memory(), channel_manager=Channels(), device_registry=Devices(),
    )
    return app


def test_dashboard_is_loopback_enabled_and_read_only(monkeypatch, tmp_path):
    from atlas import dashboard_access

    monkeypatch.setattr(dashboard_access, "control_path", lambda: tmp_path / "dashboard.json")
    token, _ = create_access(port=8765, pid=42, owns_server=False)
    client = TestClient(dashboard_app(), client=("127.0.0.1", 50000))

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert '<base href="/dashboard/">' in page.text
    asset = re.search(r'src="\./assets/([^"]+)"', page.text)
    if asset:
        javascript = client.get(f"/dashboard/assets/{asset.group(1)}")
        assert javascript.status_code == 200 and "atlas.dashboard.token" in javascript.text
    else:
        assert "运行状态" in page.text and "会话" in page.text
    assert client.get("/api/dashboard/status").status_code == 401
    headers = {"X-Atlas-Dashboard-Token": token}
    assert client.get("/api/dashboard/status", headers=headers).json() == {
        "status": "ready", "components": {"api": "ready"}, "active_runs": 0,
        "waiting_runs": 0, "channels": 1, "devices": 1,
    }
    assert client.get("/api/dashboard/sessions", headers=headers).json()[0]["id"] == "c1"
    assert client.get("/api/dashboard/channels", headers=headers).json()[0]["name"] == "telegram"
    device = client.get("/api/dashboard/devices", headers=headers).json()[0]
    assert device["device_id"] == "phone"
    assert "credential" not in device


def test_dashboard_token_is_revocable(monkeypatch, tmp_path):
    from atlas import dashboard_access

    monkeypatch.setattr(dashboard_access, "control_path", lambda: tmp_path / "dashboard.json")
    token, _ = create_access(port=8765, pid=42, owns_server=False)
    assert dashboard_access.token_valid(token)
    dashboard_access.revoke_access()
    assert not dashboard_access.token_valid(token)


def test_dashboard_cli_attaches_to_existing_server_and_does_not_stop_it(monkeypatch, tmp_path):
    from atlas import dashboard_access
    from atlas.cli import main

    monkeypatch.setattr(dashboard_access, "control_path", lambda: tmp_path / "dashboard.json")
    def request(method, path, *_args, **_kwargs):
        if method == "POST":
            client = TestClient(dashboard_app(), client=("127.0.0.1", 50000), base_url="http://127.0.0.1:18765")
            response = client.post(path)
            return SimpleNamespace(is_success=response.is_success, status_code=response.status_code, json=response.json)
        return SimpleNamespace(is_success=True)
    monkeypatch.setattr("atlas.cli._daemon_request", request)
    runner = CliRunner()
    started = runner.invoke(main, ["dashboard", "start", "--port", "18765"])
    assert started.exit_code == 0, started.output
    assert "http://127.0.0.1:18765/dashboard#" in started.output
    assert "PID= " not in started.output
    token_record = (tmp_path / "dashboard.json").read_text(encoding="utf-8")
    assert "token_hash" in token_record
    bearer = started.output.split("/dashboard#", 1)[1].split()[0]
    assert bearer not in token_record
    status = runner.invoke(main, ["dashboard", "status"])
    assert status.exit_code == 0 and "loopback only" in status.output
    stopped = runner.invoke(main, ["dashboard", "stop"])
    assert stopped.exit_code == 0, stopped.output
    assert not (tmp_path / "dashboard.json").exists()


def test_running_backend_creates_dashboard_token_in_its_data_root(monkeypatch, tmp_path):
    from atlas import dashboard_access

    monkeypatch.setattr(dashboard_access, "control_path", lambda: tmp_path / "backend" / "dashboard.json")
    client = TestClient(dashboard_app(), client=("127.0.0.1", 50000), base_url="http://127.0.0.1:18765")
    created = client.post("/api/dashboard/access")
    assert created.status_code == 200
    access = created.json()
    assert access["url"].startswith("http://127.0.0.1:18765/dashboard#")
    record = json.loads((tmp_path / "backend" / "dashboard.json").read_text(encoding="utf-8"))
    assert access["pid"] == record["pid"]
    assert access["url"].rsplit("#", 1)[1] not in json.dumps(record)
    headers = {"x-atlas-dashboard-token": access["url"].rsplit("#", 1)[1]}
    assert client.get("/api/dashboard/status", headers=headers).json()["status"] == "ready"
    assert client.post("/api/dashboard/access", headers={"Origin": "https://evil.example"}).status_code == 200
    remote = TestClient(dashboard_app(), client=("192.0.2.5", 50000), base_url="http://127.0.0.1:18765")
    assert remote.post("/api/dashboard/access").status_code == 403


def test_dashboard_cli_starts_and_stops_only_its_loopback_server(monkeypatch, tmp_path):
    import httpx

    from atlas import dashboard_access
    from atlas.cli import main

    monkeypatch.setattr(dashboard_access, "control_path", lambda: tmp_path / "dashboard.json")
    invocations: list[tuple[str, str, int]] = []
    stopped = False

    def request(method, path, port, **kwargs):
        nonlocal stopped
        invocations.append((method, path, port))
        if method == "GET" and (len(invocations) == 1 or stopped):
            raise httpx.ConnectError("offline")
        if method == "POST" and path == "/api/runtime/shutdown":
            stopped = True
            return SimpleNamespace(is_success=True)
        if method == "POST":
            token, info = dashboard_access.create_access(port=port, pid=4321, owns_server=True,
                                                         shutdown_token="test-shutdown")
            return SimpleNamespace(is_success=True, json=lambda: {
                "url": f"http://127.0.0.1:{port}/dashboard#{token}", "pid": info["pid"],
                "expires_at": info["expires_at"],
            })
        return SimpleNamespace(is_success=True)

    class Process:
        pid = 4321
        def poll(self):
            return None

    spawn: list[list[str]] = []
    monkeypatch.setattr("atlas.cli._daemon_request", request)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kwargs: (spawn.append(args) or Process()))
    runner = CliRunner()
    started = runner.invoke(main, ["dashboard", "start", "--port", "19765"])
    assert started.exit_code == 0, started.output
    assert spawn and spawn[0][-2:] == ["--host", "127.0.0.1"]
    stopped = runner.invoke(main, ["dashboard", "stop"])
    assert stopped.exit_code == 0, stopped.output
    assert ("POST", "/api/runtime/shutdown", 19765) in invocations
    assert not (tmp_path / "dashboard.json").exists()
