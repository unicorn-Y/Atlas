"""T00.2 bootstrap tests: the harness runs two REAL isolated services.

These tests exercise :class:`tests.unified_memory.harness.UMHarness` itself:
isolation from production data, real health endpoints, real process restart,
the real WebSocket chat path with a loopback fake model, and the /v1 vs /api
routing of ``h.api``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unified_memory.harness import (
    PRODUCTION_ATLAS_DATA,
    PRODUCTION_MEMORYOS_ROOT,
    UMHarness,
)

pytestmark = pytest.mark.fake_provider


def test_harness_never_uses_production(um: UMHarness) -> None:
    """Runtime is TEST-bound and every data path is outside production roots."""
    manifest = um.runtime_manifest
    assert manifest["event_class"] == "TEST"

    memoryos_db = Path(manifest["memoryos_db"]).resolve()
    assert memoryos_db != PRODUCTION_MEMORYOS_ROOT.resolve()
    assert PRODUCTION_MEMORYOS_ROOT.resolve() not in memoryos_db.parents
    assert memoryos_db.is_relative_to(Path(manifest["memoryos_data"]).resolve())

    atlas_data = Path(manifest["atlas_data"]).resolve()
    assert atlas_data != PRODUCTION_ATLAS_DATA.resolve()
    assert PRODUCTION_ATLAS_DATA.resolve() not in atlas_data.parents
    assert atlas_data.is_relative_to(Path(manifest["runtime_root"]).resolve())

    # The two services must be separate data roots of the same runtime instance.
    assert atlas_data != memoryos_db
    assert manifest["model"]["provider"] == "fake-loopback"

    atlas_env = um._atlas_env(atlas_data)
    assert Path(atlas_env["MEMORYOS_DATA_ROOT"]).resolve() == Path(manifest["memoryos_data"]).resolve()
    assert Path(atlas_env["MEMORYOS_DB_PATH"]).resolve() == memoryos_db


def test_both_services_healthy(um: UMHarness) -> None:
    atlas_health = um.api("GET", "/api/health")
    assert atlas_health.status_code == 200, atlas_health.text[:300]
    assert atlas_health.json()["status"] in {"ok", "starting"}

    memoryos_health = um.api("GET", "/v1/health")
    assert memoryos_health.status_code == 200, memoryos_health.text[:300]
    assert memoryos_health.json()["data_source"] == "sqlite"


def test_restart_atlas(um: UMHarness) -> None:
    pid_before = um.runtime_manifest["atlas_pid"]
    data_dir_before = um.runtime_manifest["atlas_data"]
    port_before = um.runtime_manifest["atlas_port"]

    um.restart("atlas")

    assert um.runtime_manifest["atlas_pid"] != pid_before
    assert um.runtime_manifest["atlas_data"] == data_dir_before, "数据目录必须不变"
    assert um.runtime_manifest["atlas_port"] == port_before
    assert um.api("GET", "/api/health").status_code == 200
    assert um.runtime_manifest["restarts"][-1]["component"] == "atlas"


def test_fault_registry_wiring(um: UMHarness) -> None:
    """service_down/service_up are wired; unknown faults raise, never no-op."""
    import httpx
    import pytest

    um.fault("service_down", True)
    with pytest.raises(httpx.TransportError):
        um.api("GET", "/v1/health")

    um.fault("service_up", True)
    assert um.api("GET", "/v1/health").status_code == 200

    try:
        um.fault("vector_unavailable", True)
    except NotImplementedError:
        pass
    else:
        raise AssertionError("未接线的故障必须 NotImplementedError，不允许静默")


def test_chat_roundtrip(um: UMHarness) -> None:
    """Fake model answers one line; the real WS run path must complete."""
    result = um.chat("请回复一句测试回复。")
    assert result["status"] == "completed", f"failure={result['failure']}"
    assert result["reply"].strip(), "假模型回复为空，WS 全流程未真正跑通"
    assert result["events"].get("run.started") == 1
    assert result["events"].get("run.completed") == 1
    assert result["trace"]["source"] == "real-ws-events"
    # Reply comes from the loopback fake provider's default text, proving the
    # real model client → real agent loop → real WS protocol chain executed.
    assert result["reply"].strip() == "um-fake-ok"


def test_harness_loopback_http_ignores_system_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Harness requests to its isolated local services must bypass OS proxies."""
    calls: list[dict[str, object]] = []

    def request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return object()

    monkeypatch.setattr("tests.unified_memory.harness.httpx.request", request)
    monkeypatch.setattr(UMHarness, "memoryos_url", property(lambda _self: "http://127.0.0.1:65534"))

    result = UMHarness().api("GET", "/v1/health")

    assert result is not None
    assert len(calls) == 1
    assert calls[0]["url"] == "http://127.0.0.1:65534/v1/health"
    assert calls[0]["trust_env"] is False


def test_run_summary_only_reports_run_scoped_application_receipts(tmp_path: Path) -> None:
    """Summary evidence comes from this run's real read_id, never nearby DB rows."""
    import json
    import sqlite3

    db_file = tmp_path / "db" / "memoryos.sqlite3"
    db_file.parent.mkdir(parents=True)
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE learning_applications (application_id TEXT, read_id TEXT, "
            "context_hash TEXT, action_refs_json TEXT, basis_json TEXT, "
            "applied_items_json TEXT, created_at TEXT)"
        )
        conn.executemany(
            "INSERT INTO learning_applications VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("app-other", "read-other", "h", "[]", "{}",
                 json.dumps([{"facet": "PREFERENCE", "content": {"value": "wrong"}}]), "2"),
                ("app-current", "read-current", "h", "[]", "{}",
                 json.dumps([{"facet": "PREFERENCE", "content": {"value": "简短中文"}}]), "1"),
            ],
        )

    harness = object.__new__(UMHarness)
    harness.started = False
    harness.stopped = True
    harness.runtime_manifest = {"memoryos_db": str(db_file)}
    run_id = "run-current"
    result = harness._summarize_run(run_id, "conversation-current", [
        {"run_id": "run-current", "event": "application_receipt",
         "data": {"read_id": "read-current", "status": "RECORDED"}},
        {"run_id": "run-other", "event": "application_receipt",
         "data": {"read_id": "read-other", "status": "RECORDED"}},
    ])

    assert [row["read_id"] for row in result["application_receipts"]] == [
        "read-current", "read-current",
    ]
    assert result["applied_preference"] == "简短中文"
    assert result["applied_preference_status"] == "VERIFIED_BY_RUN_SCOPED_APPLICATION_RECEIPT"
    assert result["fabricated_fact"] is None
    assert result["fabricated_fact_status"] == "UNVERIFIED"


def test_api_routing(um: UMHarness) -> None:
    """/v1/* reaches MemoryOS; /api/* reaches Atlas; wrong prefixes rejected."""
    memoryos_body = um.api("GET", "/v1/health").json()
    atlas_body = um.api("GET", "/api/health").json()
    # MemoryOS /v1/health shape (service/app.py): slice + data_source + version.
    assert "slice" in memoryos_body and memoryos_body["data_source"] == "sqlite"
    # Atlas /api/health shape (api/health_router.py): status + components.
    assert "components" in atlas_body and atlas_body["version"] == "0.1.0"

    try:
        um.api("GET", "/other/path")
    except ValueError:
        pass
    else:
        raise AssertionError("非 /v1 与 /api 前缀必须被拒绝")


def test_tool_dispatch_resolves_real_tool(um: UMHarness) -> None:
    """h.tool drives the real execute_tools_node; the receipt is the real result."""
    outcome = um.tool("terminal", {"command": "echo um-tool-ok", "shell": "powershell"})
    assert outcome["status"] == "completed", outcome
    assert outcome["resolved_name"], "必须从真实 tool.started 事件记录解析后的工具名"
    assert outcome["receipts"], "没有真实 tool.completed 收据"
    assert not outcome["is_error"], f"工具执行报错: {outcome['receipts']}"
    joined = " ".join(
        str(block.get("text", block)) if isinstance(block, dict) else str(block)
        for block in outcome["receipts"][0]["result"]
    )
    assert "um-tool-ok" in joined, f"工具收据不含执行输出: {joined[:300]}"
