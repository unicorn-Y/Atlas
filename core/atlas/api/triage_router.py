"""Persistent cross-conversation inbox and workboard."""
from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import DATA_ROOT

router = APIRouter()
_BOARD_PATH = DATA_ROOT / "data" / "conversation-triage-board.json"


class BoardItem(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=512)
    column: str = "todo"
    priority: int = Field(default=2, ge=1, le=5)
    position: int = Field(default=0, ge=0, le=10000)


class BoardUpdate(BaseModel):
    items: list[BoardItem] = Field(default_factory=list, max_length=2000)


def _read_board() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_BOARD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


@router.get("/api/triage")
async def get_triage(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    memory, manager = services.memory, services.runtime_mgr
    if memory is None:
        raise HTTPException(503, "Conversation store is unavailable")
    conversations = await memory.list_conversations(limit=None)
    activity = await manager.conversation_activity(limit=500) if manager is not None else {"items": []}
    states = {str(item.get("conversation_id")): item for item in activity.get("items", [])}
    board = await asyncio.to_thread(_read_board)
    items = []
    for conversation in conversations:
        cid = str(conversation.get("id", ""))
        state = states.get(cid, {})
        status = str(state.get("status") or "idle")
        saved = board.get(cid, {})
        column = str(saved.get("column") or ("doing" if status in {"running", "planning"} else "todo"))
        if column not in {"todo", "doing", "done"}:
            column = "todo"
        category = "waiting" if status == "waiting" else "failed" if status == "failed" else "pending" if column == "todo" else None
        items.append({
            "conversation_id": cid,
            "title": str(conversation.get("title") or "新对话"),
            "updated_at": conversation.get("updated_at"),
            "status": status,
            "waiting_for": state.get("waiting_for"),
            "priority": int(saved.get("priority", 2)) if str(saved.get("priority", 2)).isdigit() else 2,
            "position": int(saved.get("position", 0)) if str(saved.get("position", 0)).isdigit() else 0,
            "column": column,
            "attention": status in {"waiting", "failed"},
            "category": category,
        })
    return {"items": items}


@router.put("/api/triage")
async def put_triage(req: BoardUpdate, services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    if services.memory is None:
        raise HTTPException(503, "Conversation store is unavailable")
    existing = {str(item.get("id")) for item in await services.memory.list_conversations(limit=None)}
    board: dict[str, dict[str, Any]] = {}
    for item in req.items:
        if item.conversation_id not in existing:
            continue
        if item.column not in {"todo", "doing", "done"}:
            raise HTTPException(422, "column must be todo, doing or done")
        board[item.conversation_id] = {"column": item.column, "priority": item.priority, "position": item.position}
    await asyncio.to_thread(_write_board, board)
    return {"saved": len(board)}


def _write_board(board: dict[str, dict[str, Any]]) -> None:
    _BOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = _BOARD_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(_BOARD_PATH)
