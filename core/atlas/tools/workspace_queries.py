"""Workspace-scoped Glob and Grep model tools.

Behavior reference: anomalyco/opencode@7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937,
packages/core/src/tool/plugin/{glob,grep}.ts (MIT). This is an independent
implementation against Atlas's workspace boundary; no upstream source is copied.
"""

from __future__ import annotations

import re
import fnmatch
import os
from pathlib import Path
from typing import Any

_MAX_LIMIT = 2000
_MAX_FILE_BYTES = 2 * 1024 * 1024
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build"}


def _rooted_path(workspace: str, raw: Any) -> tuple[Path, Path]:
    root = Path(workspace).expanduser().resolve()
    candidate = (root / str(raw or ".")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Query path must remain inside the active workspace.") from exc
    if not candidate.exists():
        raise FileNotFoundError(f"Path not found: {candidate}")
    return root, candidate


def _limit(value: Any, default: int = 200) -> int:
    try:
        number = int(value) if value is not None else default
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if number < 1:
        raise ValueError("limit must be at least 1")
    return min(number, _MAX_LIMIT)


def glob_workspace(workspace: str, *, pattern: str, path: str | None = None,
                   hidden: bool = False, limit: int = 200) -> dict[str, Any]:
    root, base = _rooted_path(workspace, path)
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty glob pattern")
    if not base.is_dir():
        raise ValueError("path must point to a directory")
    maximum = _limit(limit)
    matches: list[str] = []
    try:
        for item in base.glob(pattern):
            resolved = item.resolve()
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            if not hidden and any(part.startswith(".") for part in relative.parts):
                continue
            if any(part in _SKIP_DIRS for part in relative.parts):
                continue
            matches.append(relative.as_posix())
            if len(matches) > maximum:
                break
    except (OSError, ValueError, NotImplementedError) as exc:
        raise ValueError(f"Invalid or unreadable glob query: {exc}") from exc
    matches.sort(key=str.casefold)
    truncated = len(matches) > maximum
    return {"path": str(base), "matches": matches[:maximum], "truncated": truncated}


def grep_workspace(workspace: str, *, pattern: str, path: str | None = None,
                   include: str | None = None, literal: bool = False,
                   case_sensitive: bool = True, limit: int = 200) -> dict[str, Any]:
    root, base = _rooted_path(workspace, path)
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must be a non-empty search pattern")
    maximum = _limit(limit)
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        expression = re.compile(re.escape(pattern) if literal else pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression: {exc}") from exc

    if base.is_file():
        files = [base] if not include or fnmatch.fnmatch(base.name, include) else []
    elif base.is_dir():
        files = []
        for parent, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and
                       (include is not None or not name.startswith("."))]
            for name in names:
                item = Path(parent) / name
                try:
                    relative = item.resolve().relative_to(root)
                except (OSError, ValueError):
                    continue
                if not include and not any(part.startswith(".") for part in relative.parts):
                    files.append(item)
                elif include and fnmatch.fnmatch(name, include):
                    files.append(item)
                if len(files) >= 10000:
                    break
            if len(files) >= 10000:
                break
    else:
        raise ValueError("path must point to a file or directory")

    matches: list[dict[str, Any]] = []
    for item in files:
        try:
            resolved = item.resolve()
            relative = resolved.relative_to(root)
            if any(part in _SKIP_DIRS for part in relative.parts) or item.stat().st_size > _MAX_FILE_BYTES:
                continue
            raw = item.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
        for number, line in enumerate(raw.splitlines(), 1):
            if expression.search(line):
                matches.append({"path": relative.as_posix(), "line": number, "text": line})
                if len(matches) > maximum:
                    return {"path": str(base), "matches": matches[:maximum], "truncated": True}
    return {"path": str(base), "matches": matches, "truncated": False}


def query_tool_schemas() -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {
            "name": "glob", "description": "Find workspace files with a glob pattern.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
                "hidden": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
            }, "required": ["pattern"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "grep", "description": "Search workspace file contents with a literal or regular expression.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
                "include": {"type": "string"}, "literal": {"type": "boolean"},
                "caseSensitive": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
            }, "required": ["pattern"], "additionalProperties": False},
        }},
    ]
