"""T13.3 Windows 真入口、长时间与最终关闭验收测试（UM13）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ATLAS_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ATLAS_ROOT / "artifacts" / "unified-memory" / "UM13" / "T13.3" / "release_manifest.json"
RESULT_MD_PATH = ATLAS_ROOT / "tasks" / "results" / "ATLAS-UNIFIED-MEMORY-WINDOWS.result.md"


def validate_final_receipt(receipt: dict[str, Any]) -> bool:
    """Validate final closeout receipt gate discipline (02_wave_tasks.md T13.3)."""
    if receipt.get("scope") != "Windows Atlas as primary memory subject":
        return False
    gates = receipt.get("required_gates") or []
    if not gates:
        return False
    if receipt.get("status") == "ACCEPTED" and not all(bool(g.get("passed")) for g in gates):
        return False
    return True


@pytest.fixture()
def receipt() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_final_receipt_cannot_hide_missing_gates(receipt: dict[str, Any]):
    """02_wave_tasks.md T13.3 原样判据：任何必要门禁未过，不得标 ACCEPTED。"""
    assert receipt["status"] != "ACCEPTED" or all(g["passed"] for g in receipt["required_gates"])
    assert receipt["scope"] == "Windows Atlas as primary memory subject"
    assert validate_final_receipt(receipt) is True

    # 篡改实验：若存在未通过门禁但强行标 ACCEPTED，校验器必须拒绝
    tampered = json.loads(json.dumps(receipt))
    tampered["status"] = "ACCEPTED"
    tampered["required_gates"][-1]["passed"] = False
    assert validate_final_receipt(tampered) is False


@pytest.mark.unit
def test_product_effects_and_24_interactive_trajectories(receipt: dict[str, Any]):
    """验证 12 条产品效果与 >=24 条跨会话/重启/切模型/纠错/删除/未来触发轨迹。"""
    effects = receipt["product_effects_12"]
    trajectories = receipt["interactive_trajectories_24"]
    assert len(effects) == 12
    assert len(trajectories) >= 24
    categories = {t["category"] for t in trajectories}
    assert {
        "cross_session",
        "restart_continuation",
        "model_switch",
        "correction_propagation",
        "hard_erase_barrier",
        "prospective_intent_trigger",
    } <= categories


@pytest.mark.unit
def test_longitudinal_synthetic_vs_real_30d_separation(receipt: dict[str, Any]):
    """验证 90天/1年合成轨迹与 30 天真实持续使用观察严格分开，时间未到不谎称完成。"""
    lon = receipt["longitudinal_evaluation"]
    assert lon["synthetic_90d_1y_status"] == "SYNTHETIC_LONGITUDINAL_VERIFIED"
    assert lon["real_30d_continuous_status"] == "REAL_30D_PENDING_DURATION"
    assert lon["empirical_year_scale_proven"] is False


@pytest.mark.unit
def test_64_aspects_all_tasks_and_excluded_scopes(receipt: dict[str, Any]):
    """验证 16 域 64 方面、全部波次任务映射、S01-S16 来源及外部平台采集排除声明。"""
    assert receipt["coverage"]["domains_count"] == 16
    assert receipt["coverage"]["aspects_count"] == 64
    assert receipt["coverage"]["core_cases_count"] == 320
    assert len(receipt["tasks_traceability"]) >= 35
    assert len(receipt["sources_s01_s16"]) == 16
    excluded = set(receipt["excluded_scopes"])
    assert "mobile_phone_collector" in excluded
    assert "wechat_collector" in excluded
    assert "standalone_email_collector" in excluded
    assert "third_party_agent_as_memory_subject" in excluded
    assert RESULT_MD_PATH.exists()
