"""The user's own to-do list (not agent run todos), shown as a floating panel in the desktop app."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.config import DATA_ROOT

router = APIRouter(tags=["personal-todos"])

TODOS_PATH = DATA_ROOT / "data" / "personal-todos.json"
MAX_ITEMS = 500
MAX_TEXT_CHARS = 500
_lock = threading.Lock()


class PersonalTodo(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=MAX_TEXT_CHARS)
    done: bool = False
    created_at: str = ""
    done_at: str | None = None


class PersonalTodosUpdate(BaseModel):
    items: list[PersonalTodo] = Field(max_length=MAX_ITEMS)


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        try:
            result.append(PersonalTodo.model_validate(item).model_dump())
        except ValueError:
            continue
    return result


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@router.get("/api/personal-todos")
def get_personal_todos() -> dict[str, Any]:
    with _lock:
        return {"items": _load(TODOS_PATH)}


@router.put("/api/personal-todos")
def put_personal_todos(payload: PersonalTodosUpdate) -> dict[str, Any]:
    items = [item.model_dump() for item in payload.items if item.text.strip()]
    with _lock:
        try:
            _save(TODOS_PATH, items)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="无法保存待办事项。") from exc
    return {"items": items}
