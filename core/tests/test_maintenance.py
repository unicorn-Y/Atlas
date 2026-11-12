from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from atlas import diagnostic_store
from atlas.api import maintenance_router
from atlas.engine.kernel.model_call import complete_stream


def test_model_trace_and_audit_are_durable_and_filterable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostic_store, "DATA_ROOT", tmp_path)
    diagnostic_store.record_model_request(
        request_id="req-123", run_id="run-1", model="model-a", provider="provider-a",
        endpoint="https://api.example.test", params={"message_count": 2, "stream": True},
        started_at="2026-10-25T12:00:00+00:00",
    )
    diagnostic_store.finish_model_request("req-123", duration_ms=231, status="error",
                                          error_category="timeout", error_detail="stream stalled")
    diagnostic_store.record_audit_event("test", "remove-cache", details={"count": 4})
    assert diagnostic_store.list_model_requests("req-123")[0]["duration_ms"] == 231
    assert diagnostic_store.list_model_requests("model-a")[0]["error_category"] == "timeout"
    assert diagnostic_store.list_audit_events("remove-cache")[0]["details"] == {"count": 4}
    assert (tmp_path / "data" / "diagnostics.sqlite3").is_file()


@pytest.mark.asyncio
async def test_successful_model_request_creates_trace_without_prompt_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostic_store, "DATA_ROOT", tmp_path)
    route = SimpleNamespace(provider="test-provider", wire_model="wire-model", model="model-a",
                            key="never-store-this", base_url="https://provider.example/v1?token=secret",
                            api_mode="chat_completions", model_id="model-a", capabilities={})
    agent = SimpleNamespace(_model_router=SimpleNamespace(
        resolve=AsyncMock(return_value=route),
        stream=lambda *_args, **_kwargs: iter([{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]),
    ))
    await complete_stream(agent, "model-a", [{"role": "user", "content": "private prompt must not persist"}], [], max_retries=0)
    rows = diagnostic_store.list_model_requests("model-a")
    assert len(rows) == 1 and rows[0]["status"] == "ok" and rows[0]["duration_ms"] >= 0
    serialized = json.dumps(rows[0], ensure_ascii=False)
    assert "private prompt" not in serialized and "never-store-this" not in serialized and "secret" not in serialized


async def test_data_directory_copy_verifies_manifest_and_preserves_rollback_source(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data").mkdir()
    (source / "data" / "user-settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
    (source / "config").mkdir()
    (source / "config" / "atlas.toml").write_text("[server]\nport=8765\n", encoding="utf-8")
    target = tmp_path / "destination"
    monkeypatch.setattr(maintenance_router, "DATA_ROOT", source)
    monkeypatch.setattr(diagnostic_store, "DATA_ROOT", source)
    preview = await maintenance_router.preview_data_directory({"target": str(target)})
    assert preview["file_count"] == 2
    result = await maintenance_router.copy_verify_data_directory({"target": str(target)})
    assert result["verified"] is True
    assert (target / "data" / "user-settings.json").read_text(encoding="utf-8") == '{"theme":"dark"}'
    status = await maintenance_router.get_data_directory()
    assert status["current_root"] == str(source)
    marker = json.loads((target / "data" / ".atlas-data-migration.json").read_text(encoding="utf-8"))
    assert marker["source_root"] == str(source)


async def test_crash_report_redacts_sensitive_fields_and_resource_preview_is_read_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maintenance_router, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(diagnostic_store, "DATA_ROOT", tmp_path)
    result = await maintenance_router.save_crash_report({
        "reason": "renderer failed", "diagnostics": {"api_key": "never-write-this", "summary": "local"},
    })
    report_path = Path(result["path"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["diagnostics"]["api_key"] == "（已隐藏）"
    assert "never-write-this" not in report_path.read_text(encoding="utf-8")
    rows = await maintenance_router.list_crash_reports()
    assert rows["reports"][0]["id"] == f"crash-{result['id']}"
    preview = await maintenance_router.preview_resource_reset()
    assert {item["id"] for item in preview["categories"]} == {"sessions", "logs", "artifacts", "cache", "snapshots", "models"}
    assert preview["categories"][0]["bytes"] >= 0
