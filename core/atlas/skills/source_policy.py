"""Persistent per-source skill creation/loading policy."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

_DEFAULT = {"schema_version": 1, "create": {"bundled": True, "local": True, "marketplace": True, "evolved": True},
            "load": {"bundled": True, "local": True, "marketplace": True, "evolved": True}, "overrides": {}}


def _path() -> Path:
    return DATA_ROOT / "data" / "skill-source-policy.json"


def get_policy() -> dict[str, Any]:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            merged = {**_DEFAULT, **raw}
            for key in ("create", "load"):
                merged[key] = {**_DEFAULT[key], **(raw.get(key) if isinstance(raw.get(key), dict) else {})}
            merged["overrides"] = raw.get("overrides") if isinstance(raw.get("overrides"), dict) else {}
            return merged
    except (OSError, json.JSONDecodeError):
        pass
    return json.loads(json.dumps(_DEFAULT))


def set_policy(value: dict[str, Any]) -> dict[str, Any]:
    current = get_policy()
    for key in ("create", "load"):
        if isinstance(value.get(key), dict):
            for category, enabled in value[key].items():
                if category in current[key] and isinstance(enabled, bool):
                    current[key][category] = enabled
    if isinstance(value.get("overrides"), dict):
        current["overrides"] = {str(name): bool(enabled) for name, enabled in value["overrides"].items()
                                if isinstance(name, str) and name.strip() and isinstance(enabled, bool)}
    target = _path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return current


def skill_category(skill: Any) -> str:
    source = str(getattr(skill, "source", "") or "").lower()
    path = str(getattr(skill, "path", "")).replace("\\", "/").lower()
    if "evolved" in source or "learned" in source or "/evolved/" in path:
        return "evolved"
    if "market" in source or "clawhub" in source or "github" in source:
        return "marketplace"
    if source in {"atlas", "bundled", "built-in", "builtin"}:
        return "bundled"
    return "local"


def skill_load_allowed(skill: Any) -> bool:
    policy = get_policy()
    override = policy["overrides"].get(str(getattr(skill, "name", "")))
    return override if isinstance(override, bool) else bool(policy["load"].get(skill_category(skill), True))
