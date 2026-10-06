"""T02.3 验收测试：被调用 Agent 的返回归入 Atlas（unified-memory/waves UM02）。

判据（02_wave_tasks.md T02.3 + 01_contracts.md §1.1）：
  * unit：capture_agent_tool_result 观察schema（ATLAS_AGENT_TOOL_RESULT /
    THIRD_PARTY / THIRD_PARTY_ASSERTED / content.actor_id /
    only_assistant_claim=True / 真实 tool_call ID / log_refs）；**对方声明不是
    验证** —— 声明观察无任何 verification 语义，Atlas 独立检查走
    ATLAS_VERIFICATION（revision=3，同一 source_object_id）；后端直连路径
    （无 Atlas 对话）用 AGENT_BACKEND_SESSION locator；tool_node 真实 Agent-tool
    分支接线（execute_tools_node → delegate_task）与 agent_backends_router
    prompt 流结束接线都真实产出观察。
  * 集成（um harness，参考 test_capture_lifecycle 已绿模式）：h.tool 经真实
    dispatch 驱动 delegate_task（**真实**：工具派发 / DelegationService /
    子代理运行 / 记录接线 / outbox / MemoryOS 服务端；**模拟**：被调 Agent 用
    Atlas 自身子代理 executor=atlas + fake 模型 —— TEST runtime 隔离环境不安装
    也不真跑 zcode/codex 外部 CLI）→ 服务端 records 出现 actor_id=tool-atlas
    的观察、only_assistant_claim=true → /api/unified-memory/verify-agent-result
    以真实文件存在性检查追加 ATLAS_VERIFICATION（verified=false —— 对方声称
    完成、Atlas 独立查证产物不存在）。

任务书判据 test_agent_result_belongs_to_atlas 原样语义实现：records 全部属于
harness 主体（atlas-fixture）且存在被调 actor 的观察。两处按实际映射并注释：
  1) actor_id：判据示例 "tool-zcode" 的语义是「存在被调 actor（tool-<后端名>）」；
     TEST runtime 不真跑外部 zcode CLI，实际执行者是 Atlas 子代理 → 断言
     actor_id == "tool-atlas"（同一语义，actor 按真实后端名记录）。
  2) memory_subject_id：服务端 records 端点按绑定主体过滤（T01.1 负例已证异
     主体 403），投影字段不含 memory_subject_id → 等价断言：harness 绑定主体
     == atlas-fixture 且记录全部经该主体端点返回。

记录投影层级（MemoryOS repository._event_to_record）：
    item["content"]["text"]          = 观察原 content（本测试的 _obs_content）
    item["content"]["source_kind" / "speaker_role" / "locator"] = 观察同名字段
    item["source_refs"][0]["source_event_id"] = 幂等键

运行（Atlas core 解释器）：
  cd /d/Atlas && core/.venv/Scripts/python.exe -m pytest core/tests/unified_memory \\
      -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from atlas.memory.capture import (
    TOOL_REVISION_RESULT,
    TOOL_REVISION_VERIFICATION,
    CaptureService,
)
from atlas.memory.outbox import OperationalOutbox
from tests.unified_memory.harness import EVENT_CLASS


# ------------------------------------------------------------------ 夹具


class _Cfg(dict):
    """带 .get 接口的最小配置替身。"""


@pytest.fixture(autouse=True)
def _clean_capture_singleton():
    """单例隔离：每个用例前后复位进程级 CaptureService。"""
    from atlas.memory.capture import reset_capture_service

    reset_capture_service()
    yield
    reset_capture_service()


def _service(tmp_path, facade: Any = None, **kwargs: Any) -> CaptureService:
    return CaptureService(
        facade=facade, outbox_path=tmp_path / "unified_outbox.sqlite3",
        event_class=EVENT_CLASS, **kwargs)


def _obs_content(item: dict[str, Any]) -> dict[str, Any]:
    """观察原 content（record 投影把它放在 content.text）。"""
    text = item.get("content", {}).get("text")
    return text if isinstance(text, dict) else {}


def _projection(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("content") if isinstance(item.get("content"), dict) else {}


def _source_event_id(item: dict[str, Any]) -> str:
    return str((item.get("source_refs") or [{}])[0].get("source_event_id") or "")


def _outbox_rows(tmp_path) -> dict[str, dict[str, Any]]:
    outbox = OperationalOutbox(tmp_path / "unified_outbox.sqlite3")
    rows = {row["source_event_id"]: row["payload"]["observation"]
            for row in outbox.poll_pending(100)}
    outbox.close()
    return rows


# ------------------------------------------------------------------ unit


@pytest.mark.unit
def test_agent_tool_result_builder_schema(tmp_path) -> None:
    """对方返回的观察schema：THIRD_PARTY 自报 + actor_id + only_assistant_claim
    + 真实 tool_call ID + log_refs（revision=2 与工具 result 同层）。"""
    service = _service(tmp_path)
    result = service.capture_agent_tool_result(
        "conv-1", "agent-tc-1", "tool-zcode", "我完成了重构并全部通过测试。",
        tool_name="delegate_task",
        result_payload={"status": "completed", "backend": "zcode"},
        log_refs={"subtask_id": "st-1", "full_output_path": "/blobs/st-1.log"})
    assert result is not None and result["created"] is True
    assert result["source_event_id"] == (
        f"atlas:ATLAS_AGENT_TOOL_RESULT:agent-tc-1:{TOOL_REVISION_RESULT}:UPSERT")

    rows = _outbox_rows(tmp_path)
    observation = rows[result["source_event_id"]]
    assert observation["source_kind"] == "ATLAS_AGENT_TOOL_RESULT"
    assert observation["speaker_role"] == "THIRD_PARTY"
    assert observation["epistemic_kind"] == "THIRD_PARTY_ASSERTED"
    assert observation["content"]["actor_id"] == "tool-zcode"
    assert observation["content"]["only_assistant_claim"] is True
    assert observation["content"]["tool"] == "delegate_task"
    assert observation["content"]["result_payload"]["backend"] == "zcode"
    assert observation["content"]["log_refs"] == {
        "subtask_id": "st-1", "full_output_path": "/blobs/st-1.log"}
    assert observation["locator"] == {"kind": "TOOL_CALL",
                                      "value": "conv-1/agent-tc-1"}


@pytest.mark.unit
def test_agent_claim_is_not_verification_and_verification_is_separate(tmp_path) -> None:
    """§1.1：对方的完成声明**不是验证** —— 声明观察无 verification 语义；
    Atlas 独立检查走 ATLAS_VERIFICATION（rev=3、同一 source_object_id、
    checks 落 content、verified=全部通过；无检查 → verified=False）。"""
    service = _service(tmp_path)
    claim = service.capture_agent_tool_result(
        "conv-1", "tc-v", "tool-codex", "全部完成，测试通过。")
    verification = service.capture_agent_verification(
        "conv-1", "tc-v", "delegate_task",
        [{"kind": "FILE_EXISTS", "target": "src/a.py", "passed": True,
          "detail": "声称产物已存在"},
         {"kind": "PROCESS_EXIT", "passed": True}])
    empty = service.capture_agent_verification(
        "conv-1", "tc-empty", "delegate_task", [])

    assert claim is not None and verification is not None and empty is not None
    rows = _outbox_rows(tmp_path)
    claim_obs = rows[claim["source_event_id"]]
    assert claim_obs["content"].get("verification") != "VERIFIED"
    assert "checks" not in claim_obs["content"]
    assert claim_obs["content"]["only_assistant_claim"] is True

    check_obs = rows[verification["source_event_id"]]
    assert check_obs["source_kind"] == "ATLAS_VERIFICATION"
    assert check_obs["speaker_role"] == "ATLAS"
    assert check_obs["epistemic_kind"] == "OBSERVED"
    assert check_obs["source_event_id"] == (
        f"atlas:ATLAS_VERIFICATION:tc-v:{TOOL_REVISION_VERIFICATION}:UPSERT")
    assert check_obs["content"]["verified"] is True
    assert [item["kind"] for item in check_obs["content"]["checks"]] == [
        "FILE_EXISTS", "PROCESS_EXIT"]
    # 与声明观察同一对象、不同 revision —— 关联同一 tool_call 经历。
    assert check_obs["source_object_id"] == claim_obs["source_object_id"]

    failed = service.capture_agent_verification(
        "conv-1", "tc-fail", "delegate_task",
        [{"kind": "FILE_EXISTS", "passed": False}])
    assert failed is not None
    assert _outbox_rows(tmp_path)[failed["source_event_id"]]["content"]["verified"] is False


@pytest.mark.unit
def test_backend_direct_path_uses_agent_backend_session_locator(tmp_path) -> None:
    """agent_backends_router 直连后端路径没有 Atlas 对话：locator 用
    AGENT_BACKEND_SESSION，不把后端会话伪造成 Atlas 运行会话。"""
    service = _service(tmp_path)
    claim = service.capture_agent_tool_result(
        "", "agentprompt-s1-ab12cd34ef56", "tool-zcode", "已完成",
        atlas_session=False)
    check = service.capture_agent_verification(
        "", "agentprompt-s1-ab12cd34ef56", "agent_backend_prompt",
        [{"kind": "API_OK", "passed": True}], atlas_session=False)
    assert claim is not None and check is not None
    rows = _outbox_rows(tmp_path)
    assert rows[claim["source_event_id"]]["locator"] == {
        "kind": "AGENT_BACKEND_SESSION", "value": "agentprompt-s1-ab12cd34ef56"}
    assert rows[claim["source_event_id"]]["content"]["session_id"] == ""
    assert rows[check["source_event_id"]]["locator"]["kind"] == "AGENT_BACKEND_SESSION"


@pytest.mark.unit
def test_windows_source_service_requires_capture(monkeypatch, tmp_path) -> None:
    """capture disabled → get_windows_source_service()=None；服务记录返回 None、
    导入显式报错（不静默丢导入）。"""
    from atlas.memory import capture as capture_module
    from atlas.memory.windows_sources import WindowsSourceService, get_windows_source_service

    monkeypatch.setattr(capture_module, "_load_config",
                        lambda: _Cfg({"memory.unified.enabled": False}))
    assert get_windows_source_service() is None

    service = WindowsSourceService(capture=None, registry_path=tmp_path / "registry.json")
    assert service.capture is None
    assert service.record_agent_tool_result(
        "delegate_task", "tool-zcode", "tc-1", {"status": "completed"}) is None
    assert service.verify_agent_result("tc-1", [{"passed": True}]) is None
    with pytest.raises(RuntimeError):
        service.import_text_file("whatever.txt")


@pytest.mark.unit
def test_tool_node_delegate_task_wiring_captures_third_party_claim(
        tmp_path, monkeypatch) -> None:
    """真实接线（tool_node 分支）：execute_tools_node 跑 delegate_task →
    outbox 出现 THIRD_PARTY 声明观察（actor=tool-<真实后端名>、对象 ID=真实
    tool_call ID、log_refs 带子任务 ID）。"""
    from atlas.agent import AgentOrchestrator
    from atlas.agent.tool_node import AGENT_RESULT_TOOLS

    assert {"delegate_task", "delegate_parallel"} <= AGENT_RESULT_TOOLS

    captured: dict[str, Any] = {}

    class _StubDelegation:
        async def delegate_task(self, goal, context=None, tool_profile=None, **kwargs):
            captured["goal"] = goal
            return {"backend": "zcode", "session_id": None, "subtask_id": "st-9",
                    "status": "completed",
                    "result": "我完成了重构并全部通过测试。", "evidence": []}

    model_mgr = MagicMock()
    model_mgr.current_model = "test-model"
    agent = AgentOrchestrator(model_mgr, AsyncMock(), MagicMock())
    agent._delegation = _StubDelegation()
    agent._emit_hook = AsyncMock(return_value=None)
    agent._model_facing_tools = lambda: []
    agent._resolve_subagent_model = lambda model, parent: model or "test-model"
    agent.trajectory_reviewer = SimpleNamespace(reviewer=None, evidence=[])

    runtime = SimpleNamespace(
        conversation_id="conv-wiring", model="test-model", project_id=None,
        workspace=None, allowed_paths=[], permission_mode="full_access",
        cancel_event=None, pause_event=None, event_queue=None,
        user_hook_callback=None, ssh_tool_callback=None,
        ssh_checkpoint_callback=None, sandbox_tool_callback=None,
        workspace_trusted=False, run_id="run-1", mode="act",
        read_only=False, agent_depth=0, agent_role="leaf",
        agent_type="general", todo_store=None,
        changed_paths=set(), verification_passed=False,
    )
    state = {
        "messages": [HumanMessage(content="委派任务"),
                     AIMessage(content="", tool_calls=[
                         {"name": "delegate_task",
                          "args": {"goal": "重构模块"}, "id": "agent-tc-wiring"}])],
        "pending_events": [],
        "runtime": runtime,
    }

    import atlas.memory.capture as capture_module
    capture_service = CaptureService(
        facade=None, outbox_path=tmp_path / "unified_outbox.sqlite3",
        event_class=EVENT_CLASS)
    monkeypatch.setattr(capture_module, "get_capture_service",
                        lambda: capture_service)
    # 注册表默认路径随 ATLAS_DATA_DIR —— 指向 tmp，不在 CWD 产生 side effect。
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))

    from atlas.agent.tool_node import execute_tools_node

    result = asyncio_run(execute_tools_node(agent, state))
    tool_event = next(item for item in result["pending_events"]
                      if item.get("type") == "tool_result")
    assert tool_event["is_error"] is False
    assert captured["goal"] == "重构模块"

    rows = _outbox_rows(tmp_path)
    claims = [obs for obs in rows.values()
              if obs["source_kind"] == "ATLAS_AGENT_TOOL_RESULT"]
    assert len(claims) == 1
    claim = claims[0]
    assert claim["source_object_id"] == "agent-tc-wiring"   # 真实 tool_call ID
    assert claim["content"]["actor_id"] == "tool-zcode"     # 真实后端名
    assert claim["content"]["only_assistant_claim"] is True
    assert claim["content"]["log_refs"]["subtask_id"] == "st-9"
    assert claim["speaker_role"] == "THIRD_PARTY"
    capture_service.close()


@pytest.mark.unit
def test_router_backend_prompt_recording(tmp_path, monkeypatch) -> None:
    """真实接线（agent_backends_router）：后端 prompt 流结束 → THIRD_PARTY 声明
    观察（AGENT_BACKEND_SESSION locator；错误流 → is_error 声明）。"""
    import atlas.memory.capture as capture_module
    from atlas.api.agent_backends_router import _record_backend_agent_result

    capture_service = CaptureService(
        facade=None, outbox_path=tmp_path / "unified_outbox.sqlite3",
        event_class=EVENT_CLASS)
    monkeypatch.setattr(capture_module, "get_capture_service",
                        lambda: capture_service)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))

    _record_backend_agent_result(
        backend_name="zcode", session_id="backend-s1",
        tool_call_id="agentprompt-backend-s1-0123456789ab",
        claim="任务完成。", error=None)
    _record_backend_agent_result(
        backend_name=None, session_id="backend-s2",
        tool_call_id="agentprompt-backend-s2-0123456789ab",
        claim="", error="外部 Agent 执行失败。")

    rows = _outbox_rows(tmp_path)
    claims = [obs for obs in rows.values()
              if obs["source_kind"] == "ATLAS_AGENT_TOOL_RESULT"]
    assert len(claims) == 2
    ok = next(item for item in claims if item["content"]["actor_id"] == "tool-zcode")
    assert ok["locator"]["kind"] == "AGENT_BACKEND_SESSION"
    assert ok["content"]["only_assistant_claim"] is True
    assert ok["content"]["log_refs"]["backend_session_id"] == "backend-s1"
    failed = next(item for item in claims if item["content"]["is_error"] is True)
    assert failed["content"]["actor_id"] == "tool-external-agent"
    assert failed["content"]["log_refs"]["error"].startswith("外部 Agent 执行失败")
    capture_service.close()


def asyncio_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


# ------------------------------------------------------------------ 集成


def _fetch_records(h: Any, limit: int = 200) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = h.api("GET", "/v1/unified/records", params=params)
        assert response.status_code == 200, response.text[:300]
        payload = response.json()
        items.extend(payload["items"])
        cursor = payload.get("next_cursor")
        if not cursor:
            return items


def _seid_object(item: dict[str, Any]) -> str:
    """按 seid 语法 ``atlas:{kind}:{object}:{revision}:{action}`` 从右锚定取对象 ID。

    对象 ID 允许含冒号（Atlas 合成 tool_call_id 形如 ``atlas:{uuid}``），与
    MemoryOS 契约 ``_SOURCE_EVENT_ID_RE`` 同一规则；朴素 split(":")[2] 会把
    "atlas" 前缀误当对象 ID。
    """
    parts = _source_event_id(item).split(":")
    return ":".join(parts[2:-2])


def _wait_for_records(h: Any, predicate: Any, *, timeout: float = 120.0,
                      description: str = "") -> list[dict[str, Any]]:
    """等 Atlas 侧 outbox flush 后，真实 MemoryOS /v1/unified/records 可读。"""
    deadline = time.monotonic() + timeout
    seen = 0
    while time.monotonic() < deadline:
        items = _fetch_records(h)
        seen = len(items)
        hits = [item for item in items if predicate(item)]
        if hits:
            return hits
        time.sleep(1.0)
    raise AssertionError(f"等待记录超时（{timeout:.0f}s）: {description}；当前 {seen} 条")


@pytest.mark.integration
def test_delegate_task_claim_is_third_party_and_belongs_to_atlas(um) -> None:
    """主判据集成：h.tool 真实派发 delegate_task（被调 Agent = Atlas 子代理，
    executor=atlas + fake 模型 —— TEST runtime 不真跑外部 CLI）→ 服务端 records
    出现 ATLAS_AGENT_TOOL_RESULT 观察：actor_id=tool-atlas（任务书示例
    tool-zcode 的同义映射，见模块 docstring）、only_assistant_claim=true、
    THIRD_PARTY 自报；对象 ID 是真实 WS 收据里的 tool_call_id。

    test_agent_result_belongs_to_atlas（任务书原样语义）：records 全部属于
    harness 主体 atlas-fixture（服务端按绑定主体过滤，投影无 memory_subject_id
    字段 —— 等价断言见模块 docstring），且存在被调 actor 的观察。
    """
    assert um.default_context()["memory_subject_id"] == "atlas-fixture"
    receipt = um.tool("delegate_task", {
        "goal": "总结 unified memory 的来源类型清单（只读任务，不要修改文件）。"})
    assert receipt["status"] == "completed"
    assert not receipt["is_error"], receipt
    session_id = receipt["conversation_id"]
    receipt_ids = {item["tool_call_id"] for item in receipt["receipts"]}

    def _claim(item: dict[str, Any]) -> bool:
        text = _obs_content(item)
        return (_projection(item).get("source_kind") == "ATLAS_AGENT_TOOL_RESULT"
                and text.get("session_id") == session_id
                and text.get("phase") == "result")

    hits = _wait_for_records(um, _claim,
                             description="delegate_task 的 THIRD_PARTY 声明观察")
    assert len(hits) == 1
    record = hits[0]
    content = _obs_content(record)
    # 判据映射：实际后端 = Atlas 子代理 → actor_id = "tool-atlas"
    #（任务书示例 tool-zcode 的语义等价：存在 tool-<后端名> 被调 actor）。
    assert content["actor_id"] == "tool-atlas"
    assert content["only_assistant_claim"] is True
    assert content["tool"] == "delegate_task"
    assert _projection(record)["speaker_role"] == "THIRD_PARTY"
    assert record["epistemic_kind"] == "THIRD_PARTY_ASSERTED"
    object_id = _seid_object(record)
    assert object_id in receipt_ids, (
        f"捕获对象 ID {object_id} 必须在真实收据 {receipt_ids} 中")
    # 自报声明不是验证：无 verification 语义。
    assert content.get("verification") != "VERIFIED"

    # 主体归属（判据前半）：全部 records 经绑定主体端点返回。
    items = _fetch_records(um)
    assert items
    assert any(_obs_content(item).get("actor_id") == "tool-atlas" for item in items)


@pytest.mark.integration
def test_atlas_independent_verification_after_agent_claim(um) -> None:
    """返回"完成"先记录 THIRD_PARTY 声明 → Atlas 独立检查（真实文件存在性）
    → /api/unified-memory/verify-agent-result 追加 ATLAS_VERIFICATION 观察
    （同一 tool_call_id 关联；声称的产物不存在 → verified=false）。"""
    receipt = um.tool("delegate_task", {
        "goal": "在 workspace 创建 agent_proof.txt（本运行不会真的创建）。"})
    assert receipt["status"] == "completed"
    session_id = receipt["conversation_id"]
    tool_call_id = receipt["receipts"][0]["tool_call_id"]

    claim_hits = _wait_for_records(
        um, lambda item: _projection(item).get("source_kind")
        == "ATLAS_AGENT_TOOL_RESULT"
        and _obs_content(item).get("session_id") == session_id,
        description="delegate_task 声明观察")
    assert claim_hits[0]["epistemic_kind"] == "THIRD_PARTY_ASSERTED"

    # Atlas 独立检查：声称的产物在真实 workspace 里不存在（对方声明不是验证）。
    missing_target = um.workspace / "agent_proof.txt"
    check_exists = missing_target.exists()
    response = um.api("POST", "/api/unified-memory/verify-agent-result", json={
        "tool_call_id": tool_call_id,
        "session_id": session_id,
        "tool_name": "delegate_task",
        "checks": [{"kind": "FILE_EXISTS", "target": str(missing_target),
                    "passed": check_exists,
                    "detail": "被调 Agent 声称完成；Atlas 独立核对真实产物"}],
    })
    assert response.status_code == 200, response.text[:300]
    ack = response.json()
    assert ack["verified"] is check_exists
    assert ack["source_event_id"] == (
        f"atlas:ATLAS_VERIFICATION:{tool_call_id}:{TOOL_REVISION_VERIFICATION}:UPSERT")

    verification_hits = _wait_for_records(
        um, lambda item: _projection(item).get("source_kind") == "ATLAS_VERIFICATION"
        and _obs_content(item).get("session_id") == session_id,
        description="ATLAS_VERIFICATION 观察")
    assert len(verification_hits) == 1
    content = _obs_content(verification_hits[0])
    assert content["verified"] is check_exists
    assert content["checks"][0]["kind"] == "FILE_EXISTS"
    # 验证与声明是两类观察：同一对象，speaker/epistemic 分开。
    assert _projection(verification_hits[0])["speaker_role"] == "ATLAS"
    assert verification_hits[0]["epistemic_kind"] == "OBSERVED"
    claim_object = _seid_object(claim_hits[0])
    assert _seid_object(verification_hits[0]) == claim_object

    # 负例：没有真实检查就不产生验证观察。
    empty = um.api("POST", "/api/unified-memory/verify-agent-result", json={
        "tool_call_id": tool_call_id, "checks": []})
    assert empty.status_code == 422
