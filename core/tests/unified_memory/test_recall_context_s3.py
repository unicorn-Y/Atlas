"""S3 召回装配与意图闸门测试 (core/atlas/memory/recall_context.py).

测试清单:
1. 意图闸门: 纯技术问题 (无个人线索) 闸门关闭 (不带私事)
2. 意图闸门: 相关偏好/排期/个人约束问题 闸门打开 (带私事)
3. 意图闸门: 纯数学计算拦截与结合个人线索时的放行
4. 出处验证: verify_referenced_refs 正确校验已装配 ref，不存在的 ref 标为未验证
5. 装配流程: assemble_recall_context 生成画像块 (<=600 token) 与相关记忆块 (<=1500 token)
6. 冲突标注: 存在 CONFLICTED 记录时明确标注 【有冲突/有多个候选】
"""

import asyncio
from datetime import datetime, timezone
import pytest

from atlas.memory import recall_context
from atlas.memory.recall_context import (
    RecallContextResult,
    assemble_recall_context,
    is_personal_memory_relevant,
    to_short_ref,
    verify_referenced_refs,
)


@pytest.mark.unit
def test_intent_gate_pure_tech_and_math():
    """纯技术问题与纯数学计算只给画像块，不给私事记忆 (闸门关闭)."""
    tech_queries = [
        "Python dict 怎么排序",
        "二叉树前序遍历递归实现",
        "Rust 中 Option 和 Result 的区别是什么",
        "Linux 查看端口占用命令",
        "HTTP 404 状态码是什么意思",
    ]
    for q in tech_queries:
        passed, score, reason = is_personal_memory_relevant(q)
        assert not passed, f"纯技术问题 '{q}' 闸门应当关闭, got passed={passed}, score={score}, reason={reason}"

    math_queries = [
        "帮我算一下 128 乘以 64 等于多少",
        "计算 1024 / 16",
        "求值 35 + 87",
    ]
    for q in math_queries:
        passed, score, reason = is_personal_memory_relevant(q)
        assert not passed, f"纯数学计算 '{q}' 闸门应当关闭, got passed={passed}, score={score}"


@pytest.mark.unit
def test_intent_gate_personal_and_preference():
    """包含用户偏好、习惯、排期、约束或个人指示的问题应当放行 (闸门开启)."""
    personal_queries = [
        "按我上次的习惯写一段代码",
        "我喜欢喝什么咖啡",
        "我之前说过的那个项目约束是什么",
        "帮我安排明天的日程",
        "你对我有什么了解",
        "给我推荐几个适合我的周末活动",
        "我女儿多大了",
        "前几天定的那个方案，再给我讲讲",
    ]
    for q in personal_queries:
        passed, score, reason = is_personal_memory_relevant(q)
        assert passed, f"个人/偏好问题 '{q}' 闸门应当开启, got passed={passed}, score={score}, reason={reason}"
        assert score >= 0.35, f"得分应超过阈值: score={score}"


@pytest.mark.unit
def test_provenance_verification():
    """出处验证: 仅允许引用本轮装配的 ref，不存在的 ref 标为未验证."""
    assembled_refs = ["memory:mem-pref-1", "memory:mem-task-99", "episode:ep-20261001"]

    # 合法引用
    text_valid = "根据您的偏好 [m:mem-pref-1]，我们为您配置了 Python 环境。"
    res_valid = verify_referenced_refs(text_valid, assembled_refs)
    assert not res_valid["has_unverified"]
    assert "mem-pref-1" in res_valid["valid_refs"]

    # 包含未装配/捏造的引用
    text_invalid = "据我所知 [m:mem-pref-1] 您喜欢 Python，另外 [m:fake-999] 您住上海。"
    res_invalid = verify_referenced_refs(text_invalid, assembled_refs)
    assert res_invalid["has_unverified"]
    assert "mem-pref-1" in res_invalid["valid_refs"]
    assert "fake-999" in res_invalid["unverified_refs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assemble_recall_context_pure_tech_blocks():
    """当用户问纯技术问题时，相关记忆块为空，只提供稳定画像块."""
    class FakeClient:
        async def _request(self, method: str, path: str, *, params=None, json_body=None):
            if path == "/v1/unified/profile":
                return {
                    "preferences": [
                        {"record_ref": "memory:p1", "key": "编程风格", "value": "偏好 TS 强类型"}
                    ],
                    "states": [],
                    "habits": [],
                    "relations": [],
                }
            if path == "/v1/unified/recall":
                pytest.fail("纯技术问题不应触发 POST /v1/unified/recall!")

    result = await assemble_recall_context(
        FakeClient(),
        user_message="Python dict 怎么排序",
        subject="subject-default",
    )

    assert not result.gate_passed
    assert "偏好 TS 强类型" in result.profile_block
    assert result.relevant_memory_block == ""  # 不给私事
    assert "memory:p1" in result.assembled_refs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assemble_recall_context_personal_with_conflict():
    """当用户问个人问题且召回命中冲突时，相关记忆块包含标记与冲突警示."""
    class FakeClient:
        async def _request(self, method: str, path: str, *, params=None, json_body=None):
            if path == "/v1/unified/profile":
                return {
                    "preferences": [
                        {"record_ref": "memory:p1", "key": "城市", "value": "常住杭州"}
                    ],
                    "states": [],
                    "habits": [],
                    "relations": [],
                }
            if path == "/v1/unified/recall":
                return {
                    "context_items": [
                        {
                            "record_ref": "memory:c1",
                            "lifecycle": "CONFLICTED",
                            "valid_time": {"valid_from": "2026-09-01T10:00:00Z"},
                            "content": {"text": "用户目前在上海工作"},
                        },
                        {
                            "record_ref": "memory:m2",
                            "lifecycle": "ACTIVE",
                            "valid_time": {"valid_from": "2026-10-01T10:00:00Z"},
                            "content": {"text": "用户目前在杭州工作"},
                        },
                    ],
                    "conflicts": [
                        {"record_refs": ["memory:c1", "memory:m2"], "kind": "LOCATION_DISAGREEMENT"}
                    ],
                }

    result = await assemble_recall_context(
        FakeClient(),
        user_message="我目前住在哪？",
        subject="subject-default",
    )

    assert result.gate_passed
    assert "【用户画像" in result.profile_block
    assert "【本轮相关记忆】" in result.relevant_memory_block
    # 冲突必须被明确标出
    assert "【有冲突/有多个候选】" in result.relevant_memory_block
    assert "2026-10-01" in result.relevant_memory_block
    assert len(result.assembled_refs) >= 3

    ctx_dict = result.to_context_dict()
    assert ctx_dict["gate_passed"] is True
    assert len(ctx_dict["memories"]) == 2
