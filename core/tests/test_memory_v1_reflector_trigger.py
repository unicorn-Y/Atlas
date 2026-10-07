"""Unit and integration tests for S4 Memory Reflector triggers (idle/daily/threshold).

Validates:
  1. Trigger when threshold met (count >= threshold or tokens >= threshold).
  2. Skip when below threshold (0 LLM calls, saving tokens).
  3. Mastra dynamic threshold logic (thresholds.ts).
  4. Execution submits POST /v1/unified/consolidation:apply and persists receipt.
  5. Reflector failure during chat turn does not block the conversation.
  6. Server lifespan reflector idle loop periodic execution and clean cancellation.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas.memory.reflector import (
    DEFAULT_RECORD_COUNT_THRESHOLD,
    DEFAULT_TOKEN_THRESHOLD,
    MemoryReflector,
    reflector_idle_loop,
    should_reflect,
)


class MockModelRouter:
    def __init__(self, answer: dict[str, Any] | list[Any] | str):
        self.answer = answer
        self.calls: list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]] = []

    async def complete_for(
        self, model_id: str, purpose: str, messages: list[dict[str, Any]], **kwargs: Any
    ):
        self.calls.append((model_id, purpose, messages, kwargs))
        if isinstance(self.answer, str):
            text = self.answer
        else:
            text = json.dumps(self.answer, ensure_ascii=False)
        return type(
            "Result",
            (),
            {
                "text": text,
                "usage": {"prompt_tokens": 150, "completion_tokens": 60},
            },
        )()


class MockModelManager:
    current_model = "test-model-flash"

    def __init__(self, router: MockModelRouter):
        self.model_router = router

    def list_models(self):
        return [{"id": "test-model-flash", "litellm_model": "openai/test-model-flash"}]


class MockUnifiedClient:
    def __init__(self, records: list[dict[str, Any]] | None = None):
        self.records = records or []
        self.calls: list[tuple[str, str, Any]] = []
        self.applied_payloads: list[dict[str, Any]] = []

    async def list_records(self, *, status: str = "ACTIVE", facet: str | None = None, limit: int = 50):
        self.calls.append(("GET", "/v1/unified/records", {"status": status, "limit": limit}))
        return {"items": self.records, "next_cursor": None}

    async def call(self, method: str, path: str, *, json: Any = None, params: Any = None):
        self.calls.append((method, path, json or params))
        if method == "POST" and path == "/v1/unified/consolidation:apply":
            self.applied_payloads.append(json)
            ops = (json or {}).get("operations", [])
            return {
                "total": len(ops),
                "accepted_count": len(ops),
                "rejected_count": 0,
                "results": [{"index": i, "op": op.get("op"), "status": "ACCEPTED"} for i, op in enumerate(ops)],
            }
        if method == "GET" and path == "/v1/unified/records":
            return {"items": self.records, "next_cursor": None}
        return {}


def make_record(ref: str, text: str, facet: str = "FACT", date: str = "2026-09-24") -> dict[str, Any]:
    return {
        "record_ref": ref,
        "facet": facet,
        "lifecycle": "ACTIVE",
        "recorded_at": f"{date}T10:00:00Z",
        "valid_time": {"valid_from": date},
        "content": {"text": text},
    }


# ----------------------------------------------------------------------
# 1 & 2: Threshold checks (count, tokens, dynamic threshold)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflector_triggers_when_count_threshold_met():
    """到达记录条数阈值时触发反思。"""
    records = [
        make_record(f"memory:rec-{i}", f"用户在杭州余杭从事跨境电商测试记录 {i}")
        for i in range(5)
    ]
    client = MockUnifiedClient(records=records)
    router = MockModelRouter({
        "operations": [
            {
                "op": "MERGE",
                "refs": ["memory:rec-0", "memory:rec-1"],
                "into_text": "用户在杭州余杭从事跨境电商测试工作。",
                "keep_ref": "memory:rec-0",
            }
        ]
    })
    mgr = MockModelManager(router)
    reflector = MemoryReflector(mgr, client=client)

    result = await reflector.trigger_if_threshold_met(
        subject="test-user", count_threshold=5, auto_apply=True
    )

    assert result is not None
    assert result.reflected is True
    assert len(router.calls) == 1
    assert router.calls[0][1] == "memory_reflect"
    assert result.applied_count == 1
    assert result.receipt is not None
    assert result.receipt["applied_count"] == 1


@pytest.mark.asyncio
async def test_reflector_triggers_when_token_threshold_met():
    """未达条数但达到 token 阈值时触发反思。"""
    long_text = "用户详细记录了一段长文本 " * 200  # ~1600 tokens
    records = [
        make_record("memory:rec-long-1", long_text),
        make_record("memory:rec-long-2", long_text),
    ]
    assert len(records) < 5  # < count threshold
    assert should_reflect(records, count_threshold=5, token_threshold=2000)

    client = MockUnifiedClient(records=records)
    router = MockModelRouter({"operations": []})
    mgr = MockModelManager(router)
    reflector = MemoryReflector(mgr, client=client)

    result = await reflector.trigger_if_threshold_met(
        subject="test-user", count_threshold=5, token_threshold=2000
    )
    assert result is not None
    assert result.reflected is True
    assert len(router.calls) == 1


@pytest.mark.asyncio
async def test_reflector_skips_when_below_threshold():
    """未到阈值不触发反思，大模型 0 次调用（省 token）。"""
    records = [
        make_record("memory:rec-1", "用户喜欢吃面条。"),
        make_record("memory:rec-2", "用户今天跑步了。"),
    ]
    client = MockUnifiedClient(records=records)
    router = MockModelRouter({"operations": []})
    mgr = MockModelManager(router)
    reflector = MemoryReflector(mgr, client=client)

    # trigger_if_threshold_met returns None when below threshold
    result = await reflector.trigger_if_threshold_met(
        subject="test-user", count_threshold=5, token_threshold=2000
    )
    assert result is None
    assert len(router.calls) == 0

    # run_reflection_cycle without force marks skip_reason BELOW_THRESHOLD
    cycle_result = await reflector.run_reflection_cycle(
        subject="test-user", force=False, count_threshold=5, token_threshold=2000
    )
    assert cycle_result.reflected is False
    assert cycle_result.skip_reason == "BELOW_THRESHOLD"
    assert len(router.calls) == 0
    assert cycle_result.receipt is not None
    assert cycle_result.receipt["reflected"] is False


@pytest.mark.asyncio
async def test_reflector_mastra_dynamic_threshold_logic():
    """测试 Mastra thresholds.ts 动态预算阈值逻辑字典形态。"""
    records = [
        make_record(f"memory:rec-{i}", f"测试短句 {i}") for i in range(3)
    ]
    # token_threshold as dict: min=5000, max=10000 -> calculate_dynamic_threshold
    threshold_cfg = {"min": 5000, "max": 10000}
    assert not should_reflect(records, count_threshold=10, token_threshold=threshold_cfg)

    # When records expand past threshold:
    long_records = [
        make_record(f"memory:rec-long-{i}", "这是一段很长很长的记忆内容！" * 300)
        for i in range(4)
    ]
    assert should_reflect(long_records, count_threshold=10, token_threshold=threshold_cfg)


# ----------------------------------------------------------------------
# 3: Submit apply and receipt persistence
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_submits_consolidation_apply_and_logs_receipt(tmp_path, monkeypatch):
    """触发后确实提交了 apply，并落日志与收据。"""
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))

    records = [
        make_record("memory:rec-a", "设备记录：目前使用一台 Windows 笔记本。"),
        make_record("memory:rec-b", "设备记录更新：用户更换为了 MacBook Pro。"),
        make_record("memory:rec-c", "用户在杭州余杭从事跨境电商工作。"),
        make_record("memory:rec-d", "公司在杭州余杭，主营跨境电商业务。"),
        make_record("memory:rec-e", "用户花生过敏。"),
    ]
    client = MockUnifiedClient(records=records)
    router = MockModelRouter({
        "operations": [
            {
                "op": "SUPERSEDE",
                "old_ref": "memory:rec-a",
                "new_ref": "memory:rec-b",
                "reason": "设备更新为 MacBook Pro",
            },
            {
                "op": "MERGE",
                "refs": ["memory:rec-c", "memory:rec-d"],
                "into_text": "用户在杭州余杭工作，主营跨境电商业务。",
                "keep_ref": "memory:rec-c",
            },
        ]
    })
    mgr = MockModelManager(router)
    reflector = MemoryReflector(mgr, client=client)

    result = await reflector.run_reflection_cycle(
        subject="subject-default", force=True, auto_apply=True
    )

    assert result.reflected is True
    assert result.applied_count == 2
    assert len(client.applied_payloads) == 1
    applied_ops = client.applied_payloads[0]["operations"]
    assert len(applied_ops) == 2
    assert applied_ops[0]["op"] == "SUPERSEDE"
    assert applied_ops[1]["op"] == "MERGE"

    # Verify receipt generated
    assert result.receipt is not None
    assert result.receipt["applied_count"] == 2
    assert result.receipt["subject"] == "subject-default"

    # Verify receipt file written to disk
    receipt_dir = tmp_path / "reflection_receipts"
    receipt_files = list(receipt_dir.glob("*.json"))
    assert len(receipt_files) == 1
    saved_receipt = json.loads(receipt_files[0].read_text(encoding="utf-8"))
    assert saved_receipt["applied_count"] == 2
    assert saved_receipt["receipt_id"] == result.receipt["receipt_id"]


# ----------------------------------------------------------------------
# 4: Failure does not block chat (run_phases.py)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflector_failure_does_not_block_chat():
    """反思者触发异常时，不阻塞聊天流程，正常输出 done 事件与错误收据。"""
    from langchain_core.messages import AIMessage
    from atlas.agent.run_phases import RunCallbacks, RunRequest, _RunState, _phase_finalize

    # Create dummy agent with unified memory enabled
    agent = MagicMock()
    agent._memory = MagicMock()
    agent._memory._unified_reads_enabled.return_value = True
    agent._memory.save_conversation_metadata = AsyncMock()

    # Inject a failing reflector
    failing_reflector = MagicMock()
    failing_reflector.trigger_if_threshold_met = AsyncMock(
        side_effect=RuntimeError("MemoryOS consolidation API 503 connection error")
    )
    agent._memory_reflector = failing_reflector
    agent._emit_hook = AsyncMock()

    request = RunRequest(
        conversation_id="conv-test-resilience",
        message="你好",
    )
    callbacks = RunCallbacks()
    runtime = MagicMock()
    runtime.run_id = "run-test"
    runtime.model = "test-model"
    runtime.verify_nudge_sent = True
    runtime.changed_paths = []
    runtime.external_tool_context = False

    state = _RunState(
        request=request,
        callbacks=callbacks,
        message="你好",
        runtime=runtime,
        result={"messages": [AIMessage(content="你好！我是你的助理。")]},
    )

    with patch("atlas.agent.run_phases._capture_run_assistant_message", new=AsyncMock()), \
         patch("atlas.engine.session_sync.latest_session_message_id", return_value="msg-123"):
        events = []
        async for event in _phase_finalize(agent, state):
            events.append(event)

    event_types = [e.get("type") for e in events]
    # Verify: reflector failure event was emitted without crashing the flow
    assert "memory_reflection_error" in event_types
    error_event = next(e for e in events if e.get("type") == "memory_reflection_error")
    assert "503 connection error" in error_event["detail"]
    # Verify: done event was reached successfully (chat was NOT blocked!)
    assert "done" in event_types
    assert events[-1]["type"] == "done"


# ----------------------------------------------------------------------
# 5: Idle loop background task execution
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflector_idle_loop_periodic_check_and_cancel():
    """后台空闲任务周期检测与优雅取消。"""
    client = MockUnifiedClient(records=[make_record("m:1", "短记录")])
    mgr = MockModelManager(MockModelRouter({"operations": []}))
    reflector = MemoryReflector(mgr, client=client)

    task = asyncio.create_task(
        reflector_idle_loop(reflector, check_interval=0.01, subject="subject-default")
    )
    # Let it run one or two ticks
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
