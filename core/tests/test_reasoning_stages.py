from __future__ import annotations

import pytest

from atlas.models import reasoning_stages as stages


def _patch_settings(monkeypatch, data: dict) -> dict:
    """隔离 settings 读写：load 返回 data，save 写进 saved 并同步回 data。"""
    saved: dict = {}
    monkeypatch.setattr(stages, "load_user_settings", lambda: data)
    monkeypatch.setattr(
        stages, "save_user_settings",
        lambda payload: (saved.update(payload), data.update(payload)) and None,
    )
    return saved


def test_load_stage_config_defaults_and_merge(monkeypatch) -> None:
    monkeypatch.setattr(stages, "load_user_settings", lambda: {})
    assert stages.load_stage_config() == {
        "planning": "high", "execution": "medium", "verification": "high",
        "enabled": False,
    }
    monkeypatch.setattr(stages, "load_user_settings", lambda: {
        "reasoning_stages": {"enabled": True, "planning": "low"},
    })
    assert stages.load_stage_config() == {
        "planning": "low", "execution": "medium", "verification": "high",
        "enabled": True,
    }


def test_save_stage_config_roundtrip_and_reject(monkeypatch) -> None:
    data: dict = {}
    saved = _patch_settings(monkeypatch, data)
    stages.save_stage_config({"enabled": True, "planning": "low", "execution": "medium",
                              "verification": "high"})
    assert saved["reasoning_stages"] == {
        "enabled": True, "planning": "low", "execution": "medium", "verification": "high",
    }
    assert stages.load_stage_config()["execution"] == "medium"

    with pytest.raises(ValueError):
        stages.save_stage_config({"planning": "bogus"})
    with pytest.raises(ValueError):
        stages.save_stage_config("not-a-dict")  # type: ignore[arg-type]


def test_effort_for_phase_disabled_returns_none() -> None:
    cfg = {**stages.DEFAULT_STAGES, "enabled": False}
    assert stages.effort_for_phase(cfg, "planning") is None
    assert stages.effort_for_phase(cfg, "execution") is None
    assert stages.effort_for_phase(cfg, "verification") is None


def test_effort_for_phase_enabled_maps_each_phase() -> None:
    cfg = {"enabled": True, "planning": "high", "execution": "low", "verification": "medium"}
    assert stages.effort_for_phase(cfg, "planning") == "high"
    assert stages.effort_for_phase(cfg, "execution") == "low"
    assert stages.effort_for_phase(cfg, "verification") == "medium"
    assert stages.effort_for_phase(cfg, "unknown-phase") is None
