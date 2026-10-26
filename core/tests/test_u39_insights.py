from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from atlas.api.app_services import AppServices
from atlas.api.conversations_router import router as conversations_router
from atlas.api.runtime import RunState, RuntimeManager
from atlas.api.u4_router import router as u4_router
from atlas.api.usage_router import router as usage_router
from atlas.engine.session_sync import append_session_message
from atlas.usage import UsageLedger


class Memory:
    async def list_conversations(self, limit=None):
        return []

    async def get_conversation_messages(self, conversation_id, limit=100):
        return []

    async def get_conversation(self, conversation_id):
        return {"id": conversation_id, "title": "Test session"} if conversation_id == "conversation-1" else None


@pytest.mark.asyncio
async def test_insights_report_daily_trends_model_filter_and_missing_price(tmp_path, monkeypatch):
    import atlas.config

    data_root = tmp_path / "atlas-data"
    monkeypatch.setattr(atlas.config, "DATA_ROOT", data_root)
    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    await ledger.init()
    today = datetime.now(UTC).date().isoformat()
    common = dict(conversation_id="conversation-1", subtask_id=None,
                  started_at=f"{today}T12:00:00+00:00",
                  usage={"input_tokens": 100, "output_tokens": 20})
    await ledger.record(run_id="run-priced", model="model-priced",
                        price={"input": 1, "output": 2, "cached_input": 1}, **common)
    await ledger.record(run_id="run-unpriced", model="model-unpriced", **common)
    app = FastAPI()
    app.state.services = AppServices(memory=Memory(), usage_ledger=ledger)
    app.include_router(u4_router)
    app.include_router(usage_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        filtered = await client.get("/api/u4/insights?days=7&model=model-priced")
        complete = await client.get("/api/u4/insights?days=7")
        usage = await client.get(f"/api/usage?group_by=day&from={today}&model=model-priced")
    assert filtered.status_code == complete.status_code == usage.status_code == 200
    assert len(filtered.json()["trends"]) == 7
    assert filtered.json()["trends"][-1]["runs"] == 1
    assert filtered.json()["trends"][-1]["est_cost"] == 0.00014
    assert filtered.json()["model"] == "model-priced"
    assert "UTC" in filtered.json()["markdown"] and "每日调用与估算费用趋势" in filtered.json()["markdown"]
    assert complete.json()["missing_price_records"] == 1
    assert "缺价（1 条）" in complete.json()["markdown"]
    assert usage.json()["totals"]["runs"] == 1 and usage.json()["models"] == ["model-priced", "model-unpriced"]
    await ledger.close()


@pytest.mark.asyncio
async def test_session_stats_show_message_and_runtime_run_counts(tmp_path, monkeypatch):
    import atlas.config
    data_root = tmp_path / "atlas-data"
    (data_root / "engine").mkdir(parents=True)
    monkeypatch.setattr(atlas.config, "DATA_ROOT", data_root)
    append_session_message(data_root / "engine", "conversation-1", "user", "Question")
    append_session_message(data_root / "engine", "conversation-1", "assistant", "Answer")
    runtime = RuntimeManager()
    runtime.runs = {
        "run-1": RunState("run-1", "conversation-1", "model-a"),
        "run-2": RunState("run-2", "conversation-1", "model-a"),
        "other": RunState("other", "conversation-2", "model-a"),
    }
    app = FastAPI()
    app.state.services = AppServices(memory=Memory(), runtime_mgr=runtime)
    app.include_router(conversations_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/conversations/conversation-1/stats")
    assert response.status_code == 200
    assert response.json()["message_count"] == 2
    assert response.json()["runs"] == 2
