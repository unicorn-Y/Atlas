"""Persistent standing instructions injected into matching agent turns.

Standing orders are contextual guidance, not scheduled work. Matching a turn
adds bounded system context and appends an audit receipt; it never dispatches a
cron job or heartbeat.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

_LOCK = threading.RLock()
_MAX_ORDERS = 500
_MAX_INJECTION = 12_000
_MAX_INSTRUCTION = 8_000


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _paths() -> tuple[Path, Path]:
    root = DATA_ROOT / "data"
    return root / "standing-orders.json", root / "standing-order-audit.jsonl"


def _load() -> list[dict[str, Any]]:
    path, _ = _paths()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save(rows: list[dict[str, Any]]) -> None:
    path, _ = _paths()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def normalize(raw: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or {})
    base.update(raw)
    owner = str(base.get("owner_agent_id") or "").strip()
    instruction = str(base.get("instruction") or "").strip()
    scope = base.get("scope") if isinstance(base.get("scope"), dict) else {}
    trigger = base.get("trigger") if isinstance(base.get("trigger"), dict) else {}
    keywords = trigger.get("keywords", [])
    if not owner or len(owner) > 128:
        raise ValueError("owner_agent_id is required (max 128 characters)")
    if not instruction or len(instruction) > _MAX_INSTRUCTION:
        raise ValueError(f"instruction must contain 1–{_MAX_INSTRUCTION} characters")
    scope_kind = str(scope.get("kind") or "all")
    if scope_kind not in {"all", "workspace"}:
        raise ValueError("scope.kind must be all or workspace")
    workspace = str(scope.get("workspace") or "").strip()
    if scope_kind == "workspace" and not workspace:
        raise ValueError("workspace scope requires scope.workspace")
    if not isinstance(keywords, list) or len(keywords) > 32:
        raise ValueError("trigger.keywords must be a list of at most 32 phrases")
    clean_keywords = [str(value).strip()[:120] for value in keywords if str(value).strip()]
    order_id = str(base.get("id") or uuid.uuid4().hex[:12])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", order_id):
        raise ValueError("invalid standing order id")
    return {
        "id": order_id,
        "name": str(base.get("name") or instruction[:48]).strip()[:120],
        "owner_agent_id": owner,
        "enabled": bool(base.get("enabled", True)),
        "instruction": instruction,
        "scope": {"kind": scope_kind, "workspace": workspace},
        "trigger": {"kind": "turn", "keywords": clean_keywords},
        "created_at": str(base.get("created_at") or _stamp()),
        "updated_at": _stamp(),
    }


def list_orders(query: str = "", owner_agent_id: str = "") -> list[dict[str, Any]]:
    query = query.strip().casefold()
    with _LOCK:
        rows = _load()
    result = [row for row in rows if (not owner_agent_id or row.get("owner_agent_id") == owner_agent_id)]
    if query:
        result = [row for row in result if query in " ".join((
            str(row.get("name", "")), str(row.get("instruction", "")),
            str(row.get("owner_agent_id", "")), json.dumps(row.get("scope", {}), ensure_ascii=False),
            json.dumps(row.get("trigger", {}), ensure_ascii=False),
        )).casefold()]
    return result


def create_order(raw: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        rows = _load()
        if len(rows) >= _MAX_ORDERS:
            raise ValueError(f"最多保存 {_MAX_ORDERS} 条常驻指令")
        row = normalize(raw)
        if any(item.get("id") == row["id"] for item in rows):
            raise ValueError("standing order id already exists")
        rows.append(row)
        _save(rows)
    return row


def update_order(order_id: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    with _LOCK:
        rows = _load()
        for index, old in enumerate(rows):
            if old.get("id") == order_id:
                row = normalize(raw, existing=old)
                row["id"] = order_id
                rows[index] = row
                _save(rows)
                return row
    return None


def delete_order(order_id: str) -> bool:
    with _LOCK:
        rows = _load()
        kept = [row for row in rows if row.get("id") != order_id]
        if len(kept) == len(rows):
            return False
        _save(kept)
        return True


def recent_audit(*, order_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
    _, path = _paths()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-min(max(limit, 1), 200):]
    except OSError:
        return []
    rows = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not order_id or row.get("order_id") == order_id:
            rows.append(row)
    return rows


def matching_orders(owner_agent_id: str, workspace: str | None, message: str) -> list[dict[str, Any]]:
    """Select matching active orders, audit triggers, and return bounded context."""
    if not owner_agent_id:
        return []
    text = (message or "")[:20_000]
    selected: list[dict[str, Any]] = []
    total = 0
    with _LOCK:
        rows = _load()
        _, audit_path = _paths()
        for row in rows:
            if not row.get("enabled") or row.get("owner_agent_id") != owner_agent_id:
                continue
            scope = row.get("scope") or {}
            if scope.get("kind") == "workspace" and str(workspace or "").casefold() != str(scope.get("workspace") or "").casefold():
                continue
            keywords = (row.get("trigger") or {}).get("keywords") or []
            if keywords and not any(str(word).casefold() in text.casefold() for word in keywords):
                continue
            content = str(row.get("instruction") or "")[:_MAX_INSTRUCTION]
            if total + len(content) > _MAX_INJECTION:
                break
            total += len(content)
            selected.append(row)
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "order_id": row["id"], "name": row.get("name"),
                    "owner_agent_id": owner_agent_id, "conversation_workspace": workspace or "",
                    "triggered_at": _stamp(), "matched_keywords": [w for w in keywords if str(w).casefold() in text.casefold()],
                }, ensure_ascii=False) + "\n")
    return selected
