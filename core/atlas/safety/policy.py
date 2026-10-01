"""Persistent safety preferences and bounded recent review log."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from atlas.config import get_config
from atlas.safety.detection import RULES, Assessment, assess

_LOG: list[dict[str, Any]] = []
_DENIALS: dict[str, int] = {}
_DEFAULTS = {
    "reviewer": "smart", "always_allow": [], "always_deny": [], "trusted_paths": [],
}


def _path() -> Path:
    return get_config().db_path.parent / "safety.json"


def get_settings() -> dict[str, Any]:
    try:
        stored = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    return {**_DEFAULTS, **stored}


def update_settings(value: dict[str, Any]) -> dict[str, Any]:
    current = get_settings()
    if value.get("reviewer", current["reviewer"]) not in {"smart", "rules", "off"}:
        raise ValueError("reviewer must be smart, rules, or off")
    updated = {**current, **value}
    for key in ("always_allow", "always_deny", "trusted_paths"):
        if not isinstance(updated[key], list) or any(not isinstance(item, str) for item in updated[key]):
            raise ValueError(f"{key} must be a list of strings")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated


def evaluate_rules(
    tool: str, arguments: dict[str, Any], *, workspace: str | None = None,
    allowed_paths: list[str] | None = None, write_capable_mcp: bool = False,
) -> Assessment:
    """Findings for one write; trusted_paths from settings count as part of the work folder."""
    roots = [*(allowed_paths or []), *get_settings().get("trusted_paths", [])]
    return assess(tool, arguments, workspace=workspace, allowed_roots=roots,
                  write_capable_mcp=write_capable_mcp)


def append_log(entry: dict[str, Any]) -> None:
    _LOG.append({**entry, "at": time.time()})
    del _LOG[:-200]


def get_log(limit: int = 50) -> list[dict[str, Any]]:
    return list(reversed(_LOG[-max(1, min(limit, 200)):]))


def rule_catalog() -> list[dict[str, str]]:
    return [{"id": key, "description": value} for key, value in RULES.items()]


def record_decision(run_id: str, decision: str, threshold: int = 3) -> bool:
    if decision == "allow":
        _DENIALS.pop(run_id, None)
        return False
    if decision != "deny":
        return _DENIALS.get(run_id, 0) >= threshold
    _DENIALS[run_id] = _DENIALS.get(run_id, 0) + 1
    return _DENIALS[run_id] >= max(1, threshold)
