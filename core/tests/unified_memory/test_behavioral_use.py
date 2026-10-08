"""T07.3 & T08.2-Atlas: 主动使用、适当不使用与动作前检查 (UM07 / UM08).

覆盖判据（02_wave_tasks.md T07.3 / T08.2）：
  1. test_implicit_constraint_changes_action:
     隐式约束改变行动（晚上 7 点后不排工作会议 → 安排明天工作时晚间不得排会 + 记录 application_receipts）；
  2. test_pre_plan_constraint_order:
     规划前加载相关状态/约束，不要在 plan 已生成后才加载会改变计划的记忆；
  3. test_irrelevance_gating_on_technical_queries:
     无关问题不装配私人经历（Python dict 怎么排序 / 帮我算一下 128 乘以 64 返回 False，
     安排明天工作 / 按我现在的格式来 返回 True）；
  4. test_read_id_and_input_hash_binding:
     read_id 与真正模型输入 input_hash 严格绑定，防伪造使用与跨上下文滥用；
  5. test_pre_action_stale_dependency_blocking:
     新事实不能配旧计划继续执行：动作前检查发现 STALE 时阻止动作执行；
  6. test_memory_off_comparison:
     与 memory off 对照：无统一记忆装配时不遵守约束或无 application_receipts，
     记忆开启后严格遵守约束并产生收据。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.memory.context import (
    check_action_dependencies,
    is_personal_memory_relevant,
    load_pre_plan_constraints,
)
from tests.unified_memory.harness import UMHarness


@pytest.fixture
def h(um: UMHarness) -> UMHarness:
    """Convenience fixture providing session UMHarness instance."""
    return um


# ================================================================== T07.3 Acceptance Test

@pytest.mark.integration
@pytest.mark.fake_provider
def test_implicit_constraint_changes_action(h: UMHarness) -> None:
    """T07.3 核心验收用例：隐式约束真实改变行动。

    seed('implicit') 包含用户约束：晚上 7 点后不要给我安排工作会议。
    h.chat('帮我安排明天的工作') 必须生成不包含晚间工作/会议的安排，并附带 application_receipts。
    """
    h.seed("implicit")
    result = h.chat("帮我安排明天的工作")
    assert not result["scheduled_work_in_evening"] and result["application_receipts"], (
        f"Expected no evening work and non-empty application_receipts, got: "
        f"scheduled_work_in_evening={result['scheduled_work_in_evening']}, "
        f"receipts={result['application_receipts']}, reply={result['reply']}"
    )


# ================================================================== 1. 规划前约束加载顺序

@pytest.mark.unit
def test_pre_plan_constraint_order_in_execution_flow() -> None:
    """验证 run_phases 管道中 pre_plan_constraints 阶段严格先于 plan 阶段执行。"""
    from atlas.agent.run_phases import (
        _phase_begin,
        _phase_context,
        _phase_goal_knowledge,
        _phase_plan,
        _phase_pre_plan_constraints,
        _phase_prompt_hook,
    )
    import inspect

    # 检查 execute_run 中的阶段顺序
    from atlas.agent.run_phases import execute_run
    src = inspect.getsource(execute_run)
    idx_pre_plan = src.find("_phase_pre_plan_constraints")
    idx_plan = src.find("_phase_plan")
    idx_context = src.find("_phase_context")

    assert idx_pre_plan != -1, "_phase_pre_plan_constraints 必须注册在 execute_run 中"
    assert idx_plan != -1, "_phase_plan 必须注册在 execute_run 中"
    assert idx_pre_plan < idx_plan, (
        "铁律：_phase_pre_plan_constraints 必须在 _phase_plan 之前执行，"
        "不在 plan 生成后才加载会改变计划的记忆！"
    )
    assert idx_plan < idx_context, "_phase_plan 必须在 _phase_context 之前"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_pre_plan_constraints_recalls_active_items() -> None:
    """验证 load_pre_plan_constraints 在规划前成功筛选 PREFERENCE / CONSTRAINT 并绑定收据。"""
    mock_facade = MagicMock()
    mock_facade.enabled = True
    test_query = "帮我安排明天的工作"

    mock_facade.recall_for_conversation = AsyncMock(return_value={
        "read_id": "read-test-1234",
        "context_hash": "sha256:abcd1234",
        "context_items": [
            {
                "record_ref": "memory:constraint-01",
                "record_revision": 1,
                "facet": "CONSTRAINT",
                "content": {"text": "晚上 7 点后不要给我安排工作会议。"},
            },
            {
                "record_ref": "memory:preference-01",
                "record_revision": 1,
                "facet": "PREFERENCE",
                "content": {"text": "偏好上午进行技术评审。"},
            },
        ],
    })
    mock_facade.record_application = AsyncMock(return_value={
        "application_id": "app-test-5678",
        "application_ref": "application:app-test-5678",
        "status": "RECORDED",
    })

    res = await load_pre_plan_constraints(mock_facade, test_query)

    assert res["relevant"] is True
    assert len(res["constraints"]) == 2
    assert res["read_id"] == "read-test-1234"
    expected_hash = "sha256:" + hashlib.sha256(test_query.encode("utf-8")).hexdigest()
    assert res["input_hash"] == expected_hash

    receipt = res["application_receipt"]
    assert receipt is not None
    assert receipt["application_id"] == "app-test-5678"
    assert receipt["read_id"] == "read-test-1234"
    assert receipt["input_hash"] == expected_hash
    assert "memory:constraint-01" in receipt["applied_refs"]


# ================================================================== 2. 无关问题门禁拦截

@pytest.mark.unit
def test_irrelevance_gating_on_technical_and_generic_queries() -> None:
    """无关问题门禁：纯代码与纯算术问题不装配私人经历；排期/偏好/人名线索放行。"""
    # 纯通用代码/库函数问题 -> False
    assert is_personal_memory_relevant("Python dict 怎么排序") is False
    assert is_personal_memory_relevant("python 字典怎么遍历") is False
    assert is_personal_memory_relevant("golang slice 扩容机制") is False
    assert is_personal_memory_relevant("如何实现二叉树反转") is False

    # 纯计算问题 -> False
    assert is_personal_memory_relevant("帮我算一下 128 乘以 64。") is False
    assert is_personal_memory_relevant("计算 1024 / 16 等于几") is False
    assert is_personal_memory_relevant("256 + 512") is False

    # 个人日程/偏好/人物/时间线索 -> True
    assert is_personal_memory_relevant("帮我安排明天的工作") is True
    assert is_personal_memory_relevant("按我现在的格式来") is True
    assert is_personal_memory_relevant("帮我把他上次的修改意见整理成清单。") is True
    assert is_personal_memory_relevant("明天上午项目继续推进") is True
    assert is_personal_memory_relevant("按照小王的意见修改") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_pre_plan_constraints_bypasses_irrelevant_query() -> None:
    """纯通用问题调用 load_pre_plan_constraints 时直接返回 relevant=False，不触发外部召回。"""
    mock_facade = MagicMock()
    mock_facade.recall_for_conversation = AsyncMock()

    res = await load_pre_plan_constraints(mock_facade, "Python dict 怎么排序")
    assert res["relevant"] is False
    assert res["constraints"] == []
    assert res["application_receipt"] is None
    mock_facade.recall_for_conversation.assert_not_called()


# ================================================================== 3. read_id 与 input_hash 严格绑定

@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_id_and_input_hash_binding_and_fallback() -> None:
    """验证 read_id 与真正输入 input_hash 的绑定，以及 501 降级收据的完整性。"""
    mock_facade = MagicMock()
    mock_facade.enabled = True
    query = "按我现在的格式来"
    expected_hash = "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()

    mock_facade.recall_for_conversation = AsyncMock(return_value={
        "read_id": "read-fmt-999",
        "context_hash": expected_hash,
        "context_items": [
            {
                "record_ref": "memory:pref-fmt",
                "facet": "PREFERENCE",
                "content": {"text": "格式：简短中文"},
            }
        ],
    })
    # 模拟 MemoryOS applications 路由尚未就绪 (501 / Exception)
    mock_facade.record_application = AsyncMock(side_effect=RuntimeError("HTTP 501 FeatureNotReady"))

    res = await load_pre_plan_constraints(mock_facade, query)

    assert res["relevant"] is True
    assert res["read_id"] == "read-fmt-999"
    assert res["input_hash"] == expected_hash

    # 验证降级到本地收据，且保留关键绑定要素
    receipt = res["application_receipt"]
    assert receipt is not None
    assert receipt["status"] == "RECORDED_LOCAL"
    assert receipt["read_id"] == "read-fmt-999"
    assert receipt["input_hash"] == expected_hash
    assert "memory:pref-fmt" in receipt["applied_refs"]
    assert receipt["basis"]["input_hash"] == expected_hash


# ================================================================== 4. 动作前过时依赖阻止 (T08.2)

@pytest.mark.unit
@pytest.mark.asyncio
async def test_pre_action_stale_dependency_blocking() -> None:
    """T08.2 判据：动作前检查发现依赖 STALE 时阻断动作执行并返回变更引用。"""
    mock_facade = MagicMock()
    mock_facade.enabled = True

    # 依赖检查返回 STALE
    mock_facade.check_dependencies = AsyncMock(return_value={
        "status": "STALE",
        "changed_refs": ["memory:work-constraint-old"],
        "action_required": "REPLAN",
        "details": [{"record_ref": "memory:work-constraint-old", "status": "CHANGED"}],
    })

    plan_deps = [{"record_ref": "memory:work-constraint-old", "revision": 1}]
    result = await check_action_dependencies(mock_facade, plan_deps)

    assert result["status"] == "STALE"
    assert result["blocked"] is True
    assert "memory:work-constraint-old" in result["changed_refs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pre_action_valid_dependency_passes() -> None:
    """依赖匹配无变更时，check_action_dependencies 正常放行。"""
    mock_facade = MagicMock()
    mock_facade.enabled = True
    mock_facade.check_dependencies = AsyncMock(return_value={
        "status": "VALID",
        "changed_refs": [],
    })

    plan_deps = [{"record_ref": "memory:work-constraint-current", "revision": 2}]
    result = await check_action_dependencies(mock_facade, plan_deps)

    assert result["status"] == "VALID"
    assert result["blocked"] is False
    assert result["changed_refs"] == []


# ================================================================== 5. 与 memory off 对照

@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_off_comparison_produces_no_constraints_or_receipts() -> None:
    """记忆关闭状态对照：facade=None 时不加载任何约束，亦不产生应用凭据。"""
    res = await load_pre_plan_constraints(None, "帮我安排明天的工作")
    assert res["relevant"] is True
    assert res["constraints"] == []
    assert res["application_receipt"] is None
    assert res["read_id"] is None
