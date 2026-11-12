"""Callable session lifecycle tools backed by Atlas's existing durable stores."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def _result(data: Any) -> dict[str, Any]:
    return {"content": json.dumps(data, ensure_ascii=False, default=str),
            "data": data, "outcome": "completed"}


async def dispatch_lifecycle_tool(
    name: str, arguments: dict[str, Any], runtime: Any,
) -> dict[str, Any] | None:
    """Execute local automation and conversation lifecycle tools, or return None."""
    if name not in {"CronCreate", "CronList", "CronUpdate", "CronDelete", "ScheduleWakeup", "EndConversation"}:
        return None

    if name == "EndConversation":
        reason = str(arguments.get("reason") or "").strip()
        if not reason:
            return {"content": "reason must not be empty.", "is_error": True, "outcome": "failed"}
        callback = getattr(runtime, "end_conversation_callback", None)
        if callable(callback):
            callback(reason)
        else:
            setattr(runtime, "end_conversation_reason", reason)
            cancel_event = getattr(runtime, "cancel_event", None)
            if cancel_event is not None:
                cancel_event.set()
        queue = getattr(runtime, "event_queue", None)
        if queue is not None:
            await queue.put({"type": "conversation_ended", "reason": reason})
        return _result({"ended": True, "reason": reason})

    from atlas.automation import get_automation_engine
    from atlas.automation.store import normalize_record

    engine = get_automation_engine()
    store = engine.store

    if name != "CronList" and not engine.started:
        return {"content": "The persistent scheduler is not running; no task was created or changed.",
                "is_error": True, "outcome": "failed"}

    if name == "CronList":
        return _result({"automations": store.list()})

    if name == "CronDelete":
        automation_id = str(arguments.get("id") or "").strip()
        if not automation_id or store.get(automation_id) is None:
            return {"content": "Automation not found.", "is_error": True, "outcome": "failed"}
        await engine.remove(automation_id)
        return _result({"deleted": store.delete(automation_id), "id": automation_id})

    if name == "ScheduleWakeup":
        conversation_id = str(getattr(runtime, "conversation_id", "") or "").strip()
        if not conversation_id:
            return {"content": "This run has no conversation id.", "is_error": True, "outcome": "failed"}
        automation_id = f"wakeup-{hashlib.sha256(conversation_id.encode()).hexdigest()[:24]}"
        if bool(arguments.get("stop")):
            existing = store.get(automation_id)
            if existing is None:
                return _result({"stopped": False, "reason": "no pending wakeup"})
            await engine.remove(automation_id)
            store.delete(automation_id)
            return _result({"stopped": True, "id": automation_id})
        prompt = str(arguments.get("prompt") or "Resume this conversation and continue the previous task.").strip()
        when = str(arguments.get("at") or "").strip()
        if not when:
            return {"content": "at must be an ISO 8601 timestamp with timezone.", "is_error": True, "outcome": "failed"}
        try:
            parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
        except ValueError:
            return {"content": "at must be a valid timezone-aware ISO 8601 timestamp.", "is_error": True, "outcome": "failed"}
        record = normalize_record({
            "id": automation_id, "name": f"会话唤醒：{conversation_id[:8]}",
            "trigger": {"kind": "date", "at": parsed.isoformat()},
            "payload": {"kind": "agent_turn", "message": prompt,
                        "conversation_id": conversation_id},
            "delivery": {"mode": "none"},
        })
        saved = store.put(record)
        await engine.sync_automation(saved)
        return _result({"scheduled": True, "automation": saved})

    automation_id = str(arguments.get("id") or "").strip()
    if name == "CronUpdate":
        current = store.get(automation_id) if automation_id else None
        if current is None:
            return {"content": "Automation not found.", "is_error": True, "outcome": "failed"}
        trigger = dict(current["trigger"])
        if "schedule" in arguments:
            trigger = _schedule_trigger(str(arguments["schedule"]), str(arguments.get("timezone") or ""))
        payload = dict(current["payload"])
        if "prompt" in arguments:
            payload["message"] = str(arguments["prompt"])
        updates: dict[str, Any] = {"trigger": trigger, "payload": payload}
        if "name" in arguments:
            updates["name"] = str(arguments["name"])
        if "enabled" in arguments:
            updates["enabled"] = bool(arguments["enabled"])
        saved = store.put({**current, **updates})
    else:
        automation_id = str(arguments.get("id") or "").strip()
        record = normalize_record({
            "id": automation_id or None,
            "name": str(arguments.get("name") or "").strip(),
            "trigger": _schedule_trigger(str(arguments.get("schedule") or ""),
                                         str(arguments.get("timezone") or "")),
            "payload": {"kind": "agent_turn", "message": str(arguments.get("prompt") or "").strip()},
            "delivery": {"mode": "none"},
        })
        saved = store.put(record)
    await engine.sync_automation(saved)
    return _result({"automation": saved})


def _schedule_trigger(schedule: str, timezone: str) -> dict[str, Any]:
    value = schedule.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return {"kind": "cron", "cron_expr": value, "tz": timezone}
    if parsed.tzinfo is None:
        raise ValueError("one-shot schedule timestamps must include a timezone")
    return {"kind": "date", "at": parsed.isoformat()}
