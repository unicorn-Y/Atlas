"""Retention for spilled tool output.

Oversized tool results are written to a content-addressed file and the model gets
a path instead of the text (``ContextManager.clip_tool_result`` →
``_output_ref``). Command output does the same through
``_BoundedOutputCollector``. Both are written and then never looked at again:
nothing enumerates, reports, or deletes them.

The result on one ordinary install was 2476 files and 195 MB, including a single
191 MB file from one runaway command. None of it was reachable from the UI, and
no command would remove it. That is the gap this module closes — it does not
change where output is written, because the write path is deliberately
symlink-safe and load-bearing.

Two rules shape the policy:

* **Age comes first.** A file may still be the ``output_ref`` of a message in a
  live session, and rewriting history to drop the reference is not this module's
  job. So nothing younger than ``min_age_hours`` is ever touched, and expiry is
  by age before size.
* **Never raise.** This runs during maintenance on a machine that is otherwise
  busy; a locked file is skipped and reported, not fatal. Same contract as
  ``log_rotation``.
"""

from __future__ import annotations

import time
import hashlib
from pathlib import Path
from typing import Any, Iterable

import structlog

log = structlog.get_logger(__name__)


def save_text(text: str, *, directory: Path) -> dict[str, Any] | None:
    """Persist UTF-8 text before replacement; None requires the caller to retain it.

    A locator is an absolute local file URI. The hint remains a native path for
    tools that accept filesystem paths. Failed writes never return a locator.
    """
    from atlas.engine.tools.spill_safety import ensure_spill_dir, write_text_exclusive

    payload = text.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    path = Path(directory) / (digest + ".txt")
    try:
        ensure_spill_dir(path.parent)
        try:
            write_text_exclusive(path, text)
        except FileExistsError:
            pass
        # Existing files must be verified too: a dangling/stale locator loses evidence.
        if path.is_symlink() or path.read_bytes() != payload:
            return None
        return {"locator": path.resolve().as_uri(), "bytes": len(payload), "hint": str(path.resolve())}
    except (OSError, UnicodeError):
        return None

#: Subdirectory names the kernel writes spilled text into.
SPILL_DIR_NAMES = ("tool-output", "compact-output")

DEFAULT_KEEP_DAYS = 14
DEFAULT_KEEP_TOTAL = 512 * 1024 * 1024
#: A file this young may still be referenced by an in-flight run.
DEFAULT_MIN_AGE_HOURS = 24


def _logs_root() -> Path:
    from atlas.logs import LOG_DIR

    return Path(LOG_DIR)


def spill_dirs(root: Path | None = None) -> list[Path]:
    """Every existing spill directory under ``<logs>/runs/*/``."""
    base = Path(root) if root is not None else _logs_root()
    runs = base / "runs"
    if not runs.is_dir():
        return []
    found: list[Path] = []
    for name in SPILL_DIR_NAMES:
        found.extend(sorted(path for path in runs.glob(f"*/{name}") if path.is_dir()))
    return found


def _entry(path: Path) -> tuple[float, int, Path] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime, st.st_size, path)


def inventory(root: Path | None = None) -> dict[str, Any]:
    """What is on disk right now, per directory and in total."""
    directories = spill_dirs(root)
    rows: list[dict[str, Any]] = []
    total_files = 0
    total_bytes = 0
    largest: tuple[int, str] | None = None
    for directory in directories:
        files = 0
        size = 0
        for item in directory.iterdir():
            entry = _entry(item) if item.is_file() else None
            if entry is None:
                continue
            files += 1
            size += entry[1]
            if largest is None or entry[1] > largest[0]:
                largest = (entry[1], str(item))
        total_files += files
        total_bytes += size
        rows.append(
            {
                "path": str(directory),
                "files": files,
                "bytes": size,
            }
        )
    return {
        "directories": rows,
        "directory_count": len(rows),
        "files": total_files,
        "bytes": total_bytes,
        "largest_bytes": largest[0] if largest else 0,
        "largest_path": largest[1] if largest else None,
    }


def _candidates(directories: Iterable[Path]) -> list[tuple[float, int, Path]]:
    out: list[tuple[float, int, Path]] = []
    for directory in directories:
        try:
            items = list(directory.iterdir())
        except OSError:
            continue
        for item in items:
            try:
                if not item.is_file():
                    continue
            except OSError:
                continue
            entry = _entry(item)
            if entry is not None:
                out.append(entry)
    out.sort()
    return out


def prune(
    root: Path | None = None,
    *,
    keep_days: int = DEFAULT_KEEP_DAYS,
    keep_total_bytes: int = DEFAULT_KEEP_TOTAL,
    min_age_hours: int = DEFAULT_MIN_AGE_HOURS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete spilled output by age, then oldest-first until under the size cap.

    ``dry_run`` returns the same shape with ``removed`` populated and nothing
    deleted, so a caller can show the user what a run would cost before it runs.
    """
    directories = spill_dirs(root)
    now = time.time()
    age_cutoff = now - max(0, int(keep_days)) * 86400
    # The younger of the two floors wins: a generous ``keep_days`` must not
    # undermine the in-flight protection, and a long ``min_age_hours`` must not
    # keep files the age policy already expired.
    protected = now - max(0, int(min_age_hours)) * 3600

    removed: list[str] = []
    freed = 0
    skipped = 0
    kept_bytes = 0
    survivors: list[tuple[float, int, Path]] = []

    for mtime, size, path in _candidates(directories):
        if mtime >= protected:
            skipped += 1
            survivors.append((mtime, size, path))
            continue
        if mtime < age_cutoff:
            if dry_run:
                removed.append(str(path))
                freed += size
                continue
            try:
                path.unlink()
                removed.append(str(path))
                freed += size
            except OSError:
                skipped += 1
                survivors.append((mtime, size, path))
            continue
        survivors.append((mtime, size, path))

    total = sum(size for _, size, _ in survivors)
    for mtime, size, path in sorted(survivors):
        if total <= keep_total_bytes:
            break
        if mtime >= protected:
            # Never trade an in-flight run's evidence for a size target.
            continue
        if dry_run:
            removed.append(str(path))
            freed += size
            total -= size
            continue
        try:
            path.unlink()
            removed.append(str(path))
            freed += size
            total -= size
        except OSError:
            skipped += 1
    kept_bytes = total

    return {
        "directories": [str(d) for d in directories],
        "removed": removed,
        "removed_count": len(removed),
        "freed_bytes": freed,
        "kept_bytes": kept_bytes,
        "skipped": skipped,
        "dry_run": dry_run,
        "keep_days": keep_days,
        "keep_total_bytes": keep_total_bytes,
        "min_age_hours": min_age_hours,
    }


def describe(root: Path | None = None) -> str:
    """One sentence for the UI."""
    state = inventory(root)
    if not state["files"]:
        return "没有溢出的工具输出需要清理。"
    mb = state["bytes"] / 1024 / 1024
    largest = state["largest_bytes"] / 1024 / 1024
    return (
        f"溢出的工具输出共 {state['files']} 个文件、{mb:.1f} MB，"
        f"分布在 {state['directory_count']} 个目录，最大单个 {largest:.1f} MB。"
    )


__all__ = [
    "DEFAULT_KEEP_DAYS",
    "DEFAULT_KEEP_TOTAL",
    "DEFAULT_MIN_AGE_HOURS",
    "SPILL_DIR_NAMES",
    "describe",
    "inventory",
    "prune",
    "spill_dirs",
]
