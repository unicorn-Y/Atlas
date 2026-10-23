"""Workspace-scoped Glob and Grep model tools.

Behavior reference: anomalyco/opencode@7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937,
packages/core/src/tool/plugin/{glob,grep}.ts (MIT). This is an independent
implementation against Atlas's workspace boundary; no upstream source is copied.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

_MAX_LIMIT = 2000
_MAX_FILE_BYTES = 2 * 1024 * 1024
# Cap on how many candidate files one query may collect. This is a scan budget, not a
# limit on results: files are sorted first so the truncation is deterministic instead of
# silently dropping whichever tree the filesystem happened to yield last.
_MAX_FILES = 20000
# Always pruned, whatever the query looks like. Everything here is either a copy of the
# repository or machine-local output that .gitignore already excludes -- never source the
# agent should read twice:
#   * .worktrees            -- full checkouts; one `include="*.py"` grep over them cost a
#                              real run 175s and filled the context with duplicate hits.
#   * artifacts/, _shots/   -- gitignored measurement output: 167k files, 16s of a 20s walk.
#   * data/upstream/        -- 195k files / 6 GB of upstream source staging (.gitignore:156).
#   * frontend/backend-release/ -- packaged backend copy (.gitignore:64).
#   * data/pytest-tmp/, cache/  -- rebuilt test and cache output.
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build",
    ".worktrees", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".nox", "site-packages", ".next", ".turbo", "target",
    "artifacts", "_shots", "_audit", "survey_images", "reflection_receipts",
    "backend-release", "pytest-tmp", "windows-release", "win-unpacked",
}
# Matched against the whole relative path, for trees whose name is not unique enough to
# prune globally (a real project may well have its own data/upstream).
_SKIP_PATHS = {
    "data/upstream", "data/pytest-tmp", "cache", "runs",
}


def _prune(root: Path, parent: Path, names: list[str], *, honour_skip: bool = True) -> list[str]:
    """Drop directories that a workspace search must never descend into.

    ``honour_skip=False`` is used when the caller pointed ``path`` inside a normally
    pruned tree: an explicit request must win, otherwise the tool answers "no matches"
    to a question it never actually asked the filesystem.
    """
    if not honour_skip:
        return [name for name in names if not name.startswith(".")]
    try:
        rel_parent = Path(parent).relative_to(root).as_posix()
    except ValueError:
        rel_parent = "."
    kept: list[str] = []
    for name in names:
        if name in _SKIP_DIRS or name.startswith("."):
            continue
        if rel_parent == ".":
            candidate = name
        else:
            candidate = f"{rel_parent}/{name}"
        if candidate in _SKIP_PATHS:
            continue
        kept.append(name)
    return kept


def _inside_skipped_tree(root: Path, base: Path) -> bool:
    """True when ``base`` itself sits inside (or is) a tree that searches normally prune."""
    try:
        relative = base.relative_to(root)
    except ValueError:
        return False
    if not relative.parts:
        return False
    return _is_skipped_relative(relative) or relative.as_posix() in _SKIP_PATHS


def _is_skipped_relative(relative: Path) -> bool:
    """True when a workspace-relative path lies under a pruned tree."""
    parts = relative.parts
    if any(part in _SKIP_DIRS for part in parts):
        return True
    return any(
        "/".join(parts[: index + 1]) in _SKIP_PATHS
        for index in range(len(parts) - 1)
    )


def _iter_glob(root: Path, base: Path, pattern: str, *, hidden: bool):
    """Yield workspace-relative matches for a glob pattern without walking pruned trees.

    ``Path.glob`` cannot be used directly: pruning has to happen while descending, because
    ``**`` would otherwise traverse ``data/upstream`` and only then discard the results.
    """
    recursive = "**" in pattern
    honour_skip = not _inside_skipped_tree(root, base)
    matcher = re.compile(fnmatch.translate(pattern))
    if not recursive:
        for item in base.glob(pattern):
            try:
                yield item.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
        return
    for parent, dirs, names in os.walk(base, followlinks=False):
        kept = _prune(root, Path(parent), dirs, honour_skip=honour_skip)
        if not hidden:
            kept = [name for name in kept if not name.startswith(".")]
        dirs[:] = kept
        for name in names:
            if not hidden and name.startswith("."):
                continue
            try:
                relative = (Path(parent) / name).resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            tail = relative.as_posix()
            if matcher.match(tail) or fnmatch.fnmatch(tail, pattern):
                yield relative


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


def _grep_page(value: Any, offset: Any) -> tuple[int, int]:
    """Normalize grep pagination while keeping even an unbounded request finite."""
    try:
        start = int(offset or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("offset must be a non-negative integer") from exc
    if start < 0:
        raise ValueError("offset must be a non-negative integer")
    try:
        page = int(value) if value is not None else 250
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if page < 0:
        raise ValueError("limit must be non-negative")
    # `0` asks for all results, but a workspace scan must still be bounded.
    return start, _MAX_LIMIT if page == 0 else min(page, _MAX_LIMIT)


def glob_workspace(workspace: str, *, pattern: str, path: str | None = None,
                   hidden: bool = False, limit: int = 100) -> dict[str, Any]:
    root, base = _rooted_path(workspace, path)
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty glob pattern")
    if not base.is_dir():
        raise ValueError("path must point to a directory")
    maximum = _limit(limit)
    matches: list[str] = []
    honour_result_skip = not _inside_skipped_tree(root, base)
    try:
        for relative in _iter_glob(root, base, pattern, hidden=hidden):
            if honour_result_skip and _is_skipped_relative(relative):
                continue
            matches.append(relative.as_posix())
            if len(matches) > maximum:
                break
    except (OSError, ValueError, NotImplementedError) as exc:
        raise ValueError(f"Invalid or unreadable glob query: {exc}") from exc
    matches.sort(key=str.casefold)
    truncated = len(matches) > maximum
    result = {"path": str(base), "matches": matches[:maximum], "truncated": truncated}
    if truncated:
        result["hint"] = "Results were truncated; narrow the path or use a more specific pattern."
    return result


def grep_workspace(workspace: str, *, pattern: str, path: str | None = None,
                   include: str | None = None, literal: bool = False,
                   case_sensitive: bool = True, limit: int | None = None,
                   offset: int = 0) -> dict[str, Any]:
    root, base = _rooted_path(workspace, path)
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("pattern must be a non-empty search pattern")
    start, maximum = _grep_page(limit, offset)
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        expression = re.compile(re.escape(pattern) if literal else pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression: {exc}") from exc

    if base.is_file():
        files = [base] if not include or fnmatch.fnmatch(base.name, include) else []
    elif base.is_dir():
        files = []
        # Dot-directories are pruned unconditionally. Passing `include` used to disable
        # this guard (`include is not None or not name.startswith(".")`), so narrowing a
        # search to *.py made it walk every hidden tree, .worktrees copies included.
        skipped_dirs = 0
        # An explicitly targeted path inside a normally pruned tree must be searched:
        # answering "no matches" for a directory the user named is worse than being slow.
        honour_skip = not _inside_skipped_tree(root, base)
        for parent, dirs, names in os.walk(base, followlinks=False):
            kept = _prune(root, Path(parent), dirs, honour_skip=honour_skip)
            skipped_dirs += len(dirs) - len(kept)
            dirs[:] = kept
            for name in names:
                if name.startswith(".") and not include:
                    continue
                if include and not fnmatch.fnmatch(name, include):
                    continue
                files.append(Path(parent) / name)
        # Deterministic order: a truncation must not depend on filesystem traversal order,
        # and it must not silently hide a whole top-level tree. `core/` sorting after
        # `cache/` is exactly how a real search returned zero hits for a symbol that exists.
        files.sort(key=lambda item: item.as_posix().casefold())
    else:
        raise ValueError("path must point to a file or directory")

    truncated_files = len(files) > _MAX_FILES
    if truncated_files:
        files = files[:_MAX_FILES]

    matches: list[dict[str, Any]] = []
    match_count = 0
    honour_result_skip = not _inside_skipped_tree(root, base)
    for item in files:
        try:
            resolved = item.resolve()
            relative = resolved.relative_to(root)
            if honour_result_skip and any(part in _SKIP_DIRS for part in relative.parts):
                continue
            if item.stat().st_size > _MAX_FILE_BYTES:
                continue
            raw = item.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
        for number, line in enumerate(raw.splitlines(), 1):
            if expression.search(line):
                match_count += 1
                if match_count <= start:
                    continue
                text = line
                clipped = len(text) > 500
                if clipped:
                    text = text[:500] + "… [line truncated]"
                matches.append({"path": relative.as_posix(), "line": number, "text": text,
                                **({"line_truncated": True} if clipped else {})})
                if len(matches) > maximum:
                    # Inspect one additional matching line to report real truncation.
                    result = {"path": str(base), "matches": matches, "truncated": True,
                              "scanned_files": len(files), "offset": start,
                              "next_offset": start + len(matches)}
                    if truncated_files:
                        result["scan_truncated"] = True
                    result["matches"] = matches[:maximum]
                    result["next_offset"] = start + maximum
                    return result
    result: dict[str, Any] = {"path": str(base), "matches": matches, "truncated": False,
                              "scanned_files": len(files), "offset": start}
    if truncated_files:
        # Say so explicitly. Returning an empty match list for a symbol that exists is what
        # sends an agent into a repeat-the-same-search loop; an honest "I did not look
        # everywhere" lets it narrow the path instead.
        result["scan_truncated"] = True
        result["hint"] = (
            f"Only the first {len(files)} of {len(files) + 1}+ candidate files were searched. "
            "Narrow `path` or add `include` to cover the rest."
        )
    return result


def query_tool_schemas() -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {
            "name": "glob", "description": "Find workspace files with a glob pattern.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
                "hidden": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT, "default": 100},
            }, "required": ["pattern"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "grep", "description": "Search workspace file contents with a literal or regular expression.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
                "include": {"type": "string"}, "literal": {"type": "boolean"},
                "caseSensitive": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 0, "maximum": _MAX_LIMIT,
                          "default": 250, "description": "Number of matches to return; 0 returns up to the safe cap."},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            }, "required": ["pattern"], "additionalProperties": False},
        }},
    ]
