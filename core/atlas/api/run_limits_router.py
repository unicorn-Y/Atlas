"""User-level runtime limits backed by the Atlas engine's actual limits."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.config import get_config, load_user_settings, save_user_settings
from atlas.engine.kernel.loop import DEFAULT_MAX_TURNS, MAX_TURNS_CAP

router = APIRouter(tags=["run-limits"])


class RunLimitsPayload(BaseModel):
    # None clears the user override and restores engine.max_turns.
    max_turns: int | None = Field(default=None, ge=1, le=MAX_TURNS_CAP, strict=True)
    # Estimated USD cap; exact provider billing is not available for every route.
    max_cost_usd: Decimal | None = Field(
        default=None, ge=Decimal("0.001"), le=Decimal("100000"),
        max_digits=10, decimal_places=4,
    )


def _engine_max_turns() -> int:
    configured = get_config().get("engine.max_turns", DEFAULT_MAX_TURNS)
    try:
        return max(1, min(int(configured), MAX_TURNS_CAP))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="engine.max_turns is not a valid integer") from exc


def _user_max_turns(settings: dict[str, Any]) -> int | None:
    limits = settings.get("run_limits")
    value = limits.get("max_turns") if isinstance(limits, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_TURNS_CAP:
        return value
    return None


def _user_max_cost_usd(settings: dict[str, Any]) -> Decimal | None:
    limits = settings.get("run_limits")
    raw = limits.get("max_cost_usd") if isinstance(limits, dict) else None
    try:
        value = Decimal(str(raw)) if raw is not None else None
    except Exception:
        return None
    if value is None or not value.is_finite() or value < Decimal("0.001") or value > Decimal("100000"):
        return None
    return value


def _response() -> dict[str, Any]:
    engine_limit = _engine_max_turns()
    settings = load_user_settings()
    user_limit = _user_max_turns(settings)
    cost_limit = _user_max_cost_usd(settings)
    return {
        "engine_max_turns": engine_limit,
        "user_max_turns": user_limit,
        "effective_max_turns": user_limit if user_limit is not None else engine_limit,
        "max_turns_limit": MAX_TURNS_CAP,
        "user_max_cost_usd": str(cost_limit) if cost_limit is not None else None,
        "cost_limit_supported": True,
        "cost_limit_reason": (
            "费用按 Atlas 现有模型价格表估算；价格未知或 usage 缺失时会阻止后续模型请求。"
            "已发送的单次请求无法撤回，输出 token 费用可能使估算超过设定值。"
        ),
    }


@router.get("/api/run-limits")
async def get_run_limits() -> dict[str, Any]:
    return _response()


@router.put("/api/run-limits")
async def update_run_limits(payload: RunLimitsPayload) -> dict[str, Any]:
    settings = load_user_settings()
    limits = settings.get("run_limits")
    if not isinstance(limits, dict):
        limits = {}
    if payload.max_turns is None:
        limits.pop("max_turns", None)
    else:
        limits["max_turns"] = payload.max_turns
    if payload.max_cost_usd is None:
        limits.pop("max_cost_usd", None)
    else:
        limits["max_cost_usd"] = str(payload.max_cost_usd)
    if limits:
        settings["run_limits"] = limits
    else:
        settings.pop("run_limits", None)
    save_user_settings(settings)
    return _response()
