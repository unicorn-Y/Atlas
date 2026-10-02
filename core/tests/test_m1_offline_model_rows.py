"""M1 — offline catalog rows for the current Claude defaults (CC 2.1.257-2.1.284).

With models.dev unreachable (empty registry, network off), ``get_model_capabilities`` /
``get_model_info`` must still resolve the three new default flagships from the
Atlas-owned fallback table in ``atlas.models.catalog``.
"""

from __future__ import annotations

import pytest

from atlas.models import catalog, models_dev


def test_fallback_rows_cover_the_three_current_claude_defaults() -> None:
    rows = catalog.CLAUDE_DEFAULT_MODEL_FALLBACKS
    assert {
        "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1",
    } == {mid for _pid, mid in rows}
    assert all(pid == "anthropic" for pid, _mid in rows)
    # 行形状与 models_dev._BUILTIN_MODEL_METADATA 一致：1M 上下文 + 已核实价格 + 能力位。
    expected_costs = {
        "claude-sonnet-5-5": (2.0, 10.0, 0.2),
        "claude-opus-5-5": (4.0, 20.0, None),
        "claude-fable-5-1": (10.0, 50.0, None),
    }
    for (_pid, mid), row in rows.items():
        assert row["limit"]["context"] == 1_000_000
        cost = row["cost"]
        exp_input, exp_output, exp_cache_read = expected_costs[mid]
        assert cost["input"] == exp_input and cost["output"] == exp_output
        assert cost.get("cache_read") == exp_cache_read
        assert row["tool_call"] is True and row["reasoning"] is True
        assert row["modalities"]["input"] == ["text", "image"]


@pytest.fixture
def offline_registry(monkeypatch: pytest.MonkeyPatch):
    """models.dev unreachable: empty registry for both network modes."""
    monkeypatch.setattr(models_dev, "fetch_models_dev", lambda *args, **kwargs: {})
    monkeypatch.setattr(models_dev, "_load_model_overrides", lambda **kwargs: {})
    return models_dev


def test_capabilities_survive_models_dev_outage(offline_registry) -> None:
    caps = offline_registry.get_model_capabilities("anthropic", "claude-sonnet-5-5")
    assert caps is not None
    assert caps.context_window == 1_000_000
    assert caps.supports_tools is True
    assert caps.supports_reasoning is True
    assert caps.supports_vision is True
    assert caps.model_family == "claude-sonnet-5-5"
    # hermes provider id 归一（anthropic → models.dev "anthropic"）之外，模型 id 大小写不敏感。
    caps_upper = offline_registry.get_model_capabilities("anthropic", "Claude-Opus-5-5")
    assert caps_upper is not None and caps_upper.context_window == 1_000_000


def test_model_info_survives_models_dev_outage(offline_registry) -> None:
    info = offline_registry.get_model_info("anthropic", "claude-fable-5-1")
    assert info is not None
    assert info.context_window == 1_000_000
    assert info.cost_input == 10.0 and info.cost_output == 50.0
    assert info.provider_id == "anthropic"
    assert info.has_cost_data()


def test_unknown_models_do_not_inherit_fallback_rows(offline_registry) -> None:
    # 无覆盖、无目录、无内建行 → 能力未知（None），绝不借用回退行。
    assert offline_registry.get_model_capabilities("anthropic", "claude-sonnet-9-9") is None
    assert offline_registry.get_model_info("anthropic", "claude-sonnet-9-9") is None


def test_live_catalog_still_wins_over_fallback_rows(offline_registry) -> None:
    """在线时 models.dev 已自动覆盖：目录命中优先，回退行不遮蔽注册表数据。"""
    offline_registry._BUILTIN_MODEL_METADATA[("anthropic", "claude-sonnet-5-5")] = {
        "limit": {"context": 500_000},
    }
    try:
        caps = offline_registry.get_model_capabilities("anthropic", "claude-sonnet-5-5")
        assert caps is not None and caps.context_window == 500_000
    finally:
        del offline_registry._BUILTIN_MODEL_METADATA[("anthropic", "claude-sonnet-5-5")]
