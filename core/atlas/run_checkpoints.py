"""Durable per-run execution checkpoints: the write side of run replay.

The run archive (``atlas/logs.py`` :func:`append_run_event`) is a *narrative*
record: it says what happened, but it is written best-effort, line by line, and
it deliberately stores no tool arguments or output text. This module is the
complementary *position* record: at every safe boundary the kernel stamps one
row saying "run ``X`` has durably reached phase ``P`` / finished tool call
``C``". A process that dies mid-flight can then answer two questions the
archive alone cannot:

* where exactly did the run stop, and
* which of the steps at that point may be re-executed and which must not.

Safe boundaries (the kernel writes a row at exactly these points):

* every accepted :class:`atlas.engine.kernel.state.RunPhase` transition, and
* every tool call whose result has been written into the session history.

Nothing is written twice for the same boundary, and no checkpoint is ever used
to *re-run* a tool. A checkpoint only records that a side effect already
happened, so resume must skip it. Re-execution of a tool whose outcome was lost
is decided by :func:`classify_tool`: only tools the kernel already declares
read-only are safe to repeat, and everything else is reported to the caller as
"unknown side effects" instead of being replayed silently.

This module is intentionally separable from the read-only replay toolkit in
:mod:`atlas.run_replay`: that package never writes, this one is the only writer.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

log = logging.getLogger(__name__)

__all__ = [
    "CLASSIFIED_UNSAFE",
    "CheckpointWriteError",
    "checkpoint_overview",
    "classify_tool",
    "latest_checkpoint",
    "list_checkpoints",
    "summarize_checkpoints",
    "require_checkpoint",
    "write_checkpoint",
]

#: Verdict for a tool call whose outcome was lost and which must not be re-run.
CLASSIFIED_UNSAFE = "unsafe"

#: Truncation limits, mirroring ``atlas/diagnostic_store.py``: the store is a
#: local index, not a document store, so no single field may grow unbounded.
_MAX_RUN_ID = 128
_MAX_KIND = 24
_MAX_PHASE = 48
_MAX_TOOL_NAME = 120
_MAX_STATE = 32
_MAX_DETAIL = 4000


class CheckpointWriteError(RuntimeError):
    """A required recovery boundary could not be durably recorded."""


def _path() -> Path:
    return DATA_ROOT / "data" / "run_checkpoints.db"


def _connect() -> sqlite3.Connection:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS run_checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        kind TEXT NOT NULL,
        phase TEXT,
        tool_call_id TEXT,
        tool_name TEXT,
        state TEXT,
        replay_safe INTEGER,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run ON run_checkpoints(run_id, id)")
    db.commit()
    return db


# -- classification --------------------------------------------------------


def _read_only_tools() -> frozenset[str]:
    """The kernel's own read-only table, imported lazily to avoid a cycle.

    ``atlas.engine.kernel.tools`` imports the tool-permission layer, so it must not be
    pulled in at module import time by a store that the kernel itself imports.
    """
    try:
        from atlas.engine.kernel.tools import READ_ONLY_TOOLS  # noqa: PLC0415

        return READ_ONLY_TOOLS
    except Exception:  # pragma: no cover - defensive: never break a checkpoint
        log.exception("run_checkpoints.read_only_tools_unavailable")
        return frozenset()


def _edit_tool_names() -> frozenset[str]:
    try:
        from atlas.engine.kernel.tools import EDIT_TOOL_NAMES  # noqa: PLC0415

        return EDIT_TOOL_NAMES
    except Exception:  # pragma: no cover
        return frozenset()


def classify_tool(name: str | None) -> bool:
    """True only when ``name`` is provably free of user-visible side effects.

    Safe to *repeat*: the tool only reads (``READ_ONLY_TOOLS``). Everything else
    -- shell/terminal/process control, file edits, MCP and plugin tools, unknown
    names -- is treated as unsafe, because repeating it could change state that
    the previous, lost attempt may already have changed.

    Both spellings of a tool are consulted, because the live pool is not the
    kernel's own schema list: MCP servers namespace their tools as
    ``<server>__<tool>``, so the real read primitive is ``filesystem__read_file``
    and never the bare ``read_file``. That suffix rule is the same one
    ``kernel.loop._ALWAYS_KEEP_TOOLS`` and ``tool_pruning`` already use, and it is
    applied here to the *read* and to the *edit* table alike -- checking only the
    bare read name would let ``filesystem__edit_file`` through on the strength of
    ``edit_file`` sharing no prefix with the kernel's edit names.
    """
    tool = str(name or "").strip()
    if not tool:
        return False
    spellings = {tool}
    if "__" in tool:
        spellings.add(tool.rsplit("__", 1)[-1])
    if spellings & _edit_tool_names():
        return False
    return bool(spellings & _read_only_tools())


# -- writes ----------------------------------------------------------------


def write_checkpoint(
    run_id: str,
    *,
    kind: str,
    phase: str | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    state: str | None = None,
    replay_safe: bool | None = None,
    sequence: int = 0,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Append one checkpoint row. Returns True when it was persisted.

    Never raises: a run must not fail because its position record could not be
    written. The caller keeps running either way; the return value only exists
    so a caller *can* log a degradation.
    """
    key = str(run_id or "").strip()[:_MAX_RUN_ID]
    if not key:
        return False
    try:
        detail = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))[:_MAX_DETAIL]
    except (TypeError, ValueError):
        detail = "{}"
    try:
        with closing(_connect()) as db, db:
            db.execute(
                """INSERT INTO run_checkpoints
                    (run_id,sequence,kind,phase,tool_call_id,tool_name,state,replay_safe,payload,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    max(0, int(sequence or 0)),
                    str(kind or "").strip()[:_MAX_KIND] or "note",
                    (str(phase).strip()[:_MAX_PHASE] if phase else None),
                    (str(tool_call_id).strip()[:_MAX_RUN_ID] if tool_call_id else None),
                    (str(tool_name).strip()[:_MAX_TOOL_NAME] if tool_name else None),
                    (str(state).strip()[:_MAX_STATE] if state else None),
                    (None if replay_safe is None else int(bool(replay_safe))),
                    detail,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except sqlite3.Error:
        log.exception("run_checkpoints.write_failed", extra={"run_id": key, "kind": kind})
        return False
    return True


def require_checkpoint(
    run_id: str,
    *,
    kind: str,
    phase: str | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    state: str | None = None,
    replay_safe: bool | None = None,
    sequence: int = 0,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Persist a checkpoint or raise so callers can stop before unsafe progress.

    ``write_checkpoint`` remains best-effort for diagnostic and observational
    call sites. Recovery barriers must use this strict variant and let the
    exception abort dispatch or the enclosing phase transition.
    """
    if not str(run_id or "").strip():
        raise CheckpointWriteError("required durable checkpoint needs a non-empty run_id")
    try:
        persisted = write_checkpoint(
            run_id,
            kind=kind,
            phase=phase,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            state=state,
            replay_safe=replay_safe,
            sequence=sequence,
            payload=payload,
        )
    except Exception as exc:
        raise CheckpointWriteError(
            f"required durable checkpoint failed for run {str(run_id)[:_MAX_RUN_ID]!r}"
        ) from exc
    if not persisted:
        raise CheckpointWriteError(
            f"required durable checkpoint was not persisted for run {str(run_id)[:_MAX_RUN_ID]!r}"
        )
    return True


# -- reads -----------------------------------------------------------------


def _row(row: sqlite3.Row) -> dict[str, Any]:
    item = {**dict(row), "replay_safe": (None if row["replay_safe"] is None else bool(row["replay_safe"]))}
    try:
        item["payload"] = json.loads(row["payload"])
    except (TypeError, ValueError):
        item["payload"] = {}
    return item


def list_checkpoints(run_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Checkpoints for one run in insertion (== chronological) order."""
    key = str(run_id or "").strip()
    if not key:
        return []
    try:
        with closing(_connect()) as db, db:
            rows = db.execute(
                "SELECT * FROM run_checkpoints WHERE run_id=? ORDER BY id ASC LIMIT ?",
                (key, max(1, min(2000, int(limit)))),
            ).fetchall()
    except sqlite3.Error:
        log.exception("run_checkpoints.list_failed", extra={"run_id": key})
        return []
    return [_row(row) for row in rows]


def latest_checkpoint(run_id: str) -> dict[str, Any] | None:
    """The most recent durable boundary for ``run_id``, or ``None``."""
    key = str(run_id or "").strip()
    if not key:
        return None
    try:
        with closing(_connect()) as db, db:
            row = db.execute(
                "SELECT * FROM run_checkpoints WHERE run_id=? ORDER BY id DESC LIMIT 1", (key,)
            ).fetchone()
    except sqlite3.Error:
        log.exception("run_checkpoints.latest_failed", extra={"run_id": key})
        return None
    return _row(row) if row is not None else None


def checkpoint_overview(limit: int = 50) -> list[dict[str, Any]]:
    """Runs holding durable boundaries, newest activity first.

    This is the inventory side of resume: it answers "which runs did the
    process actually make progress on", which the in-memory runtime map loses
    across a restart. One row per run, with counts only -- no tool payloads.
    """
    try:
        with closing(_connect()) as db, db:
            rows = db.execute(
                """SELECT run_id,
                          COUNT(*) AS checkpoint_count,
                          SUM(CASE WHEN kind='tool' THEN 1 ELSE 0 END) AS tool_count,
                          SUM(CASE WHEN kind='phase' THEN 1 ELSE 0 END) AS phase_count,
                          SUM(CASE WHEN kind='tool' AND replay_safe=0 THEN 1 ELSE 0 END) AS unsafe_tool_count,
                          MAX(created_at) AS updated_at
                   FROM run_checkpoints
                   GROUP BY run_id
                   ORDER BY MAX(id) DESC
                   LIMIT ?""",
                (max(1, min(500, int(limit))),),
            ).fetchall()
    except sqlite3.Error:
        log.exception("run_checkpoints.overview_failed")
        return []
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["checkpoint_count"] = int(item["checkpoint_count"] or 0)
        item["tool_count"] = int(item["tool_count"] or 0)
        item["phase_count"] = int(item["phase_count"] or 0)
        item["unsafe_tool_count"] = int(item["unsafe_tool_count"] or 0)
        items.append(item)
    return items


def summarize_checkpoints(run_id: str, limit: int = 2000) -> dict[str, Any]:
    """Resume-oriented digest of a run's durable boundaries.

    ``phase`` order is preserved as written, ``completed_tools`` lists only tool
    calls that are known to have finished, and ``unsafe_tools`` names the ones
    whose re-execution would be unsafe. This is what a resume answer is built
    from; it never claims more than the store actually recorded.
    """
    items = list_checkpoints(run_id, limit=limit)
    phases: list[str] = []
    completed_tools: list[dict[str, Any]] = []
    safe_count = 0
    unsafe_names: list[str] = []
    for item in items:
        if item["kind"] == "phase" and item.get("phase") and item["phase"] not in phases:
            phases.append(item["phase"])
        if item["kind"] != "tool":
            continue
        completed_tools.append(
            {
                "tool_call_id": item.get("tool_call_id"),
                "name": item.get("tool_name"),
                "state": item.get("state"),
                "replay_safe": item.get("replay_safe"),
            }
        )
        if item.get("replay_safe"):
            safe_count += 1
        elif item.get("tool_name"):
            unsafe_names.append(str(item["tool_name"]))
    return {
        "run_id": str(run_id or ""),
        "checkpoint_count": len(items),
        "phase_count": sum(1 for item in items if item["kind"] == "phase"),
        "tool_count": len(completed_tools),
        "phases": phases,
        "phase": phases[-1] if phases else None,
        "completed_tools": completed_tools,
        "replay_safe_tool_count": safe_count,
        "unsafe_tool_count": len(completed_tools) - safe_count,
        "unsafe_tools": sorted(set(unsafe_names)),
        "last": items[-1] if items else None,
    }
