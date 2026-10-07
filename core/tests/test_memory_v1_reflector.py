"""Unit tests for Atlas Memory V1 S4 Reflector (core/atlas/memory/reflector.py)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from atlas.memory.reflector import (
    DEFAULT_RECORD_COUNT_THRESHOLD,
    DEFAULT_TOKEN_THRESHOLD,
    MAX_PROFILE_TOKENS,
    MemoryReflector,
    build_reflector_system_prompt,
    build_reflector_user_prompt,
    parse_reflector_output,
    should_reflect,
    validate_compression,
    validate_operations_local,
    validate_traceability,
)


class MockRouter:
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
        return type("Result", (), {
            "text": text,
            "usage": {"prompt_tokens": 120, "completion_tokens": 45},
        })()


class MockModelManager:
    current_model = "test-model-flash"

    def __init__(self, router: MockRouter):
        self.model_router = router

    def list_models(self):
        return [{"id": "test-model-flash", "litellm_model": "deepseek/test-model-flash"}]


class MockClient:
    def __init__(self, apply_response: dict[str, Any] | None = None):
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.apply_response = apply_response or {
            "total": 1,
            "accepted_count": 1,
            "rejected_count": 0,
            "results": [{"index": 0, "op": "MERGE", "status": "ACCEPTED"}],
        }

    async def call(self, method: str, path: str, *, json: Any = None, **kwargs: Any):
        self.calls.append((method, path, json))
        return self.apply_response


def sample_record(ref: str, text: str, facet: str = "FACT", date: str = "2026-09-24") -> dict[str, Any]:
    return {
        "record_ref": ref,
        "facet": facet,
        "lifecycle": "ACTIVE",
        "recorded_at": f"{date}T10:00:00Z",
        "valid_time": {"valid_from": date},
        "content": {"text": text},
    }


def test_should_reflect_precheck_skips_llm_below_threshold():
    records = [
        sample_record("mem:1", "用户喜欢吃面条。"),
        sample_record("mem:2", "用户今天跑步了。"),
    ]
    # 2 records, < 2000 tokens
    assert not should_reflect(records, count_threshold=5, token_threshold=2000)

    # Calling reflect() with under-threshold input should skip model
    router = MockRouter({"operations": []})
    reflector = MemoryReflector(MockModelManager(router))
    res = asyncio.run(reflector.reflect("user-1", records))
    assert not res.reflected
    assert res.skip_reason == "BELOW_THRESHOLD"
    assert len(router.calls) == 0


def test_should_reflect_triggers_when_thresholds_met():
    # Trigger by count (>= 5 records)
    records_5 = [sample_record(f"mem:{i}", f"记忆条目 {i}") for i in range(5)]
    assert should_reflect(records_5, count_threshold=5, token_threshold=2000)

    # Trigger by tokens (< 5 records but >= token_threshold)
    long_text = "重要记忆内容 " * 500  # large token size
    records_large = [sample_record("mem:big", long_text)]
    assert should_reflect(records_large, count_threshold=5, token_threshold=500)


def test_merge_operation_proposal_and_local_validation():
    rec1 = sample_record("mem:1", "用户在杭州从事跨境电商。")
    rec2 = sample_record("mem:2", "用户在杭州做跨境电商业务。")
    records = [rec1, rec2]

    # Valid MERGE
    ops = [
        {
            "op": "MERGE",
            "refs": ["mem:1", "mem:2"],
            "into_text": "用户在杭州从事跨境电商业务。",
            "keep_ref": "mem:1",
        }
    ]
    valid, rejected = validate_operations_local(ops, records)
    assert len(valid) == 1
    assert len(rejected) == 0
    assert valid[0]["op"] == "MERGE"
    assert valid[0]["keep_ref"] == "mem:1"

    # Invalid MERGE: unknown ref
    ops_bad_ref = [
        {
            "op": "MERGE",
            "refs": ["mem:1", "mem:nonexistent"],
            "into_text": "合并内容",
        }
    ]
    valid, rejected = validate_operations_local(ops_bad_ref, records)
    assert len(valid) == 0
    assert len(rejected) == 1
    assert "UNKNOWN_REF" in rejected[0]["reason"]

    # Invalid MERGE: only 1 ref
    ops_single_ref = [
        {
            "op": "MERGE",
            "refs": ["mem:1"],
            "into_text": "无法单条合并",
        }
    ]
    valid, rejected = validate_operations_local(ops_single_ref, records)
    assert len(valid) == 0
    assert len(rejected) == 1
    assert "INVALID_REFS" in rejected[0]["reason"]


def test_supersede_operation_proposal_and_validation():
    rec_old = sample_record("mem:old", "用户使用 Windows 笔记本。")
    rec_new = sample_record("mem:new", "用户更换为 MacBook Pro。")
    records = [rec_old, rec_new]

    # Valid SUPERSEDE
    ops = [
        {
            "op": "SUPERSEDE",
            "old_ref": "mem:old",
            "new_ref": "mem:new",
            "reason": "设备升级更换为 MacBook",
        }
    ]
    valid, rejected = validate_operations_local(ops, records)
    assert len(valid) == 1
    assert len(rejected) == 0
    assert valid[0]["old_ref"] == "mem:old"
    assert valid[0]["new_ref"] == "mem:new"

    # Self-supersede rejected
    ops_self = [
        {
            "op": "SUPERSEDE",
            "old_ref": "mem:old",
            "new_ref": "mem:old",
            "reason": "自我替换",
        }
    ]
    valid, rejected = validate_operations_local(ops_self, records)
    assert len(valid) == 0
    assert "SELF_SUPERSEDE" in rejected[0]["reason"]


def test_rollup_day_and_week_validation():
    rec1 = sample_record("mem:d1", "周一完成需求评审。", date="2026-09-24")
    rec2 = sample_record("mem:d2", "周一修复了登录缺陷。", date="2026-09-24")
    records = [rec1, rec2]

    # Valid ROLLUP_DAY
    ops = [
        {
            "op": "ROLLUP_DAY",
            "date": "2026-09-24",
            "refs": ["mem:d1", "mem:d2"],
            "text": "2026-09-24：完成需求评审并修复登录缺陷。",
        },
        {
            "op": "ROLLUP_WEEK",
            "date": "2026-09-24",
            "refs": ["mem:d1", "mem:d2"],
            "text": "本周主要完成需求与缺陷修复。",
        },
    ]
    valid, rejected = validate_operations_local(ops, records)
    assert len(valid) == 2
    assert len(rejected) == 0

    # Invalid date format
    bad_date_op = [
        {
            "op": "ROLLUP_DAY",
            "date": "2026/09/24",  # not YYYY-MM-DD
            "refs": ["mem:d1"],
            "text": "日期格式不对",
        }
    ]
    valid, rejected = validate_operations_local(bad_date_op, records)
    assert len(valid) == 0
    assert "INVALID_DATE" in rejected[0]["reason"]


def test_profile_update_compression_and_traceability():
    rec1 = sample_record("mem:p1", "用户在杭州余杭从事跨境电商工作。")
    rec2 = sample_record("mem:p2", "用户对花生严重过敏，外出就餐需避开。")
    records = [rec1, rec2]

    # Grounded profile update <= 600 tokens
    good_profile = "用户在杭州余杭从事跨境电商。对花生严重过敏。"
    ops = [
        {
            "op": "PROFILE_UPDATE",
            "refs": ["mem:p1", "mem:p2"],
            "text": good_profile,
        }
    ]
    valid, rejected = validate_operations_local(ops, records)
    assert len(valid) == 1
    assert len(rejected) == 0

    # Ungrounded hallucinated statement rejected
    bad_profile = "用户养了一只叫花花的英国短毛蓝猫，平时最爱吃川菜毛血旺。"
    ops_hallucinated = [
        {
            "op": "PROFILE_UPDATE",
            "refs": ["mem:p1"],
            "text": bad_profile,
        }
    ]
    valid, rejected = validate_operations_local(ops_hallucinated, records)
    assert len(valid) == 0
    assert len(rejected) == 1
    assert "UNGROUNDED_SENTENCE" in rejected[0]["reason"]

    # Exceeding 600 tokens rejected
    huge_profile = "用户详细信息 " * 700
    ops_huge = [
        {
            "op": "PROFILE_UPDATE",
            "refs": ["mem:p1"],
            "text": huge_profile,
        }
    ]
    valid, rejected = validate_operations_local(ops_huge, records)
    assert len(valid) == 0
    assert "TOKEN_LIMIT_EXCEEDED" in rejected[0]["reason"]


def test_forbidden_operations_strictly_rejected():
    rec = sample_record("mem:1", "普通事实")
    records = [rec]

    forbidden_ops = [
        {"op": "DELETE", "ref": "mem:1"},
        {"op": "REMOVE", "ref": "mem:1"},
        {"op": "HARD_ERASE", "ref": "mem:1"},
        {"op": "DROP", "ref": "mem:1"},
    ]
    valid, rejected = validate_operations_local(forbidden_ops, records)
    assert len(valid) == 0
    assert len(rejected) == 4
    for r in rejected:
        assert "FORBIDDEN_OP" in r["reason"]


def test_reflector_model_router_purpose_and_retry():
    rec1 = sample_record("mem:1", "用户在杭州工作。")
    rec2 = sample_record("mem:2", "用户在余杭做电商。")
    rec3 = sample_record("mem:3", "用户使用 Mac。")
    rec4 = sample_record("mem:4", "用户对花生过敏。")
    rec5 = sample_record("mem:5", "用户周末喜欢爬山。")
    records = [rec1, rec2, rec3, rec4, rec5]

    model_answer = {
        "operations": [
            {
                "op": "MERGE",
                "refs": ["mem:1", "mem:2"],
                "into_text": "用户在杭州余杭从事电商工作。",
                "keep_ref": "mem:1",
            },
            {
                "op": "PROFILE_UPDATE",
                "refs": ["mem:1", "mem:4"],
                "text": "用户在杭州从事电商。对花生过敏。",
            },
            {
                "op": "IMPORTANCE",
                "ref": "mem:4",
                "level": "HIGH",
            },
        ]
    }

    router = MockRouter(model_answer)
    manager = MockModelManager(router)
    client = MockClient()
    reflector = MemoryReflector(manager, client=client)

    result = asyncio.run(reflector.reflect("user-sub", records, auto_apply=True))

    assert result.reflected
    assert len(router.calls) == 1
    call_model, purpose, messages, kwargs = router.calls[0]
    assert purpose == "memory_reflect"
    assert call_model == "test-model-flash"

    # Client call verified
    assert len(client.calls) == 1
    method, path, body = client.calls[0]
    assert method == "POST"
    assert path == "/v1/unified/consolidation:apply"
    assert body["context"]["memory_subject_id"] == "user-sub"
    assert len(body["operations"]) == 3
    assert result.applied_count == 1


def test_parse_reflector_output_handles_markdown_and_raw():
    # Markdown fenced json
    fenced = """Here is the consolidation plan:
```json
{
  "operations": [
    {"op": "IMPORTANCE", "ref": "mem:1", "level": "HIGH"}
  ]
}
```
"""
    ops = parse_reflector_output(fenced)
    assert len(ops) == 1
    assert ops[0]["op"] == "IMPORTANCE"

    # Bare array
    bare_array = """[
      {"op": "ROLLUP_DAY", "date": "2026-10-08", "refs": ["m1"], "text": "summary"}
    ]"""
    ops_array = parse_reflector_output(bare_array)
    assert len(ops_array) == 1
    assert ops_array[0]["op"] == "ROLLUP_DAY"


def test_idempotency_behavior_on_identical_input():
    rec1 = sample_record("mem:1", "用户在杭州工作。")
    rec2 = sample_record("mem:2", "用户在杭州做电商。")
    records = [rec1, rec2]

    op = {
        "op": "MERGE",
        "refs": ["mem:1", "mem:2"],
        "into_text": "用户在杭州做电商工作。",
        "keep_ref": "mem:1",
    }

    # First run produces op
    valid1, _ = validate_operations_local([op], records)
    assert len(valid1) == 1

    # Second run with same candidate set produces identical accepted operation
    valid2, _ = validate_operations_local([op], records)
    assert valid1 == valid2
