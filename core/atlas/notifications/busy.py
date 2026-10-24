"""Persistent user busy window and deferred notification summary."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from typing import Any

_LOCK = threading.RLock()


def _path() -> Path:
    from atlas.config import get_config
    return get_config().db_path.parent / "busy-state.json"


def _read() -> dict[str, Any]:
    try:
        value = json.loads(_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(value: dict[str, Any]) -> None:
    path = _path(); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def status() -> dict[str, Any]:
    with _LOCK:
        state = _read()
        until = float(state.get("until", 0) or 0)
        if until and until <= time.time():
            state["until"] = 0
            _write(state)
        return {"busy": bool(state.get("until")), "until": state.get("until") or None,
                "deferred": len(state.get("deferred", []))}


def set_busy(seconds: float | None) -> dict[str, Any]:
    with _LOCK:
        state = _read()
        if seconds is None or seconds <= 0:
            state["until"] = 0
        else:
            state["until"] = time.time() + seconds
        _write(state)
        return status()


def defer(title: str, body: str) -> bool:
    """Save notification while busy; return true when it was suppressed."""
    with _LOCK:
        state = _read()
        until = float(state.get("until", 0) or 0)
        if not until or until <= time.time():
            if until:
                state["until"] = 0; _write(state)
            return False
        rows = state.get("deferred", [])
        rows = rows if isinstance(rows, list) else []
        rows.append({"title": str(title)[:120], "body": str(body)[:2000]})
        state["deferred"] = rows[-100:]
        _write(state)
        return True


def take_summary() -> str:
    with _LOCK:
        state = _read()
        rows = state.get("deferred", [])
        if not rows:
            return ""
        state["deferred"] = []
        _write(state)
        return "忙碌期间有 " + str(len(rows)) + " 条更新：\n" + "\n".join(
            f"• {row.get('title', 'Atlas')}: {row.get('body', '')}" for row in rows[-20:] if isinstance(row, dict)
        )
