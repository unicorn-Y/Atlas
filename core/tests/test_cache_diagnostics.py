from __future__ import annotations

from atlas.models import cache_diagnostics as diag


def _fresh_state(monkeypatch) -> None:
    monkeypatch.setattr(diag, "_layers", {})


def test_changed_tools_signature_reports_tool_change(monkeypatch) -> None:
    _fresh_state(monkeypatch)
    first = diag.record_layer_hashes("conv", "system", "tools-v1", "history-1")
    # 首次可比请求：无上次命中率可比，不给原因。
    assert diag.explain_cache_drop("conv", first, 800, 1000) is None
    second = diag.record_layer_hashes("conv", "system", "tools-v2", "history-2")
    assert diag.explain_cache_drop("conv", second, 0, 1000) == diag.TOOLS_CHANGED


def test_changed_system_signature_reports_system_change(monkeypatch) -> None:
    _fresh_state(monkeypatch)
    first = diag.record_layer_hashes("conv", "system-v1", "tools", "history-1")
    assert diag.explain_cache_drop("conv", first, 900, 1000) is None
    second = diag.record_layer_hashes("conv", "system-v2", "tools", "history-2")
    assert diag.explain_cache_drop("conv", second, 0, 1000) == diag.SYSTEM_CHANGED


def test_changed_history_signature_reports_history_change(monkeypatch) -> None:
    _fresh_state(monkeypatch)
    first = diag.record_layer_hashes("conv", "system", "tools", "history-v1")
    assert diag.explain_cache_drop("conv", first, 500, 1000) is None
    second = diag.record_layer_hashes("conv", "system", "tools", "history-v2")
    assert diag.explain_cache_drop("conv", second, 0, 1000) == diag.HISTORY_CHANGED


def test_healthy_hit_rate_returns_none(monkeypatch) -> None:
    _fresh_state(monkeypatch)
    first = diag.record_layer_hashes("conv", "system", "tools-a", "history-1")
    assert diag.explain_cache_drop("conv", first, 800, 1000) is None
    second = diag.record_layer_hashes("conv", "system", "tools-b", "history-2")
    assert diag.explain_cache_drop("conv", second, 900, 1000) is None
    # 降幅 0.1，未超过 0.5 阈值。
    third = diag.record_layer_hashes("conv", "system", "tools-c", "history-3")
    assert diag.explain_cache_drop("conv", third, 700, 1000) is None


def test_identical_layers_with_drop_reports_unknown(monkeypatch) -> None:
    _fresh_state(monkeypatch)
    first = diag.record_layer_hashes("conv", "system", "tools", "history")
    assert diag.explain_cache_drop("conv", first, 800, 1000) is None
    second = diag.record_layer_hashes("conv", "system", "tools", "history")
    assert diag.explain_cache_drop("conv", second, 0, 1000) == diag.UNKNOWN_REASON


def test_no_input_tokens_or_missing_history_returns_none(monkeypatch) -> None:
    _fresh_state(monkeypatch)
    assert diag.explain_cache_drop("conv", {"system": "a", "tools": "b", "history": "c"},
                                   0, 0) is None
    assert diag.explain_cache_drop("never-recorded", {"system": "a"}, 0, 100) is None
