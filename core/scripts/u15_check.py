"""U15 integration scenarios for duplex voice, live CUA frames and cross-session triage.

Run with ``ATLAS_ROOT`` pointing at a disposable Atlas data root.
"""
from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def check_voice_stream_and_recovery() -> None:
    from atlas.api.app_services import AppServices
    from atlas.api.application import create_app

    class FakeAsr:
        def status(self):
            return {"ready": True}

        def process_frame(self, data: bytes, final: bool = False):
            if data:
                return (["partial words"], ["first turn"])
            return ([], ["last words"] if final else [])

    @asynccontextmanager
    async def lifespan(_app):
        yield

    app = create_app(lifespan=lifespan, services=AppServices(asr_manager=FakeAsr()))
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        with client.websocket_connect("/ws/asr", headers={"origin": "http://localhost:5173"}) as socket:
            socket.send_bytes(b"\x00\x00")
            assert socket.receive_json() == {"type": "partial", "text": "partial words"}
            assert socket.receive_json() == {"type": "final", "text": "first turn"}
            # A final utterance does not end the duplex recognition session.
            socket.send_bytes(b"\x01\x00")
            assert socket.receive_json()["type"] == "partial"
            assert socket.receive_json()["type"] == "final"
            socket.send_text(json.dumps({"type": "end"}))
            assert socket.receive_json() == {"type": "final", "text": "last words"}
            assert socket.receive_json() == {"type": "ended"}
    source = Path("frontend/src/renderer/components/VoiceOverlay.tsx").read_text(encoding="utf-8")
    assert "echoCancellation: true" in source and "speechFramesRef.current >= 3" in source
    assert "window.speechSynthesis?.cancel()" in source and "onSpeechVoiceChange" in source
    assert "转为文字" in source and "failureRef.current < 2" in source
    print("U15 voice: persistent ASR socket accepts consecutive utterances, end flushes; interruption, echo suppression, voice preference and recovery UI PASS")


async def check_triage_api() -> None:
    from atlas.api.app_services import AppServices
    from atlas.api.application import create_app
    from atlas.api import triage_router

    class Memory:
        async def list_conversations(self, limit=None):
            return [
                {"id": "waiting-session", "title": "等待输入"},
                {"id": "failed-session", "title": "失败运行"},
                {"id": "idle-session", "title": "待办"},
            ]

    class Activity:
        async def conversation_activity(self, limit=500):
            return {"items": [
                {"conversation_id": "waiting-session", "status": "waiting", "waiting_for": "approval"},
                {"conversation_id": "failed-session", "status": "failed"},
            ]}

    @asynccontextmanager
    async def lifespan(_app):
        yield

    with tempfile.TemporaryDirectory(prefix="atlas-u15-triage-") as temp:
        with patch.object(triage_router, "_BOARD_PATH", Path(temp) / "board.json"):
            app = create_app(lifespan=lifespan, services=AppServices(memory=Memory(), runtime_mgr=Activity()))
            with TestClient(app, client=("127.0.0.1", 1234)) as client:
                result = client.get("/api/triage").json()
                by_id = {item["conversation_id"]: item for item in result["items"]}
                assert by_id["waiting-session"]["attention"] and by_id["waiting-session"]["waiting_for"] == "approval"
                assert by_id["failed-session"]["attention"] and not by_id["idle-session"]["attention"]
                updated = client.put("/api/triage", json={"items": [
                    {"conversation_id": "waiting-session", "column": "doing", "priority": 1, "position": 0},
                    {"conversation_id": "failed-session", "column": "todo", "priority": 2, "position": 1},
                ]})
                assert updated.status_code == 200 and updated.json()["saved"] == 2
                persisted = {item["conversation_id"]: item for item in client.get("/api/triage").json()["items"]}
                assert persisted["waiting-session"]["column"] == "doing" and persisted["waiting-session"]["priority"] == 1
                assert persisted["failed-session"]["column"] == "todo"
    print("U15 triage: waiting/failed cross-session inbox, priority and board columns persist through API PASS")


async def check_live_computer_frame() -> None:
    from atlas.tools.x2.computer import X2ComputerRuntime
    from atlas.tools.x2.context import X2Context

    received: list[tuple[str, dict[str, object]]] = []

    async def emit(name: str, data: dict[str, object]) -> None:
        received.append((name, data))

    runtime = X2ComputerRuntime(backend=None)
    context = X2Context(run_id="u15-cua-run", session_id="u15-session", emit=emit)
    fake_image = "data:image/jpeg;base64," + base64.b64encode(b"synthetic-frame").decode("ascii")
    await runtime._emit_step(context, "computer_observe", {"data": {"_image_data_url": fake_image}, "is_error": False})
    assert received[0][0] == "computer.step"
    assert received[1][0] == "computer.frame" and received[1][1]["run_id"] == "u15-cua-run"
    source = Path("frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    composer = Path("frontend/src/renderer/components/x2/ComputerLivePreview.tsx").read_text(encoding="utf-8")
    assert "tool_deny" in source and "computer_*" in source and "computerReady" in source
    assert "暂停刷新" in composer and "继续刷新" in composer
    print("U15 computer use: real run event bridge emits a bounded live frame alongside its step; preview pause and run tool gate PASS")


def check_frontend_wiring() -> None:
    source = Path("frontend/src/renderer/shell/Sidebar.tsx").read_text(encoding="utf-8")
    board = Path("frontend/src/renderer/components/TriageBoardDialog.tsx").read_text(encoding="utf-8")
    assert "/api/triage" in board and "onOpenConversation" in board and "onDragStart" in board
    assert "优先级" in board and "分诊队列" in board and "待处理" in board and "手动顺序" in board
    assert "跨会话收件箱与工作板" in source
    print("U15 frontend: triage entry, drag reorder, priority assignment and session restore bindings PASS")


async def main() -> None:
    check_voice_stream_and_recovery()
    await check_triage_api()
    await check_live_computer_frame()
    check_frontend_wiring()


if __name__ == "__main__":
    asyncio.run(main())
    print("U15 CHECK PASS")
