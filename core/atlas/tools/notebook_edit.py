"""Workspace-scoped Jupyter notebook cell editing.

Behavior reference: Anthropic's public Claude Code NotebookEdit documentation,
https://code.claude.com/docs/en/tools-reference#notebookedit-tool-behavior.
This is an independent implementation; no proprietary Claude Code source or
closed-source implementation code is copied or ported. Atlas adds a read mode
because its tool contract needs direct cell inspection.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


def notebook_edit_tool_schema() -> dict[str, Any]:
    """Return the OpenAI-style function schema for the notebook editor."""
    return {
        "type": "function",
        "function": {
            "name": "notebook_edit",
            "description": (
                "Read notebook cells, or insert, replace, or delete one cell in an existing "
                "Jupyter notebook. notebook_path must be relative to the active workspace. "
                "edit_mode defaults to replace. In insert mode, cell_id is the cell after "
                "which the new cell is inserted; omit it to insert at the start."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "notebook_path": {
                        "type": "string",
                        "description": "Workspace-relative path to an existing .ipynb file.",
                    },
                    "edit_mode": {
                        "type": "string",
                        "enum": ["read", "replace", "insert", "delete"],
                        "default": "replace",
                    },
                    "cell_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Target cell ID; for insert, the new cell is placed after this cell.",
                    },
                    "cell_type": {"type": "string", "enum": ["code", "markdown"]},
                    "new_source": {
                        "type": "string",
                        "description": "New cell source for insert or replacement.",
                    },
                },
                "required": ["notebook_path"],
                "additionalProperties": False,
            },
        },
    }


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _resolve_notebook(
    workspace_root: str | Path, notebook_path: str
) -> tuple[Path, Path, tuple[str, ...]]:
    if not isinstance(notebook_path, str) or not notebook_path or "\x00" in notebook_path:
        raise ValueError("notebook_path must be a non-empty workspace-relative path.")

    windows_path = PureWindowsPath(notebook_path)
    normalized = notebook_path.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        Path(notebook_path).is_absolute()
        or relative.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part == ".." for part in (*relative.parts, *windows_path.parts))
    ):
        raise ValueError("notebook_path must stay inside the active workspace.")

    parts = tuple(part for part in relative.parts if part not in ("", "."))
    if not parts:
        raise ValueError("notebook_path must name an existing .ipynb file.")
    if Path(parts[-1]).suffix.lower() != ".ipynb":
        raise ValueError("NotebookEdit accepts .ipynb files only.")

    root = Path(workspace_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Workspace root is not a directory: {root}")

    target = _assert_notebook_path(root, parts)
    return root, target, parts


def _assert_notebook_path(
    root: Path, parts: tuple[str, ...], expected: Path | None = None
) -> Path:
    target = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if _is_link_or_junction(current):
            raise ValueError("Notebook paths may not contain symlinks or junctions.")
    resolved = target.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("notebook_path must stay inside the active workspace.")
    if not stat.S_ISREG(resolved.lstat().st_mode):
        raise ValueError("notebook_path must name a regular file.")
    if expected is not None and resolved != expected:
        raise RuntimeError("Notebook path changed while editing; read it again and retry.")
    return resolved


def _read_source(cell: dict[str, Any], index: int) -> str:
    source = cell.get("source", "")
    if isinstance(source, str):
        return source
    if isinstance(source, list) and all(isinstance(line, str) for line in source):
        return "".join(source)
    raise ValueError(f"Notebook cell at index {index} has an invalid source field.")


def _cell_summary(cell: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "cell_id": cell.get("id"),
        "cell_type": cell.get("cell_type"),
        "source": _read_source(cell, index),
    }


def _find_cell(cells: list[Any], cell_id: str) -> int:
    matches = [
        index
        for index, cell in enumerate(cells)
        if isinstance(cell, dict) and cell.get("id") == cell_id
    ]
    if not matches:
        raise ValueError(f"Notebook cell_id not found: {cell_id}")
    if len(matches) > 1:
        raise ValueError(f"Notebook contains duplicate cell_id values: {cell_id}")
    return matches[0]


def _source_lines(source: str) -> list[str]:
    return source.splitlines(keepends=True)


def _indent_unit(text: str) -> int | str:
    match = re.search(r"\r?\n([ \t]+)\S", text)
    return match.group(1) if match else 1


def _serialize_notebook(notebook: dict[str, Any], original_text: str) -> str:
    rendered = json.dumps(notebook, ensure_ascii=False, indent=_indent_unit(original_text))
    newline = "\r\n" if "\r\n" in original_text else "\n"
    if newline != "\n":
        rendered = rendered.replace("\n", newline)
    if original_text.endswith(("\n", "\r")):
        rendered += newline
    return rendered


def _same_file_version(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _atomic_replace(
    root: Path,
    path: Path,
    parts: tuple[str, ...],
    rendered: str,
    original_stat: os.stat_result,
) -> None:
    _assert_notebook_path(root, parts, expected=path)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as staged:
            temp_path = Path(staged.name)
            staged.write(rendered)
            staged.flush()
            os.fsync(staged.fileno())

        os.chmod(temp_path, stat.S_IMODE(original_stat.st_mode))
        _assert_notebook_path(root, parts, expected=path)
        current_stat = path.lstat()
        if not stat.S_ISREG(current_stat.st_mode) or not _same_file_version(
            original_stat, current_stat
        ):
            raise RuntimeError("Notebook changed while editing; read it again and retry.")
        if _is_link_or_junction(path):
            raise ValueError("Notebook paths may not contain symlinks or junctions.")
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def notebook_edit(
    workspace_root: str | Path,
    notebook_path: str,
    edit_mode: str = "replace",
    cell_id: str | None = None,
    cell_type: str | None = None,
    new_source: str | None = None,
) -> dict[str, Any]:
    """Read or edit notebook cells; edits are staged and atomically replaced."""
    if not isinstance(edit_mode, str) or edit_mode not in {
        "read",
        "replace",
        "insert",
        "delete",
    }:
        raise ValueError("edit_mode must be read, replace, insert, or delete.")
    if cell_id is not None and (not isinstance(cell_id, str) or not cell_id):
        raise ValueError("cell_id must be a non-empty string when supplied.")
    if cell_type is not None and (
        not isinstance(cell_type, str) or cell_type not in {"code", "markdown"}
    ):
        raise ValueError("cell_type must be code or markdown.")

    if edit_mode == "read":
        if cell_type is not None or new_source is not None:
            raise ValueError("read mode does not accept cell_type or new_source.")
    elif edit_mode == "insert":
        if cell_type is None or not isinstance(new_source, str):
            raise ValueError("insert mode requires cell_type and new_source.")
    elif edit_mode == "replace":
        if not cell_id or not isinstance(new_source, str):
            raise ValueError("replace mode requires cell_id and new_source.")
        if cell_type is not None:
            raise ValueError("cell_type is only valid in insert mode.")
    else:
        if not cell_id:
            raise ValueError("delete mode requires cell_id.")
        if cell_type is not None or new_source is not None:
            raise ValueError("delete mode does not accept cell_type or new_source.")

    root, path, parts = _resolve_notebook(workspace_root, notebook_path)
    original_stat = path.lstat()
    original_text = path.read_text(encoding="utf-8")
    try:
        notebook = json.loads(original_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Notebook is not valid JSON: {exc.msg} at line {exc.lineno}.") from exc
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        raise ValueError("Notebook JSON must contain a cells array.")
    if "nbformat" in notebook and notebook["nbformat"] != 4:
        raise ValueError("Only nbformat 4 notebooks are supported.")
    cells = notebook["cells"]
    if any(not isinstance(cell, dict) for cell in cells):
        raise ValueError("Notebook cells must be JSON objects.")

    relative_name = PurePosixPath(*parts).as_posix()
    if edit_mode == "read":
        if cell_id is None:
            result_cells = [_cell_summary(cell, index) for index, cell in enumerate(cells)]
        else:
            index = _find_cell(cells, cell_id)
            result_cells = [_cell_summary(cells[index], index)]
        return {
            "ok": True,
            "notebook_path": relative_name,
            "cell_count": len(cells),
            "cells": result_cells,
        }

    affected_index: int
    affected_id: str
    if edit_mode == "insert":
        if cell_id is None:
            affected_index = 0
        else:
            affected_index = _find_cell(cells, cell_id) + 1
        affected_id = uuid.uuid4().hex[:8]
        while any(cell.get("id") == affected_id for cell in cells):
            affected_id = uuid.uuid4().hex[:8]
        new_cell: dict[str, Any] = {
            "cell_type": cell_type,
            "id": affected_id,
            "metadata": {},
            "source": _source_lines(new_source),
        }
        if cell_type == "code":
            new_cell["execution_count"] = None
            new_cell["outputs"] = []
        cells.insert(affected_index, new_cell)
    else:
        affected_index = _find_cell(cells, cell_id)
        affected_id = cell_id
        if edit_mode == "replace":
            cell = cells[affected_index]
            _read_source(cell, affected_index)
            cell["source"] = _source_lines(new_source)
            if cell.get("cell_type") == "code":
                cell["execution_count"] = None
                cell["outputs"] = []
        else:
            del cells[affected_index]

    _atomic_replace(
        root,
        path,
        parts,
        _serialize_notebook(notebook, original_text),
        original_stat,
    )
    return {
        "ok": True,
        "notebook_path": relative_name,
        "edit_mode": edit_mode,
        "cell_id": affected_id,
        "cell_index": affected_index,
        "cell_count": len(cells),
    }
