"""T02.2 验收测试：聊天、模型输出与工具调用的真实捕获（unified-memory/waves UM02）。

判据（02_wave_tasks.md T02.2 + 01_contracts.md §1.1/§2）：
  * unit：ObservationBuilder 的 source_event_id 格式 / content_hash / speaker_role
    映射（USER/ATLAS/TOOL）；同一真实 ID 重入只产生一次（builder 层 set 去重 +
    outbox UNIQUE 兜底，同 ID 异内容 first-write-wins）；dispatch/result/
    verification 三类观察同 source_object_id、按 revision+phase 区分；重启恢复
    （outbox 2 条未 flush → 新 CaptureService 同文件 → flush → 服务端无重复）；
    capture 抛异常时 run_phases 照常完成（护栏）。
  * 集成（um harness，子进程 enabled=true）：h.chat 真实 WS → 等 outbox flush →
    /v1/unified/records 读到 USER/ATLAS 两条观察，locator 指向 session/message
    稳定 ID；同会话再次 h.chat 无重复观察（created 不增）；工具捕获出现
    dispatch + result 观察（同 tool_call_id）；会抛错的工具产生带 error 标记的
    result 观察且服务端照收；assistant 自报 != 验证（epistemic_kind=OBSERVED
    且 content.verification 不存在或 != "VERIFIED"）。

记录投影层级（MemoryOS repository._event_to_record）：
    item["content"]["text"]          = 观察原 content（本测试的 _obs_content）
    item["content"]["source_kind" / "speaker_role" / "locator"] = 观察同名字段
    item["source_refs"][0]["source_event_id"] = 幂等键（解析出对象 ID 与 revision）

运行（Atlas core 解释器）：
  cd /d/Atlas && core/.venv/Scripts/python.exe -m pytest core/tests/unified_memory \\
      -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from atlas.memory.capture import (
    TOOL_REVISION_DISPATCH,
    TOOL_REVISION_RESULT,
    TOOL_REVISION_VERIFICATION,
    CaptureService,
    atlas_message_object_id,
    capture_enabled,
    next_source_revision,
    observation_content_hash,
)
from atlas.memory.outbox import OperationalOutbox
from tests.unified_memory.harness import EVENT_CLASS


# ------------------------------------------------------------------ 夹具


class _Cfg(dict):
    """带 .get 接口的最小配置替身（capture_enabled 只读这两个键）。"""


class _RecordingFacade:
    """flush 测试替身：记录 observe 批次；可注入前 N 次 ServiceUnavailable。"""

    def __init__(self, fail_first: int = 0) -> None:
        self.batches: list[dict[str, Any]] = []
        self.fail_first = fail_first

    def default_context(self, **overrides: Any) -> dict[str, Any]:
        context = {
            "owner_id": "owner-fixture", "memory_subject_id": "atlas-fixture",
            "client_id": "atlas-desktop", "actor_id": "atlas-main",
            "runtime_session_id": "", "task_id": None, "project_id": None,
            "environment_id": "windows", "model_deployment_id": None,
        }
        context.update(overrides)
        return context

    async def observe_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        from atlas.memory.unified_client import ServiceUnavailable

        if self.fail_first > 0:
            self.fail_first -= 1
            raise ServiceUnavailable("memoryos down for test")
        self.batches.append(batch)
        return {"created": len(batch["observations"]), "duplicates": 0, "receipts": []}


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
    """episode 投影层字段（source_kind/speaker_role/locator 从观察复制）。"""
    content = item.get("content")
    return content if isinstance(content, dict) else {}


def _source_event_id(item: dict[str, Any]) -> str:
    return str((item.get("source_refs") or [{}])[0].get("source_event_id") or "")


def _seid_object_revision(item: dict[str, Any]) -> tuple[str, str]:
    """按 seid 语法 ``atlas:{kind}:{object}:{revision}:{action}`` 取 (object, rev)。

    对象 ID 允许含冒号（Atlas 合成 tool_call_id 就是 ``atlas:{uuid}``），所以
    只能从右锚定解析 —— 与 MemoryOS 契约 ``_SOURCE_EVENT_ID_RE`` 同一规则；
    朴素的 ``split(":")[2]`` 会把 "atlas" 前缀误当对象 ID。
    """
    parts = _source_event_id(item).split(":")
    return ":".join(parts[2:-2]), parts[-2]


# ------------------------------------------------------------------ unit


@pytest.mark.unit
def test_builder_source_event_id_format_and_speaker_role_mapping(tmp_path) -> None:
    """幂等键用真实消息/工具调用 ID；speaker_role 映射 USER/ATLAS/TOOL。"""
    service = _service(tmp_path)

    user = service.capture_user_message(
        "conv-1", "msg-u-1", "记住我喜欢简洁回复", "2026-10-06T09:00:00+08:00",
        source_timezone="Asia/Hong_Kong")
    assert user is not None and user["created"] is True
    assistant = service.capture_assistant_message(
        "conv-1", "msg-a-1", "好的，已记下。", "2026-10-06T09:00:05+08:00",
        source_timezone="Asia/Hong_Kong", model="fake-model")
    assert assistant is not None and assistant["created"] is True
    call = service.capture_tool_call("conv-1", "tc-1", "local_file", {"action": "list"})
    result = service.capture_tool_result("conv-1", "tc-1", "local_file", "a.txt\nb.txt")

    assert user["source_event_id"] == "atlas:ATLAS_USER_MESSAGE:msg-u-1:1:UPSERT"
    assert assistant["source_event_id"] == "atlas:ATLAS_ASSISTANT_MESSAGE:msg-a-1:1:UPSERT"
    assert call["source_event_id"] == (
        f"atlas:ATLAS_TOOL_OBSERVATION:tc-1:{TOOL_REVISION_DISPATCH}:UPSERT")
    assert result["source_event_id"] == (
        f"atlas:ATLAS_TOOL_OBSERVATION:tc-1:{TOOL_REVISION_RESULT}:UPSERT")

    outbox = OperationalOutbox(tmp_path / "unified_outbox.sqlite3")
    rows = {row["source_event_id"]: row["payload"]["observation"]
            for row in outbox.poll_pending(50)}
    assert rows["atlas:ATLAS_USER_MESSAGE:msg-u-1:1:UPSERT"]["speaker_role"] == "USER"
    assert rows["atlas:ATLAS_USER_MESSAGE:msg-u-1:1:UPSERT"]["epistemic_kind"] == "USER_ASSERTED"
    assert rows["atlas:ATLAS_ASSISTANT_MESSAGE:msg-a-1:1:UPSERT"]["speaker_role"] == "ATLAS"
    assert rows["atlas:ATLAS_ASSISTANT_MESSAGE:msg-a-1:1:UPSERT"]["epistemic_kind"] == "OBSERVED"
    tool_result = rows[
        f"atlas:ATLAS_TOOL_OBSERVATION:tc-1:{TOOL_REVISION_RESULT}:UPSERT"]
    assert tool_result["speaker_role"] == "TOOL"
    assert tool_result["epistemic_kind"] == "OBSERVED"
    # content_hash 由本地按契约规则重算且入 outbox 前已带上
    for source_event_id, observation in rows.items():
        assert observation["content_hash"] == observation_content_hash(observation)
        assert observation["locator"]["value"].startswith("conv-1/")
    outbox.close()


@pytest.mark.unit
def test_assistant_self_report_is_not_verification(tmp_path) -> None:
    """模型自报不是验证：assistant 观察 epistemic_kind=OBSERVED，content 无
    verification="VERIFIED"（契约 §1.1；验证证据属 ATLAS_VERIFICATION）。"""
    service = _service(tmp_path)
    assert service.capture_assistant_message(
        "conv-1", "msg-a-9", "我已经完成并验证了全部修改。") is not None
    outbox = OperationalOutbox(tmp_path / "unified_outbox.sqlite3")
    rows = [row["payload"]["observation"] for row in outbox.poll_pending(10)]
    assert len(rows) == 1
    observation = rows[0]
    assert observation["epistemic_kind"] == "OBSERVED"
    assert observation["content"].get("verification") != "VERIFIED"
    assert observation["content"]["only_assistant_claim"] is True
    outbox.close()


@pytest.mark.unit
def test_tool_phases_share_object_id_and_verification_is_separate_kind(tmp_path) -> None:
    """dispatch/result/verification 三类分开：同 tool_call_id，revision+phase 区分；
    verification 走 ATLAS_VERIFICATION（speaker ATLAS），失败只有 error result。"""
    service = _service(tmp_path)
    call = service.capture_tool_call("conv-1", "tc-2", "local_shell", {"command": "pytest -q"})
    result = service.capture_tool_result("conv-1", "tc-2", "local_shell", "3 passed",
                                         full_output_path="/blobs/tc-2.log")
    verification = service.capture_tool_verification("conv-1", "tc-2", "local_shell",
                                                     "3 passed", verified=True)
    assert call is not None and result is not None and verification is not None
    assert len({call["source_event_id"], result["source_event_id"],
                verification["source_event_id"]}) == 3
    for observation in (call, result, verification):
        assert observation["source_event_id"].split(":")[2] == "tc-2"

    outbox = OperationalOutbox(tmp_path / "unified_outbox.sqlite3")
    rows = {row["source_event_id"]: row["payload"]["observation"]
            for row in outbox.poll_pending(50)}
    dispatch = rows[f"atlas:ATLAS_TOOL_OBSERVATION:tc-2:{TOOL_REVISION_DISPATCH}:UPSERT"]
    outcome = rows[f"atlas:ATLAS_TOOL_OBSERVATION:tc-2:{TOOL_REVISION_RESULT}:UPSERT"]
    checked = rows[f"atlas:ATLAS_VERIFICATION:tc-2:{TOOL_REVISION_VERIFICATION}:UPSERT"]
    assert dispatch["content"]["phase"] == "dispatch"
    assert dispatch["content"]["arguments"] == {"command": "pytest -q"}
    assert outcome["content"]["phase"] == "result"
    assert outcome["content"]["is_error"] is False
    assert outcome["content"]["full_output_path"] == "/blobs/tc-2.log"
    assert checked["source_kind"] == "ATLAS_VERIFICATION"
    assert checked["speaker_role"] == "ATLAS"
    assert checked["content"]["phase"] == "verification"
    outbox.close()


@pytest.mark.unit
def test_agent_tool_result_reserved_signature(tmp_path) -> None:
    """T02.3 预留：capture_agent_tool_result 带 actor_id，按 THIRD_PARTY 断言记录。"""
    service = _service(tmp_path)
    result = service.capture_agent_tool_result(
        "conv-1", "agent-tc-1", "tool-zcode", "对方声称已完成")
    assert result is not None and result["created"] is True
    outbox = OperationalOutbox(tmp_path / "unified_outbox.sqlite3")
    rows = [row["payload"]["observation"] for row in outbox.poll_pending(10)]
    observation = rows[0]
    assert observation["source_kind"] == "ATLAS_AGENT_TOOL_RESULT"
    assert observation["speaker_role"] == "THIRD_PARTY"
    assert observation["epistemic_kind"] == "THIRD_PARTY_ASSERTED"
    assert observation["content"]["actor_id"] == "tool-zcode"
    outbox.close()


@pytest.mark.unit
def test_same_real_id_reentry_captures_once_and_conflict_keeps_first(tmp_path) -> None:
    """同一 ID 重入只产生一次；同 ID 异内容 first-write-wins（不覆盖原文）。"""
    service = _service(tmp_path)
    first = service.capture_user_message("conv-1", "msg-u-1", "原始文本")
    again = service.capture_user_message("conv-1", "msg-u-1", "原始文本")
    assert first is not None and first["created"] is True
    assert again is not None and again["created"] is False
    assert again.get("deduplicated") is True

    # 新进程（新 _seen）同 outbox：同 ID 异内容 → 本地冲突，保留第一次内容。
    second_process = _service(tmp_path)
    conflict = second_process.capture_user_message("conv-1", "msg-u-1", "被篡改的文本")
    assert conflict is not None and conflict["created"] is False
    assert conflict.get("conflict") is True

    outbox = OperationalOutbox(tmp_path / "unified_outbox.sqlite3")
    rows = outbox.poll_pending(10)
    assert len(rows) == 1
    assert rows[0]["payload"]["observation"]["content"]["text"] == "原始文本"
    outbox.close()


@pytest.mark.unit
def test_restart_recovery_same_outbox_no_duplicates(tmp_path) -> None:
    """重启恢复：outbox 有 2 条未 flush → 新 CaptureService 同文件 → flush →
    服务端无重复（同 ID 只投一次，再 flush 零待投）。"""
    path = tmp_path / "unified_outbox.sqlite3"

    # 进程一：采集 2 条（flush 失败 → 本地兜底留在 outbox），随后"退出"。
    first = CaptureService(facade=_RecordingFacade(fail_first=5), outbox_path=path,
                           event_class=EVENT_CLASS)
    assert first.capture_user_message("conv-r", "msg-1", "第一条原话") is not None
    assert first.capture_assistant_message("conv-r", "msg-2", "第一条回复") is not None
    stats_after_failure = asyncio.run(first.flush(backoff_seconds=0.0))
    assert stats_after_failure["acked"] == 0
    assert stats_after_failure["outbox"]["pending"] == 2
    first.close()

    # 进程二（重启后）：同一耐久 outbox 文件恢复 → flush 全部 ACK。
    facade = _RecordingFacade()
    second = CaptureService(facade=facade, outbox_path=path, event_class=EVENT_CLASS)
    report = asyncio.run(second.flush(backoff_seconds=0.0))
    assert report["acked"] == 2, report
    assert report["outbox"]["pending"] == 0

    final = asyncio.run(second.flush(backoff_seconds=0.0))
    assert final["sent"] == 0
    sent_ids = [observation["source_event_id"]
                for batch in facade.batches
                for observation in batch["observations"]]
    assert len(sent_ids) == 2 and len(set(sent_ids)) == 2
    second.close()


@pytest.mark.unit
def test_capture_failure_never_raises_and_reports_error(tmp_path) -> None:
    """护栏：底层失败（坏 outbox 路径）只返回 error 结果，绝不向调用方抛异常。"""
    broken = CaptureService(facade=_RecordingFacade(),
                            outbox_path=tmp_path / "blocked-directory",
                            event_class=EVENT_CLASS)
    (tmp_path / "blocked-directory").mkdir()  # sqlite 无法在目录路径上建库

    result = broken.capture_user_message("conv-1", "msg-1", "文本")
    assert result is not None and result["created"] is False
    assert "error" in result


@pytest.mark.unit
def test_capture_flush_loop_drains_and_wakes_on_enqueue(tmp_path) -> None:
    """flush 循环事件驱动：启动排空遗留行；入队即唤醒（不依赖空闲 tick）。"""
    from atlas.memory.capture import capture_flush_loop

    facade = _RecordingFacade()
    service = _service(tmp_path, facade=facade)
    assert service.capture_user_message("conv-1", "msg-legacy", "遗留行") is not None

    async def _scenario() -> None:
        task = asyncio.create_task(capture_flush_loop(service, idle_seconds=30.0))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not facade.batches:
            await asyncio.sleep(0.02)
        assert facade.batches, "启动排空（上一进程遗留行）未发生"
        facade.batches.clear()
        # 入队即唤醒：idle 30s 下批次仍立即出现，证明走的是唤醒而不是周期轮询。
        assert service.capture_user_message("conv-1", "msg-live", "入队即唤醒") is not None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not facade.batches:
            await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_scenario())
    sent = [observation["source_event_id"] for batch in facade.batches
            for observation in batch["observations"]]
    assert sent == ["atlas:ATLAS_USER_MESSAGE:msg-live:1:UPSERT"]
    assert service.stats()["pending"] == 0


@pytest.mark.unit
def test_capture_enabled_default_on_and_configurable() -> None:
    """采集默认开启（capture_mode 缺省 enabled），显式 disabled 才关。"""
    assert capture_enabled(_Cfg({
        "memory.unified.enabled": True})) is True
    assert capture_enabled(_Cfg({
        "memory.unified.enabled": True,
        "memory.unified.capture_mode": "enabled"})) is True
    assert capture_enabled(_Cfg({
        "memory.unified.enabled": True,
        "memory.unified.capture_mode": "disabled"})) is False
    assert capture_enabled(_Cfg({"memory.unified.enabled": False})) is False
    assert capture_enabled(None) is False


@pytest.mark.unit
def test_singleton_configure_get_reset(monkeypatch) -> None:
    """configure → get 返回同一实例；disabled → None；reset 后回到未组装态。"""
    from atlas.memory import capture as capture_module

    monkeypatch.setattr(capture_module, "_load_config",
                        lambda: _Cfg({"memory.unified.enabled": False}))
    assert capture_module.configure_capture_service() is None
    assert capture_module.get_capture_service() is None

    service = capture_module.configure_capture_service(
        config=_Cfg({"memory.unified.enabled": True,
                     "memory.unified.capture_mode": "enabled"}),
        event_class=EVENT_CLASS)
    assert service is not None
    assert capture_module.get_capture_service() is service
    capture_module.reset_capture_service()
    assert capture_module.get_capture_service() is None


@pytest.mark.unit
def test_message_id_mapping_and_revision_helpers() -> None:
    """session_sync 与 capture 用同一稳定 ID 体系（message_uid，legacy row id 回落）。"""
    assert atlas_message_object_id({"message_uid": "uid-1"}) == "uid-1"
    assert atlas_message_object_id({"id": "42"}) == "42"          # legacy row id
    assert atlas_message_object_id({"message_uid": "", "id": "7"}) == "7"
    assert atlas_message_object_id("raw-id") == "raw-id"
    assert atlas_message_object_id({"id": ""}) == ""
    assert next_source_revision("1") == "2"
    assert next_source_revision(3) == "4"
    assert next_source_revision("r7") == "r7.2"


# ------------------------------------------------------- unit：run_phases 护栏


def _run_state(message: str = "记住我喜欢简洁回复") -> Any:
    from atlas.agent.run_phases import RunCallbacks, RunRequest, _RunState

    request = RunRequest(message=message, conversation_id="conv-guard")
    runtime = type("Runtime", (), {})()
    runtime.model = "test-model"
    runtime.verify_nudge_sent = False
    runtime.changed_paths = set()
    runtime.verification_passed = False
    runtime.run_id = "run-1"
    runtime.external_tool_context = False
    state = _RunState(request=request, callbacks=RunCallbacks(), message=message)
    state.runtime = runtime
    state.result = {"messages": [AIMessage(content="好的，已记下。")]}
    return state


def _finalize_agent() -> Any:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from atlas.agent import AgentOrchestrator

    model_mgr = MagicMock()
    model_mgr.current_model = "test-model"
    agent = AgentOrchestrator(model_mgr, AsyncMock(), MagicMock())
    agent._emit_hook = AsyncMock(return_value=None)
    agent._reflection = SimpleNamespace(reflect=AsyncMock(return_value=None))
    agent.trajectory_reviewer = SimpleNamespace(evidence=[])
    return agent


@pytest.mark.unit
def test_run_phases_finalize_completes_when_capture_raises(monkeypatch) -> None:
    """护栏单测：capture 抛异常时 _phase_finalize 照常产出 done（聊天不受影响）。"""
    from atlas.agent.run_phases import _phase_finalize
    from atlas.engine import session_sync

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("capture service exploded")

    monkeypatch.setattr(session_sync, "latest_session_message_id",
                        lambda *_a, **_k: "assistant-1")
    monkeypatch.setattr(session_sync, "latest_session_message",
                        lambda *_a, **_k: {"id": "assistant-1", "role": "assistant",
                                           "content": "好的，已记下。",
                                           "created_at": "2026-10-06T00:00:00+00:00"})
    monkeypatch.setattr(session_sync, "read_session_all_messages", lambda *_a, **_k: [])
    monkeypatch.setattr("atlas.memory.capture.get_capture_service", _boom)

    state = _run_state()

    async def _collect() -> list[dict[str, Any]]:
        return [event async for event in _phase_finalize(_finalize_agent(), state)]

    events = asyncio.run(_collect())
    done = [event for event in events if event.get("type") == "done"]
    assert done and done[0]["message_id"] == "assistant-1"
    assert not [event for event in events if event.get("type") == "error"]


@pytest.mark.unit
def test_run_user_message_capture_swallows_capture_errors(monkeypatch) -> None:
    """护栏单测：用户消息捕获内部失败只记日志；成功路径把真实 ID 原样传给 capture。"""
    from atlas.agent.run_phases import _capture_run_user_message
    from atlas.engine import session_sync

    persisted = {"id": "user-uid-1", "role": "user",
                 "content": "记住我喜欢简洁回复",
                 "created_at": "2026-10-06T09:00:00+00:00"}
    monkeypatch.setattr(session_sync, "latest_session_message",
                        lambda *_a, **_k: dict(persisted))
    monkeypatch.setattr(session_sync, "read_session_messages", lambda *_a, **_k: [])

    calls: list[tuple[Any, ...]] = []

    class _Ok:
        def capture_user_message(self, *args: Any) -> dict[str, Any]:
            calls.append(args)
            return {"created": True}

    async def _scenario(monkeypatch_module: Any) -> None:
        state = _run_state()
        monkeypatch_module.setattr("atlas.memory.capture.get_capture_service", lambda: _Ok())
        await _capture_run_user_message(state)          # 成功路径：参数即真实 ID
        assert calls == [("conv-guard", "user-uid-1",
                          "记住我喜欢简洁回复", "2026-10-06T09:00:00+00:00")]

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("capture down")

        monkeypatch_module.setattr("atlas.memory.capture.get_capture_service", _boom)
        await _capture_run_user_message(state)          # 失败路径：不抛异常

    asyncio.run(_scenario(monkeypatch))


@pytest.mark.unit
def test_run_user_message_capture_prefers_matching_persisted_message(monkeypatch) -> None:
    """同回合被 steer 追加消息时，优先取与本次输入一致的持久化用户消息。"""
    from atlas.agent.run_phases import _capture_run_user_message
    from atlas.engine import session_sync

    steer_message = {"id": "user-uid-steer", "role": "user",
                     "content": "等一下，先停一下", "created_at": None}
    monkeypatch.setattr(session_sync, "latest_session_message",
                        lambda *_a, **_k: dict(steer_message))

    original = {"id": "user-uid-original", "role": "user",
                "content": "记住我喜欢简洁回复", "created_at": None}
    monkeypatch.setattr(session_sync, "read_session_messages",
                        lambda *_a, **_k: [dict(original), dict(steer_message)])

    calls: list[tuple[Any, ...]] = []

    class _Ok:
        def capture_user_message(self, *args: Any) -> dict[str, Any]:
            calls.append(args)
            return {"created": True}

    monkeypatch.setattr("atlas.memory.capture.get_capture_service", lambda: _Ok())
    asyncio.run(_capture_run_user_message(_run_state()))
    assert calls == [("conv-guard", "user-uid-original", "记住我喜欢简洁回复", None)]


# ------------------------------------------------------------------ 集成


def _fetch_records(h: Any) -> list[dict[str, Any]]:
    response = h.api("GET", "/v1/unified/records", params={"limit": 200})
    assert response.status_code == 200, response.text[:300]
    return response.json()["items"]


def _wait_for_records(h: Any, predicate: Any, *, timeout: float = 90.0,
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


def _in_session(item: dict[str, Any], session_id: str) -> bool:
    return _obs_content(item).get("session_id") == session_id


def _of_kind(item: dict[str, Any], source_kind: str) -> bool:
    return _projection(item).get("source_kind") == source_kind


@pytest.mark.integration
def test_chat_capture_user_and_assistant_observations(um) -> None:
    """主判据：h.chat 真实 WS → flush → records 读到 USER+ATLAS 观察（稳定 ID
    locator）；同会话再次 h.chat 无重复观察（同 ID 幂等，created 不增）。"""
    session_id = um.chat("记住我喜欢简洁回复")["conversation_id"]

    user_hits = _wait_for_records(
        um, lambda item: _in_session(item, session_id)
        and _of_kind(item, "ATLAS_USER_MESSAGE"),
        description=f"session {session_id} 的 USER 观察")
    assert len(user_hits) == 1
    user_record = user_hits[0]
    user_projection = _projection(user_record)
    assert user_projection["speaker_role"] == "USER"
    assert _obs_content(user_record)["text"] == "记住我喜欢简洁回复"
    # locator 指向稳定 session/message ID（SessionDB message_uid 体系）
    locator_value = str((user_projection.get("locator") or {}).get("value") or "")
    assert locator_value.startswith(f"{session_id}/")
    message_uid = locator_value.split("/", 1)[1]
    assert message_uid
    assert _source_event_id(user_record) == (
        f"atlas:ATLAS_USER_MESSAGE:{message_uid}:1:UPSERT")

    assistant_hits = _wait_for_records(
        um, lambda item: _in_session(item, session_id)
        and _of_kind(item, "ATLAS_ASSISTANT_MESSAGE"),
        description=f"session {session_id} 的 ATLAS 观察")
    assert len(assistant_hits) == 1
    assert _projection(assistant_hits[0])["speaker_role"] == "ATLAS"
    assert _obs_content(assistant_hits[0])["text"]  # Atlas 当次输出已落地

    # 同会话第二次 h.chat：旧消息不被重复采集（同 ID 只产生一次观察）。
    second = um.chat("再聊一句就好", session_id=session_id)
    assert second["status"] == "completed"
    deadline = time.monotonic() + 60.0
    total = 0
    while time.monotonic() < deadline:
        message_items = [item for item in _fetch_records(um)
                         if _in_session(item, session_id)
                         and _of_kind(item, "ATLAS_USER_MESSAGE")
                         or _in_session(item, session_id)
                         and _of_kind(item, "ATLAS_ASSISTANT_MESSAGE")]
        total = len(message_items)
        if total >= 4:
            break
        time.sleep(1.0)
    assert total == 4, f"两次聊天应恰好 4 条消息观察，实际 {total}"
    # 第一次的 USER 观察仍恰好一条（无重复行、无重复事件）
    still_one = [item for item in _fetch_records(um)
                 if _source_event_id(item) == _source_event_id(user_record)]
    assert len(still_one) == 1


@pytest.mark.integration
def test_tool_capture_dispatch_and_result_observations(um) -> None:
    """工具捕获：真实派发后 records 出现 dispatch 与 result 两类观察 —— 同
    tool_call_id（source_object_id 相同），revision+phase 区分。

    说明：terminal 经 Atlas handler 翻译为 local_shell 进入 execute_tools_node，
    Atlas 侧执行使用合成 tool_call_id（``atlas:{uuid}``，与 WS tool.started/
    tool.completed 事件同源）；模型面向的 provider call id（call_fake_N）是
    外层包装，不是 Atlas 执行身份 —— 捕获的对象 ID 必须能在真实收据里找到。
    """
    receipt = um.tool("terminal", {"command": "echo um-cap-ok", "shell": "powershell"})
    assert receipt["status"] == "completed"
    assert not receipt["is_error"], receipt
    session_id = receipt["conversation_id"]
    receipt_ids = {item["tool_call_id"] for item in receipt["receipts"]}

    def _tool_obs(phase: str) -> Any:
        def _match(item: dict[str, Any]) -> bool:
            # _obs_content 已是观察原 content（本模块头部的投影层级说明）：
            # phase/tool/session_id 就在这一层，不能再下钻 content["text"] ——
            # dispatch content 没有 text 键，消息记录的 text 是字符串。
            text = _obs_content(item)
            return (text.get("session_id") == session_id
                    and text.get("phase") == phase
                    and text.get("tool") == "local_shell")
        return _match

    dispatch_hits = _wait_for_records(
        um, _tool_obs("dispatch"), description="local_shell dispatch 观察")
    result_hits = _wait_for_records(
        um, _tool_obs("result"), description="local_shell result 观察")
    assert len(dispatch_hits) == 1 and len(result_hits) == 1
    dispatch_seid = _source_event_id(dispatch_hits[0])
    result_seid = _source_event_id(result_hits[0])
    object_id, dispatch_revision = _seid_object_revision(dispatch_hits[0])
    result_object_id, result_revision = _seid_object_revision(result_hits[0])
    assert result_object_id == object_id          # 同一工具调用对象
    assert dispatch_seid != result_seid
    assert dispatch_revision == TOOL_REVISION_DISPATCH
    assert result_revision == TOOL_REVISION_RESULT
    assert object_id in receipt_ids, (
        f"捕获的对象 ID {object_id} 必须是真实 WS 收据里的 tool_call_id: {receipt_ids}")
    for item in (dispatch_hits[0], result_hits[0]):
        content = _obs_content(item)
        assert _projection(item)["speaker_role"] == "TOOL"
        assert item["epistemic_kind"] == "OBSERVED"
        assert content["tool"] == "local_shell"
        assert _projection(item)["source_kind"] == "ATLAS_TOOL_OBSERVATION"
    assert _obs_content(result_hits[0]).get("is_error") is False


@pytest.mark.integration
def test_failing_tool_result_captured_with_error_marker(um) -> None:
    """异常工具：error result 观察存在且服务端照收（可读 = 接受）。

    用缺 command 的 terminal（翻译为 local_shell 后空命令被参数校验拒绝）——
    Atlas 侧 execute_tools_node 真实执行失败，异常路径产生 is_error 的完整
    结果观察（空命令不再静默启动一个"成功"的空 shell）。
    """
    receipt = um.tool("terminal", {"shell": "powershell"})
    session_id = receipt["conversation_id"]
    receipt_ids = {item["tool_call_id"] for item in receipt["receipts"]}

    error_hits = _wait_for_records(
        um, lambda item: (_obs_content(item).get("session_id") == session_id
                          and _obs_content(item).get("phase") == "result"
                          and _obs_content(item).get("tool") == "local_shell"
                          and _obs_content(item).get("is_error") is True),
        description="local_shell 的 error result 观察")
    assert len(error_hits) == 1
    object_id, _revision = _seid_object_revision(error_hits[0])
    assert object_id in receipt_ids, (
        f"捕获的对象 ID {object_id} 必须是真实 WS 收据里的 tool_call_id: {receipt_ids}")
    content = _obs_content(error_hits[0])
    assert _projection(error_hits[0])["speaker_role"] == "TOOL"
    assert error_hits[0]["epistemic_kind"] == "OBSERVED"  # 失败也是 OBSERVED 事实
    assert content["error_category"] == "tool"


@pytest.mark.integration
def test_model_self_report_is_not_verification(um) -> None:
    """任务书判据语义：assistant 声称完成的观察不是验证 —— epistemic_kind=
    OBSERVED 且 content.verification 不存在或 != "VERIFIED"。"""
    session_id = um.chat("请直接回复完成两个字。")["conversation_id"]
    _wait_for_records(
        um, lambda item: _in_session(item, session_id)
        and _of_kind(item, "ATLAS_ASSISTANT_MESSAGE"),
        description=f"session {session_id} 的 ATLAS 观察")
    assistant_items = [item for item in _fetch_records(um)
                       if _in_session(item, session_id)
                       and _of_kind(item, "ATLAS_ASSISTANT_MESSAGE")]
    assert assistant_items
    for item in assistant_items:
        assert item["epistemic_kind"] != "VERIFIED"       # 无 VERIFIED 语义等价物
        assert item["epistemic_kind"] == "OBSERVED"
        verification = _obs_content(item).get("verification")
        assert verification != "VERIFIED"
        assert _obs_content(item).get("only_assistant_claim") is True
