"""Validation helpers for files declared to the user as run deliverables."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def record_workspace_changes(home: Path, session_id: str, turn_id: str, *, workspace: str | None,
                             tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    """Persist tool-reported changes under the turn owning the successful operation."""
    if result.get("is_error") or not workspace or workspace.startswith("ssh://"):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    paths = list(data.get("changed_paths") or data.get("paths") or [])
    if tool in {"present", "local_edit", "local_edit_batch", "create_document", "create_spreadsheet", "create_presentation"}:
        if args.get("path"):
            paths.append(args["path"])
    if tool == "local_file" and args.get("action") in {"write", "append", "delete", "move", "copy"}:
        paths.extend(value for key in ("path", "destination") if (value := args.get(key)))
    root = Path(workspace).resolve()
    admitted = set()
    for raw in paths:
        if not isinstance(raw, str):
            continue
        target = Path(raw)
        target = (root / target).resolve() if not target.is_absolute() else target.resolve()
        try:
            admitted.add(target.relative_to(root).as_posix())
        except ValueError:
            continue
    if not admitted:
        return None
    payload = {"turn_id": turn_id, "tool": tool, "paths": sorted(admitted),
               "kind": "deliverable" if tool == "present" else "changed"}
    from atlas.engine.session_sync import append_session_event
    append_session_event(home, session_id, "workspace/changes", payload)
    return payload


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
