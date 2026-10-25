"""``/api/automations`` REST 面全覆盖（lane W4；TestClient + 真 DBOS 引擎）.

策略与 tests/test_automation_engine.py 相同：模块共用一个 DBOS 实例与一个
已 start 的 AutomationEngine（单例经 set_automation_engine 注入），async
用例共享模块级 loop；TestClient 的 portal loop 独立存在，但 DBOS 的
*_async 只做 to_thread DB 操作、workflow 都跑在 DBOS 后台 loop 上，
两个 loop 并存安全。

覆盖：list/create/validate-400/get/patch/delete(+404)、run-now(+wait 参数)、
runs、pause→run-now 409→resume、cancel、import-legacy、engine 未启动 503。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.automation import set_automation_engine
from atlas.automation.engine import AutomationEngine, schedule_name
from atlas.automation.store import AutomationStore
from atlas.api.automation_router import automation_router

pytest.importorskip("dbos")

# 与 engine 模块同一约束：async 用例共享模块级 loop（避免 DBOS 执行器被
# Runner 关闭）。本文件的 async 用例只做 runs 断言。
pytestmark = pytest.mark.asyncio(loop_scope="module")

LEGACY_TOML = """
[tasks.router-legacy]
name = "路由导入"
trigger_type = "interval"
action = "agent:检查一次"
status = "active"

[tasks.router-legacy.trigger_args]
minutes = 15
"""


@pytest.fixture(scope="module")
def env(tmp_path_factory) -> Any:
    tmp = tmp_path_factory.mktemp("automation-router")
    from dbos import DBOS

    (tmp / "dbos").mkdir(parents=True, exist_ok=True)
    DBOS(config={
        "name": "atlas-automation-router",
        "system_database_url": f"sqlite:///{(tmp / 'dbos' / 'dbos.sqlite').as_posix()}",
        "db_engine_kwargs": {"connect_args": {"timeout": 30}},
        "scheduler_polling_interval_sec": 1.0,
    })
    DBOS.launch()

    async def _tick(agent_id: str, reason: str) -> dict:
        return {"tick": agent_id, "reason": reason}

    async def _dispatch(payload: dict) -> dict:
        return {"sent": True}

    store = AutomationStore(tmp / "automations.toml")
    engine = AutomationEngine(store, heartbeat_tick=_tick, dispatch_turn=_dispatch)
    engine.start(DBOS)
    previous = set_automation_engine(engine)

    app = FastAPI()
    app.include_router(automation_router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, store=store, engine=engine, tmp=tmp)

    set_automation_engine(previous)
    engine.shutdown()
    DBOS.destroy(destroy_registry=True)


def _script_body(automation_id: str) -> dict:
    return {
        "id": automation_id,
        "name": "路由脚本",
        "trigger": {"kind": "cron", "cron_expr": "0 0 1 1 *"},
        "payload": {"kind": "script", "script": "echo router-ok"},
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_list_empty_and_engine_flag(env: Any) -> None:
    data = env.client.get("/api/automations").json()
    assert data["engine_started"] is True
    assert isinstance(data["automations"], list)


def test_create_validate_get_patch_delete(env: Any) -> None:
    client = env.client

    # 非法 cron → 400
    bad = _script_body("router-bad")
    bad["trigger"]["cron_expr"] = "not a cron"
    resp = client.post("/api/automations", json=bad)
    assert resp.status_code == 400
    assert "cron_expr" in resp.json()["detail"]

    # 非法 payload.kind：pydantic Literal 直接 422（枚举校验双保险的另一层）
    bad2 = _script_body("router-bad2")
    bad2["payload"]["kind"] = "shell"
    assert client.post("/api/automations", json=bad2).status_code == 422

    bad_effort = _script_body("router-bad-effort")
    bad_effort["payload"] = {"kind": "agent_turn", "message": "run", "reasoning_effort": "turbo"}
    assert client.post("/api/automations", json=bad_effort).status_code == 422

    model_body = _script_body("router-model")
    model_body["payload"] = {"kind": "agent_turn", "message": "run", "model": "deepseek-v4.1-flash", "reasoning_effort": "high"}
    model_resp = client.post("/api/automations", json=model_body)
    assert model_resp.status_code == 200
    assert model_resp.json()["automation"]["payload"]["reasoning_effort"] == "high"

    # 正常创建（含 DBOS schedule 同步）
    resp = client.post("/api/automations", json=_script_body("router-crud"))
    assert resp.status_code == 200
    created = resp.json()["automation"]
    assert created["id"] == "router-crud"
    assert created["state"]["consecutive_errors"] == 0
    assert created["next_run_at"]  # cron 展示投影
    from dbos import DBOS

    assert DBOS.get_schedule(schedule_name("router-crud")) is not None

    # list / get
    ids = [item["id"] for item in client.get("/api/automations").json()["automations"]]
    assert "router-crud" in ids
    got = client.get("/api/automations/router-crud")
    assert got.status_code == 200
    assert got.json()["automation"]["payload"]["script"] == "echo router-ok"

    # PATCH：改名 + 改表达式（section 局部合并）
    patched = client.patch(
        "/api/automations/router-crud",
        json={"name": "改名", "trigger": {"cron_expr": "30 0 1 1 *"}},
    )
    assert patched.status_code == 200
    body = patched.json()["automation"]
    assert body["name"] == "改名"
    assert body["trigger"]["cron_expr"] == "30 0 1 1 *"
    assert body["trigger"]["kind"] == "cron"  # 未提供的字段保留
    assert DBOS.get_schedule(schedule_name("router-crud"))["schedule"] == "30 0 1 1 *"

    # DELETE → 404 后续
    assert client.delete("/api/automations/router-crud").json()["deleted"] is True
    assert client.get("/api/automations/router-crud").status_code == 404
    assert client.delete("/api/automations/router-crud").status_code == 404
    assert DBOS.get_schedule(schedule_name("router-crud")) is None
    assert client.get("/api/automations/nope").status_code == 404


# ---------------------------------------------------------------------------
# run-now / runs / pause / resume / cancel
# ---------------------------------------------------------------------------


def test_run_now_wait_runs_and_runs_history(env: Any) -> None:
    client = env.client
    assert client.post("/api/automations", json=_script_body("router-run")).status_code == 200

    resp = client.post("/api/automations/router-run/run-now", params={"wait": 20})
    assert resp.status_code == 200
    receipt = resp.json()
    assert receipt["fired"] is True
    assert receipt["receipt"]["kind"] == "dbos_workflow"
    assert receipt["status"] == "SUCCESS"
    assert "router-ok" in receipt["result"]["result"]["stdout"]

    runs = client.get("/api/automations/router-run/runs").json()["runs"]
    assert len(runs) >= 1
    assert runs[0]["workflow_id"] == receipt["workflow_id"]
    assert {"ENQUEUED", "PENDING", "RUNNING", "SUCCESS"} >= {runs[0]["status"]}

    # 活跃已结束后再次 run-now：新 receipt（dedup 只在活跃期间合并）
    second = client.post("/api/automations/router-run/run-now", params={"wait": 20}).json()
    assert second["workflow_id"] != receipt["workflow_id"]
    assert client.delete("/api/automations/router-run").status_code == 200


def test_pause_blocks_run_now_then_resume(env: Any) -> None:
    client = env.client
    body = _script_body("router-pause")
    body["trigger"] = {"kind": "interval", "every_seconds": 3600}
    assert client.post("/api/automations", json=body).status_code == 200

    paused = client.post("/api/automations/router-pause/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    record = env.store.get("router-pause")
    assert record["state"]["paused_reason"] == "user"
    assert record["enabled"] is True

    blocked = client.post("/api/automations/router-pause/run-now", params={"wait": 5})
    assert blocked.status_code == 409

    resumed = client.post("/api/automations/router-pause/resume")
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False
    assert env.store.get("router-pause")["state"]["paused_reason"] == ""

    ok = client.post("/api/automations/router-pause/run-now", params={"wait": 20})
    assert ok.status_code == 200
    client.post("/api/automations/router-pause/cancel")
    client.delete("/api/automations/router-pause")


def test_cancel_active_run(env: Any) -> None:
    client = env.client
    body = _script_body("router-cancel")
    body["payload"] = {
        "kind": "script",
        "script": "ping -n 30 127.0.0.1 >nul",  # Windows cmd 长跑，给 cancel 留窗口
        "timeout_seconds": 60,
    }
    assert client.post("/api/automations", json=body).status_code == 200

    first = client.post("/api/automations/router-cancel/run-now")  # 不等待
    assert first.status_code == 200
    assert first.json()["fired"] is True

    cancelled = client.post("/api/automations/router-cancel/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"], "活跃 run 应被取消"
    client.delete("/api/automations/router-cancel")


# ---------------------------------------------------------------------------
# import-legacy
# ---------------------------------------------------------------------------


def test_import_legacy_endpoint(env: Any) -> None:
    legacy = env.tmp / "legacy-schedules.toml"
    legacy.write_text(LEGACY_TOML, encoding="utf-8")
    resp = env.client.post(
        "/api/automations/import-legacy", json={"toml_path": str(legacy)}
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["imported_count"] == 1
    assert report["imported"][0]["id"] == "router-legacy"
    record = env.store.get("router-legacy")
    assert record is not None
    assert record["trigger"]["kind"] == "interval"
    assert record["trigger"]["every_seconds"] == 900.0

    # 幂等：二次导入只剩 skipped
    second = env.client.post(
        "/api/automations/import-legacy", json={"toml_path": str(legacy)}
    ).json()
    assert second["imported_count"] == 0
    env.store.delete("router-legacy")


# ---------------------------------------------------------------------------
# engine 未启动 → 503
# ---------------------------------------------------------------------------


def test_run_control_endpoints_require_started_engine(env: Any) -> None:
    cold = AutomationEngine(AutomationStore(env.tmp / "cold.toml"))
    restore = set_automation_engine(cold)
    try:
        client = env.client
        assert client.get("/api/automations").json()["engine_started"] is False
        assert (
            client.post("/api/automations/cold/run-now").status_code == 503
        )
        assert client.post("/api/automations/cold/cancel").status_code == 503
        assert client.get("/api/automations/cold/runs").status_code == 503
    finally:
        set_automation_engine(restore)
