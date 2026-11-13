"""Validation helpers for files declared to the user as run deliverables."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_presented_file(args: dict[str, Any], *, workspace: str | None) -> dict[str, str]:
    """Return the artifact event payload for an existing file in the active workspace."""
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("present requires a file path inside the current workspace")
    if not workspace or workspace.startswith("ssh://"):
        raise ValueError("present requires a local current workspace")

    root = Path(workspace).expanduser().resolve()
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("present only accepts files inside the current workspace") from exc
    if not target.is_file():
        raise ValueError(f"present file does not exist: {target}")

    suffix = target.suffix.lower()
    kind = (
        "spreadsheet" if suffix in {".xlsx", ".xls", ".ods", ".csv"}
        else "presentation" if suffix in {".pptx", ".ppt", ".odp"}
        else "document"
    )
    payload = {
        "path": str(target), "kind": kind, "tool": "present",
        "title": str(args.get("title") or target.name).strip(),
        "summary": str(args.get("summary") or "交付物").strip(),
    }
    if not payload["title"]:
        payload["title"] = target.name
    if not payload["summary"]:
        payload["summary"] = "交付物"
    return payload
