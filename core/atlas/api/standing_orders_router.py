"""CRUD and audit API for contextual standing orders."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas import standing_orders

router = APIRouter(prefix="/api/standing-orders", tags=["standing-orders"])


class StandingOrderPayload(BaseModel):
    name: str = ""
    owner_agent_id: str
    enabled: bool = True
    instruction: str
    scope: dict[str, Any] = Field(default_factory=lambda: {"kind": "all"})
    trigger: dict[str, Any] = Field(default_factory=lambda: {"kind": "turn", "keywords": []})


@router.get("")
async def list_standing_orders(q: str = Query(default=""), owner_agent_id: str = "") -> dict[str, Any]:
    return {"items": standing_orders.list_orders(q, owner_agent_id)}


@router.post("")
async def create_standing_order(payload: StandingOrderPayload) -> dict[str, Any]:
    try:
        return standing_orders.create_order(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{order_id}")
async def update_standing_order(order_id: str, payload: StandingOrderPayload) -> dict[str, Any]:
    try:
        result = standing_orders.update_order(order_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="standing order not found")
    return result


@router.delete("/{order_id}")
async def delete_standing_order(order_id: str) -> dict[str, str]:
    if not standing_orders.delete_order(order_id):
        raise HTTPException(status_code=404, detail="standing order not found")
    return {"status": "deleted", "id": order_id}


@router.get("/{order_id}/audit")
async def standing_order_audit(order_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return {"items": standing_orders.recent_audit(order_id=order_id, limit=limit)}
