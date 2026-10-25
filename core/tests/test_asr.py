from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.asr import filter_transcription
from atlas.server import app


@pytest.fixture(autouse=True)
def restore_app_services():
    """Snapshot ``app.state.services`` around every test.

    The module-level app's lifespan repopulates the shared container in place
    and its shutdown never restores the slots, so any slot a test touches must
    be put back or the leak spreads to every later test in this process.
    """
    from dataclasses import fields

    from atlas.api.app_services import AppServices

    services = app.state.services
    snapshot = {f.name: getattr(services, f.name) for f in fields(AppServices)}
    runtime_manager = services.runtime_mgr
    yield
    for field in fields(AppServices):
        setattr(services, field.name, snapshot[field.name])
    # create_app bound the container to its runtime manager; the lifespan's
    # shutdown path clears that back-reference, so restore the import-time one.
    runtime_manager.services = services


def test_transcription_filter_drops_silence_and_tiny_fragments() -> None:
    assert filter_transcription("sil") == ""
    assert filter_transcription("啊") == ""
    assert filter_transcription("你好") == "你好"


def test_asr_websocket_segments_partial_final_and_end(monkeypatch) -> None:
    class MockASR:
        def status(self):
            return {"ready": True}

        def process_frame(self, data: bytes, *, final: bool = False):
            if final:
                return [], ["你好，Atlas"]
            return (["你好"] if data else []), []

    monkeypatch.setattr(server.app.state.services, "asr_manager", MockASR())
    with TestClient(app, client=("127.0.0.1", 50000)).websocket_connect("/ws/asr") as websocket:
        websocket.send_bytes(b"\x00\x00")
        assert websocket.receive_json() == {"type": "partial", "text": "你好"}
        websocket.send_json({"type": "end"})
        assert websocket.receive_json() == {"type": "final", "text": "你好，Atlas"}
        assert websocket.receive_json() == {"type": "ended"}


def test_asr_websocket_prepares_model_on_first_use(monkeypatch) -> None:
    class MockASR:
        ready = False

        def status(self):
            return {"ready": self.ready, "progress": 1.0 if self.ready else 0.0}

        async def download(self):
            self.ready = True

        def process_frame(self, data: bytes, *, final: bool = False):
            return [], []

    monkeypatch.setattr(server.app.state.services, "asr_manager", MockASR())
    with TestClient(app, client=("127.0.0.1", 50000)).websocket_connect("/ws/asr") as websocket:
        assert websocket.receive_json()["type"] == "preparing"
        updates = []
        while True:
            message = websocket.receive_json()
            updates.append(message["type"])
            if message["type"] == "ready":
                break
        assert set(updates) <= {"progress", "ready"}
        websocket.send_json({"type": "end"})
        assert websocket.receive_json() == {"type": "ended"}


async def test_asr_status_endpoint_uses_mock(monkeypatch) -> None:
    class MockASR:
        def status(self):
            return {"ready": False, "model": None, "downloading": False,
                    "progress": 0, "detail": "not installed"}

    monkeypatch.setattr(server.app.state.services, "asr_manager", MockASR())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/api/asr/status")
    assert result.json()["detail"] == "not installed"
