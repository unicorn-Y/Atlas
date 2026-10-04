from __future__ import annotations

from starlette.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.asr import filter_transcription
from atlas.server import app


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
    with TestClient(app).websocket_connect("/ws/asr") as websocket:
        websocket.send_bytes(b"\x00\x00")
        assert websocket.receive_json() == {"type": "partial", "text": "你好"}
        websocket.send_json({"type": "end"})
        assert websocket.receive_json() == {"type": "final", "text": "你好，Atlas"}
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
