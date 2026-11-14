"""Durable session timing totals and API entry point integration."""

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from atlas.api.app_services import AppServices
from atlas.api.conversations_router import router
from atlas.session_stats import session_timing_stats

pytestmark = pytest.mark.unit


def _run(root, run_id, session_id):
    root.mkdir(parents=True, exist_ok=True)
    events = [
        {"event": "run_start", "session_id": session_id},
        {"event": "model_request", "input_tokens": 1, "attempt": 1},
        {"event": "model_request", "purpose": "conversation", "duration_ms": 120,
         "first_token_ms": 20, "output_tokens": 10, "attempt": 1},
        {"event": "tool_start", "tool_call_id": "tool-a", "name": "read"},
        {"event": "tool_end", "tool_call_id": "tool-a", "duration_ms": 30},
        {"event": "tool_result", "tool_call_id": "tool-a", "is_error": False},
        {"event": "step_end", "reason": "completed"},
        {"event": "run_end", "status": "completed"},
    ]
    (root / f"{run_id}.jsonl").write_text("".join(
        json.dumps({**item, "run_id": run_id, "timestamp": "2026-11-14T01:00:00Z"}) + "\n"
        for item in events
    ), encoding="utf-8")


def test_timing_projection_is_durable_filtered_and_does_not_double_count(tmp_path):
    _run(tmp_path, "one", "session-a")
    _run(tmp_path, "two", "session-a")
    _run(tmp_path, "other", "session-b")
    assert session_timing_stats("session-a", tmp_path) == {
        "turns": 2, "steps": 2, "llmMs": 240, "toolMs": 60,
        "ttftMs": 40, "ttftSteps": 2, "decodeMs": 200, "decodeTokens": 20,
    }
    assert all(value == 0 for value in session_timing_stats("missing", tmp_path).values())


def test_run_info_session_id_is_captured_when_run_start_is_not_first_line(tmp_path):
    """Live run logs open with api_timing/request envelopes; the owning session
    must still be found so the timing projection can filter by session."""
    from atlas.run_replay import list_runs

    root = tmp_path / "runs"
    root.mkdir(parents=True)
    events = [
        {"event": "api_timing", "stage": "request_received"},
        {"event": "run_status", "state": "queued"},
        {"event": "run_start", "session_id": "session-late", "model": "deepseek-v4.1-flash"},
        {"event": "model_request", "purpose": "conversation", "duration_ms": 500,
         "first_token_ms": 100, "output_tokens": 8, "attempt": 1},
        {"event": "step_end", "reason": "completed"},
        {"event": "run_end", "status": "completed"},
    ]
    (root / "late.jsonl").write_text("".join(
        json.dumps({**item, "run_id": "late", "timestamp": "2026-11-14T02:00:00Z"}) + "\n"
        for item in events
    ), encoding="utf-8")
    infos = list_runs(limit=None, runs_dir=root)
    assert [info.session_id for info in infos] == ["session-late"]
    assert session_timing_stats("session-late", root)["llmMs"] == 500


@pytest.mark.asyncio
async def test_stats_api_serves_projection(tmp_path, monkeypatch):
    import atlas.config
    import atlas.logs
    from atlas.engine.session_sync import append_session_message

    monkeypatch.setattr(atlas.config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(atlas.logs, "LOG_DIR", tmp_path / "logs")
    append_session_message(tmp_path / "engine", "session-a", "user", "question")
    _run(tmp_path / "data" / "logs" / "runs", "one", "session-a")

    class Memory:
        async def get_conversation(self, session_id):
            return {"id": session_id}

    app = FastAPI()
    app.state.services = AppServices(memory=Memory())
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/conversations/session-a/stats")
    assert response.status_code == 200
    assert response.json()["sessionStats"]["llmMs"] == 120
    assert response.json()["message_count"] == 1
