# Behavior reference: Anthropic Claude Code Tools reference
# https://code.claude.com/docs/en/tools-reference (TaskCreate/TaskGet/TaskList/TaskUpdate/TodoWrite).
# Independent Atlas adapter based on the public documentation; no Claude Code
# proprietary implementation code is copied or ported.
"""Run-scoped adapter for Claude Code task-list tools."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
_MAX_TEXT = 4000
_MAX_OWNER = 200
_MAX_TASKS = 256
_DETAILS_ATTR = "_claude_task_details"


def _tool(name: str, description: str, properties: dict[str, Any],
          required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


def task_tool_schemas() -> list[dict[str, Any]]:
    """Return OpenAI-style function schemas for Claude's task-list tools."""
    text = {"type": "string", "maxLength": _MAX_TEXT}
    status = {"type": "string", "enum": sorted(_STATUSES)}
    blocked_by = {"type": "array", "items": {"type": "string"}}
    return [
        _tool("TaskCreate", "Create a task in the current run's task list.", {
            "subject": text, "description": text, "activeForm": text,
            "status": status, "owner": {"type": "string", "maxLength": _MAX_OWNER},
            "blockedBy": blocked_by,
        }, ["subject"]),
        _tool("TaskGet", "Retrieve one task from the current run's task list.", {
            "taskId": {"type": "string"},
        }, ["taskId"]),
        _tool("TaskList", "List tasks and their current status for this run.", {}),
        _tool("TaskUpdate", "Update a task's details, status, owner, or dependencies.", {
            "taskId": {"type": "string"}, "subject": text,
            "description": text, "activeForm": text, "status": status,
            "owner": {"type": "string", "maxLength": _MAX_OWNER},
            "blockedBy": blocked_by,
        }, ["taskId"]),
        _tool("TodoWrite", "Replace the current run's task checklist.", {
            "todos": {"type": "array", "maxItems": _MAX_TASKS, "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "content": text,
                    "status": status,
                    "activeForm": text,
                },
                "required": ["content", "status"],
                "additionalProperties": False,
            }},
        }, ["todos"]),
    ]


def _result(data: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "data": data,
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        "is_error": is_error,
    }


def _todo_store(runtime: Any) -> Any:
    if isinstance(runtime, Mapping):
        store = runtime.get("todo_store")
    else:
        store = getattr(runtime, "todo_store", None)
    if store is None or not callable(getattr(store, "snapshot", None)) \
            or not callable(getattr(store, "write", None)):
        raise ValueError("This run does not expose a TodoStore")
    return store


def _details(store: Any) -> dict[str, dict[str, Any]]:
    details = getattr(store, _DETAILS_ATTR, None)
    if details is None:
        details = {}
        setattr(store, _DETAILS_ATTR, details)
    if not isinstance(details, dict):
        raise ValueError("TodoStore task metadata is invalid")
    current = {
        str(item.get("id", "")): item
        for item in store.snapshot().get("todos", [])
    }
    for item_id in list(details):
        if item_id not in current:
            del details[item_id]
        elif details[item_id].get("subject") != current[item_id].get("text", ""):
            # Another TodoStore writer reused the ID with a new subject.
            details[item_id] = {
                "subject": current[item_id].get("text", ""),
                "description": "", "activeForm": "", "owner": "", "blockedBy": [],
            }
    return details


def _string(value: Any, field: str, *, required: bool = False,
            maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    result = value.strip()
    if required and not result:
        raise ValueError(f"{field} must not be empty")
    if len(result) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return result


def _task_rows(store: Any) -> list[dict[str, Any]]:
    details = _details(store)
    rows: list[dict[str, Any]] = []
    for item in store.snapshot().get("todos", []):
        task_id = str(item["id"])
        metadata = details.get(task_id, {})
        task = {
            "taskId": task_id,
            "subject": metadata.get("subject", item.get("text", "")),
            "status": item.get("status", "pending"),
            "description": metadata.get("description", ""),
            "activeForm": metadata.get("activeForm", ""),
            "owner": metadata.get("owner", ""),
            "blockedBy": list(metadata.get("blockedBy", [])),
        }
        if item.get("parent"):
            task["parent"] = item["parent"]
        rows.append(task)
    return rows


def _find_task(store: Any, task_id: str) -> dict[str, Any]:
    for task in _task_rows(store):
        if task["taskId"] == task_id:
            return task
    raise ValueError(f"Task {task_id!r} was not found")


def _next_task_id(store: Any) -> str:
    used = {task["taskId"] for task in _task_rows(store)}
    index = 1
    while f"task-{index}" in used:
        index += 1
    return f"task-{index}"


def _checked_blockers(value: Any, task_id: str, store: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("blockedBy must be a list of task IDs")
    known = {task["taskId"] for task in _task_rows(store)}
    blockers: list[str] = []
    for raw in value:
        blocker = _string(raw, "blockedBy item", required=True, maximum=100)
        if blocker == task_id:
            raise ValueError("A task cannot be blocked by itself")
        if blocker not in known:
            raise ValueError(f"blockedBy task {blocker!r} was not found")
        if blocker not in blockers:
            blockers.append(blocker)
    return blockers


def _status(value: Any) -> str:
    if not isinstance(value, str) or value not in _STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(_STATUSES))}")
    return value


def _call_task_create(args: dict[str, Any], store: Any) -> dict[str, Any]:
    subject = _string(args.get("subject"), "subject", required=True)
    if len(_task_rows(store)) >= _MAX_TASKS:
        raise ValueError(f"The run task list is limited to {_MAX_TASKS} items")
    task_id = _next_task_id(store)
    blockers = (_checked_blockers(args["blockedBy"], task_id, store)
                if "blockedBy" in args else [])
    metadata = {
        "subject": subject,
        "description": _string(args.get("description", ""), "description"),
        "activeForm": _string(args.get("activeForm", ""), "activeForm"),
        "owner": _string(args.get("owner", ""), "owner", maximum=_MAX_OWNER),
        "blockedBy": blockers,
    }
    task_status = _status(args.get("status", "pending"))
    store.write([{"id": task_id, "content": subject, "status": task_status}], merge=True)
    _details(store)[task_id] = metadata
    return {"task": _find_task(store, task_id), "revision": store.snapshot().get("revision", 0)}


def _call_task_update(args: dict[str, Any], store: Any) -> dict[str, Any]:
    task_id = _string(args.get("taskId"), "taskId", required=True, maximum=100)
    before = _find_task(store, task_id)
    details = _details(store)
    metadata = {key: before[key] for key in (
        "subject", "description", "activeForm", "owner", "blockedBy",
    )}
    todo_status = before["status"]
    if "subject" in args:
        metadata["subject"] = _string(args["subject"], "subject", required=True)
    if "description" in args:
        metadata["description"] = _string(args["description"], "description")
    if "activeForm" in args:
        metadata["activeForm"] = _string(args["activeForm"], "activeForm")
    if "owner" in args:
        metadata["owner"] = _string(args["owner"], "owner", maximum=_MAX_OWNER)
    if "blockedBy" in args:
        metadata["blockedBy"] = _checked_blockers(args["blockedBy"], task_id, store)
    if "status" in args:
        todo_status = _status(args["status"])
    if todo_status != before["status"] or metadata["subject"] != before["subject"]:
        store.write([{
            "id": task_id, "content": metadata["subject"], "status": todo_status,
        }], merge=True)
    details[task_id] = metadata
    return {"task": _find_task(store, task_id), "revision": store.snapshot().get("revision", 0)}


def _call_todo_write(args: dict[str, Any], store: Any) -> dict[str, Any]:
    todos = args.get("todos")
    if not isinstance(todos, list):
        raise ValueError("todos must be a list")
    if len(todos) > _MAX_TASKS:
        raise ValueError(f"todos is limited to {_MAX_TASKS} items")
    normalized: list[dict[str, str]] = []
    metadata: dict[str, dict[str, Any]] = {}
    used: set[str] = set()
    for index, item in enumerate(todos, start=1):
        if not isinstance(item, dict):
            raise ValueError("each todo must be an object")
        task_id = _string(item.get("id", f"todo-{index}"), "todo id", required=True, maximum=100)
        if task_id in used:
            raise ValueError(f"duplicate todo id {task_id!r}")
        used.add(task_id)
        content = _string(item.get("content"), "content", required=True)
        task_status = _status(item.get("status"))
        active_form = _string(item.get("activeForm", ""), "activeForm")
        normalized.append({"id": task_id, "content": content, "status": task_status})
        metadata[task_id] = {
            "subject": content, "description": "", "activeForm": active_form,
            "owner": "", "blockedBy": [],
        }
    snapshot = store.write(normalized)
    details = _details(store)
    # Replacing the checklist replaces metadata for IDs supplied by this write.
    details.clear()
    details.update({key: value for key, value in metadata.items()
                    if key in {str(item["id"]) for item in snapshot.get("todos", [])}})
    return {
        "todos": _task_rows(store),
        "revision": snapshot.get("revision", 0),
    }


def call_task_tool(name: str, args: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """Dispatch one task-list call against the TodoStore owned by ``runtime``."""
    if not isinstance(args, dict):
        return _result({"error": "tool arguments must be an object"}, is_error=True)
    try:
        store = _todo_store(runtime)
        if name == "TaskCreate":
            data = _call_task_create(args, store)
        elif name == "TaskGet":
            task_id = _string(args.get("taskId"), "taskId", required=True, maximum=100)
            data = {"task": _find_task(store, task_id)}
        elif name == "TaskList":
            data = {"tasks": _task_rows(store)}
        elif name == "TaskUpdate":
            data = _call_task_update(args, store)
        elif name == "TodoWrite":
            data = _call_todo_write(args, store)
        else:
            raise ValueError(f"Unknown task-list tool: {name}")
        return _result(data)
    except (ValueError, TypeError, AttributeError) as exc:
        return _result({"error": str(exc)}, is_error=True)
