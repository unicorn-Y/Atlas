"""L8 分阶段思考量 — 按规划/执行/验收阶段分配 reasoning effort（C5 契约 §3）。

settings["reasoning_stages"] = {"enabled": false, "planning": "high",
"execution": "medium", "verification": "high"}；关闭（enabled=False）时
effort_for_phase 一律返回 None，引擎行为与未接入前完全一致。
"""

from __future__ import annotations

from typing import Any

from atlas.config import load_user_settings, save_user_settings
from atlas.models.reasoning_effort import EFFORT_LADDER

DEFAULT_STAGES = {"planning": "high", "execution": "medium", "verification": "high"}
PHASES = ("planning", "execution", "verification")


def load_stage_config() -> dict[str, Any]:
    """读 settings["reasoning_stages"]，缺省合并 DEFAULT_STAGES + enabled=False。"""
    cfg: dict[str, Any] = {**DEFAULT_STAGES, "enabled": False}
    raw = load_user_settings().get("reasoning_stages")
    if isinstance(raw, dict):
        for phase in PHASES:
            value = str(raw.get(phase) or "").strip().lower()
            if value in EFFORT_LADDER:
                cfg[phase] = value
        cfg["enabled"] = bool(raw.get("enabled", False))
    return cfg


def save_stage_config(cfg: dict[str, Any]) -> None:
    """校验三档 ∈ EFFORT_LADDER 后写回 settings["reasoning_stages"]。"""
    if not isinstance(cfg, dict):
        raise ValueError("reasoning_stages 配置必须是对象")
    merged: dict[str, Any] = {}
    for phase in PHASES:
        value = str(cfg.get(phase, DEFAULT_STAGES[phase]) or "").strip().lower()
        if value not in EFFORT_LADDER:
            raise ValueError(f"非法思考档位: {phase}={cfg.get(phase)!r}")
        merged[phase] = value
    settings = load_user_settings()
    settings["reasoning_stages"] = {**merged, "enabled": bool(cfg.get("enabled", False))}
    save_user_settings(settings)


def effort_for_phase(cfg: dict[str, Any], phase: str) -> str | None:
    """cfg 未 enabled 或 phase 不在三个阶段内 → None；否则返回该阶段档位。"""
    if not isinstance(cfg, dict) or not cfg.get("enabled") or phase not in PHASES:
        return None
    value = str(cfg.get(phase) or "").strip().lower()
    return value if value in EFFORT_LADDER else None
