"""Small durable local alert stream shared by diagnostics and runtime events."""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

_LOCK = threading.Lock()
_PATH = Path(DATA_ROOT) / "data" / "diagnostic-alerts.json"


def _redact(text: str) -> str:
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret|credential)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED]", text)


def _read() -> list[dict[str, Any]]:
    try:
        value = json.loads(_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []


def record_alert(category: str, title: str, detail: str, *, target: str = "diagnostics", dedupe_key: str = "") -> dict[str, Any]:
    """Append a bounded alert; identical active alerts are coalesced."""
    with _LOCK:
        rows = _read()
        if dedupe_key:
            existing = next((row for row in rows if row.get("dedupe_key") == dedupe_key and not row.get("read")), None)
            if existing:
                existing["last_seen"] = datetime.now(timezone.utc).isoformat()
                _PATH.parent.mkdir(parents=True, exist_ok=True)
                _PATH.write_text(json.dumps(rows[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
                return existing
        row = {"id": uuid.uuid4().hex, "category": category, "title": _redact(title)[:200], "detail": _redact(detail)[:2000],
               "target": target, "read": False, "created_at": datetime.now(timezone.utc).isoformat(), "dedupe_key": dedupe_key}
        rows.append(row)
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(rows[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
        return row
