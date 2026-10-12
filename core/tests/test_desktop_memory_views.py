from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from atlas.api.app_services import AppServices
from atlas.api.memory_changes_router import DeleteBody, delete_memory, get_facts, get_library
from atlas.memory.unified_facade import UnifiedMemoryFacade


async def test_desktop_reads_unified_records_and_never_old_memos(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy MemOS must not be read")

    monkeypatch.setattr("atlas.memory.memos_service.request", forbidden)
    facade = SimpleNamespace(enabled=True, list_records=AsyncMock(return_value={
        "items": [
            {"record_ref": "memory:user-1", "facet": "FACT", "lifecycle": "ACTIVE",
             "content": {"key": "preference", "value": "中文"}, "recorded_at": "2026-10-13T00:00:00Z"},
            {"record_ref": "experience:skill-1", "facet": "SKILL", "lifecycle": "ACTIVE",
             "content": {"title": "真实技能", "text": "步骤"}},
        ], "next_cursor": None,
    }))
    services = AppServices(unified_memory=facade)
    facts = await get_facts(services, history=True)
    assert facts["facts"][0]["id"] == "memory:user-1"
    assert facts["facts"][0]["text"] == "中文"
    assert facts["source"] == "unified-memory"
    assert facts["can_delete"] is False
    library = await get_library("skills", services)
    assert library["skills"][0]["name"] == "真实技能"
    with pytest.raises(HTTPException) as error:
        await delete_memory(DeleteBody(entity="user_facts", ids=["memory:user-1"]), services)
    assert error.value.status_code == 501


async def test_background_read_does_not_use_foreground_recall_budget():
    class Config:
        def get(self, key, default=None):
            return {"memory.unified.enabled": True,
                    "memory.v1.recall_timeout_seconds": 0.01,
                    "memory.unified.timeout_seconds": 1}.get(key, default)

    import asyncio

    async def slow():
        await asyncio.sleep(0.06)
        return {"items": []}

    facade = UnifiedMemoryFacade(Config())
    assert await facade._remote_read("/v1/unified/records", slow) == {"items": []}


def test_service_record_summary_validity_and_candidate_state_are_preserved():
    from atlas.memory.desktop_views import facts

    row = {"record_ref": "memory:candidate", "facet": "FACT", "lifecycle": "CANDIDATE",
           "content": {"title": "标题", "summary": "完整内容"},
           "valid_time": {"valid_to": "2026-10-14T00:00:00Z"}}
    fact = facts([row], True)["facts"][0]
    assert fact["text"] == "完整内容"
    assert fact["status"] == "candidate"
    assert fact["updatedAt"] is None
    assert fact["forgetAfter"] == 1791936000000


async def test_unavailable_unified_facade_never_falls_back_to_legacy():
    class Config:
        def get(self, key, default=None):
            return key == "memory.unified.enabled"

    with pytest.raises(HTTPException) as error:
        await get_facts(AppServices(config=Config()))
    assert error.value.status_code == 503


async def test_health_reports_runtime_memory_failure():
    from atlas.api.health_router import health

    facade = SimpleNamespace(enabled=True, service_state="ready", _last_unavailable="timeout")
    result = await health(AppServices(unified_memory=facade))
    assert result["status"] == "degraded"
    assert result["components"]["memoryos"] == "failed"


def test_missing_claude_key_is_detected_without_network(monkeypatch):
    from atlas.models import ModelManager

    manager = ModelManager.__new__(ModelManager)
    manager._models = [{"id": "claude", "provider": "anthropic"}]
    manager._api_key = ""
    manager.resolve_api_key = lambda provider: None
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "设置" in manager.missing_model_credentials("claude")
    manager._api_key = "configured-test-key"
    assert manager.missing_model_credentials("claude") is None


def test_foreign_memos_home_is_rejected(monkeypatch, tmp_path):
    import psutil
    from atlas.memory import memos_service

    connection = SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=18800), pid=123)
    monkeypatch.setattr(psutil, "net_connections", lambda **kwargs: [connection])
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(cmdline=lambda: ["node", "--home=" + str(tmp_path / "foreign")]))
    monkeypatch.setattr(memos_service, "MEMOS_HOME", tmp_path / "current")
    assert memos_service._owned_listener() is False
