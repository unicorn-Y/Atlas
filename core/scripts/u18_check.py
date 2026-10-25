"""Focused U18 runtime checks. Uses a temporary SQLite DB and local runtime controls; never launches Electron."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
from starlette.websockets import WebSocketDisconnect


def check_context_attribution() -> None:
    from atlas.kernel.loop import _context_breakdown

    messages = [
        {"role": "system", "content": "Atlas rules: be precise."},
        {"role": "user", "content": "Use the attached source."},
        {"role": "tool", "tool_name": "read_file", "content": "source contents"},
    ]
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    breakdown = _context_breakdown(messages, tools, used_tokens=180, context_limit=1000)
    attribution = breakdown["byte_attribution"]
    assert attribution["system_prompt"] == len(json.dumps([messages[0]], ensure_ascii=False, default=str).encode("utf-8"))
    assert attribution["tool_schema"] == len(json.dumps(tools, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    assert attribution["system_prompt_tokens_estimated"] > 0 and attribution["tool_schema_tokens_estimated"] > 0
    assert breakdown["context_used"] == 180 and breakdown["context_max"] == 1000


def check_limit_normalization() -> None:
    from atlas.kernel.loop import _normalized_limit_event
    from atlas.kernel.model_call import ModelCallError

    error = ModelCallError("slow down", category="rate_limit", status=429,
                           retryable=True, service="local fake provider", retry_after_seconds=12.5)
    limit = _normalized_limit_event(error)
    assert limit["category"] == "rate_limit" and limit["source"] == "provider_retry_after"
    assert limit["retry_after_seconds"] == 12.5
    from datetime import datetime
    reset = datetime.fromisoformat(limit["reset_at"])
    observed = datetime.fromisoformat(limit["observed_at"])
    assert 12.4 <= (reset - observed).total_seconds() <= 12.6
    missing = _normalized_limit_event(ModelCallError("quota exceeded", category="billing"))
    assert missing["reset_at"] is None and missing["source"] == "provider_error_without_reset"


async def check_background_controls() -> None:
    from atlas.api.runtime import RunState, RuntimeManager
    from atlas.api.runtime_ws_router import ws_chat

    class Socket:
        def __init__(self, messages: list[dict[str, str]]) -> None:
            self.messages = [json.dumps(item) for item in messages]

        async def receive_text(self) -> str:
            if self.messages:
                return self.messages.pop(0)
            raise WebSocketDisconnect(code=1000)

    class CaptureManager(RuntimeManager):
        def __init__(self, path: Path) -> None:
            super().__init__(path)
            self.sent: list[dict] = []

        async def connect(self, _socket, conn_id: str) -> None:
            self.connections[conn_id] = _socket

        async def send(self, _conn_id: str, envelope: dict) -> None:
            self.sent.append(envelope)

        def disconnect(self, conn_id: str) -> None:
            self.connections.pop(conn_id, None)

    with tempfile.TemporaryDirectory(prefix="atlas-u18-runtime-") as directory:
        manager = CaptureManager(Path(directory) / "runtime.sqlite")
        await manager.init()
        run = RunState("u18-background", "u18-conversation", "fake-model")
        manager.runs[run.run_id] = run
        await manager.persist_run(run)
        services = type("Services", (), {"runtime_mgr": manager})()
        ws = Socket([
            {"type": "run.background", "run_id": run.run_id},
            {"type": "run.pause", "run_id": run.run_id},
            {"type": "run.resume", "run_id": run.run_id},
            {"type": "run.foreground", "run_id": run.run_id},
        ])
        await ws_chat(ws, services)
        assert run.background is False and run.status == "running"
        events = [item for item in manager.sent if item.get("event") == "run.background"]
        assert [item["data"]["background"] for item in events] == [True, False]
        assert any(item.get("event") == "run.paused" for item in manager.sent)
        assert any(item.get("event") == "run.resumed" for item in manager.sent)
        row = await (await manager._db.execute("SELECT resume_context FROM runtime_runs WHERE run_id=?", (run.run_id,))).fetchone()
        assert row is not None and json.loads(row[0]).get("background") is None
        await manager.close()


def check_frontend_surface() -> None:
    app = (ROOT / "frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    sidebar = (ROOT / "frontend/src/renderer/shell/Sidebar.tsx").read_text(encoding="utf-8")
    inspector = (ROOT / "frontend/src/renderer/shell/Inspector.tsx").read_text(encoding="utf-8")
    usage = (ROOT / "frontend/src/renderer/components/TokenUsage.tsx").read_text(encoding="utf-8")
    assert "label: '/context'" in app and "label: '/status'" in app and "label: '/prompt-size'" in app and "label: '/new'" in app
    assert "label: '/bg'" in app and "onPauseRun" in sidebar and "onStopRun" in sidebar and "后台 ·" in sidebar
    assert "本轮提示词来源" in inspector and "ContextGrid" in usage
    assert "等待 {rateRetrySeconds} 秒后重试" in app and "换模型" in app and "打开 {usagePage.label}" in app


async def main() -> None:
    check_context_attribution()
    check_limit_normalization()
    await check_background_controls()
    check_frontend_surface()
    print("U18 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
