from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api import channel_router
from atlas.origin_guard import OriginGuard


class FakeProcess:
    def __init__(self, lines: list[bytes], returncode: int = 0) -> None:
        self.stdout = self
        self.lines = list(lines)
        self.returncode = None
        self.final_returncode = returncode
        self.killed = False

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        return self.lines.pop(0) if self.lines else b""

    async def wait(self) -> int:
        self.returncode = self.final_returncode
        return self.final_returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(OriginGuard)
    app.include_router(channel_router.router)
    return TestClient(app, client=("127.0.0.1", 50000))


def test_channel_dependency_install_uses_atlas_python_and_reports_progress(monkeypatch) -> None:
    process = FakeProcess(["Collecting lark-oapi\n".encode(), "安装完成：飞书 SDK\n".encode()])
    calls = []

    async def create(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(channel_router.sys, "executable", "C:/atlas/.venv/Scripts/python.exe")
    monkeypatch.setattr(channel_router.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(channel_router, "_install_state", {"status": "idle", "channel": None, "message": ""})
    with client() as api:
        response = api.post("/api/channels/dependencies/feishu/install")
        assert response.status_code == 200
        assert response.json()["python"] == "C:/atlas/.venv/Scripts/python.exe"
        assert "lark-oapi" in response.json()["output"]
        assert calls[0][0][:4] == ("C:/atlas/.venv/Scripts/python.exe", "-m", "pip", "install")
        status = api.get("/api/channels/dependencies/status").json()
        assert status["status"] == "complete" and status["channel"] == "feishu"
        assert "安装完成" in status["message"]


def test_channel_dependency_install_rejects_unknown_channel(monkeypatch) -> None:
    monkeypatch.setattr(channel_router, "_install_state", {"status": "idle", "channel": None, "message": ""})
    with client() as api:
        response = api.post("/api/channels/dependencies/not-a-channel/install")
        assert response.status_code == 404

