# Adapted from NousResearch/hermes-agent tools/todo_tool.py at
# 330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3 (MIT); Atlas emits Runtime events.
"""Bounded revisioned todo state, scoped to one Atlas run."""

from __future__ import annotations

from typing import Any

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
MAX_TODO_CONTENT_CHARS = 4000
MAX_TODO_ITEMS = 256


class TodoStore:
    def __init__(self) -> None:
        self._items: list[dict[str, str]] = []
        self._revision = 0

    def snapshot(self) -> dict[str, Any]:
        return {"revision": self._revision, "todos": [dict(item) for item in self._items]}

    def write(self, todos: list[dict[str, Any]], *, merge: bool = False) -> dict[str, Any]:
        if not isinstance(todos, list):
            raise ValueError("todos must be a list")
        before = self.snapshot()["todos"]
        incoming: list[dict[str, str]] = []
        ids: set[str] = set()
        for value in todos:
            if not isinstance(value, dict):
                raise ValueError("each todo must be an object")
            item_id = str(value.get("id", "")).strip()[:100]
            text = str(value.get("content", "")).strip()[:MAX_TODO_CONTENT_CHARS]
            status = str(value.get("status", "pending")).strip().lower()
            if not item_id or not text or status not in VALID_STATUSES:
                raise ValueError("each todo needs id, content, and a valid status")
            if item_id in ids:
                continue
            ids.add(item_id)
            item = {"id": item_id, "text": text, "status": status}
            if value.get("parent"):
                item["parent"] = str(value["parent"])[:100]
            incoming.append(item)
        if merge:
            existing = {item["id"]: dict(item) for item in self._items}
            for item in incoming:
                if item["id"] in existing:
                    existing[item["id"]].update(item)
                else:
                    existing[item["id"]] = item
            self._items = list(existing.values())
        else:
            self._items = incoming
        self._items = self._items[:MAX_TODO_ITEMS]
        valid = {item["id"] for item in self._items}
        self._items = [item for item in self._items
                       if not item.get("parent") or item["parent"] in valid]
        if self._items != before:
            self._revision += 1
        return self.snapshot()

    def format_for_injection(self) -> str | None:
        active = [item for item in self._items if item["status"] in {"pending", "in_progress"}]
        if not active:
            return None
        return "[Your active task list was preserved across context compression]\n" + "\n".join(
            f"- [{item['status']}] {item['id']}: {item['text']}" for item in active
        )
