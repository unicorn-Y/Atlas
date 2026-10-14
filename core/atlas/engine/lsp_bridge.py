"""LSP write-path bridge: native file tools ↔ ``atlas.lsp`` facade (C6 contract §3).

Every function is silent and total — LSP being disabled, broken or unavailable never
raises into the write path; failures degrade to no report / no event.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("atlas.engine.lsp_bridge")

# 契约 §2.1：事件里最多 20 条，count 仍为真实数。
_MAX_EVENT_DIAGNOSTICS = 20
_EVENT_PUT_TIMEOUT = 5.0

_loop_for_events: Optional[asyncio.AbstractEventLoop] = None


def set_event_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """Module-level fallback loop for queue events when the caller doesn't pass one."""
    global _loop_for_events
    _loop_for_events = loop


def lsp_applicable(workspace: str) -> bool:
    """True unless ``workspace`` is an SSH remote (LSP servers only run locally)."""
    return not str(workspace or "").startswith("ssh://")


def snapshot_before_write(path: str) -> None:
    """Capture the pre-write diagnostics baseline.  Never raises."""
    try:
        import atlas.lsp as lsp_facade

        lsp_facade.snapshot_baseline(path)
    except Exception as e:  # noqa: BLE001
        logger.debug("LSP snapshot_before_write failed for %s: %s", path, e, exc_info=e)


def report_after_edit(
    runtime: Any, path: str, pre_content: Optional[str], post_content: Optional[str],
    *, loop: Optional[asyncio.AbstractEventLoop] = None,
) -> str:
    """Report only what this edit introduced; ``""`` when nothing new / LSP unavailable.

    The text block matches ``atlas.lsp.edit_report`` byte for byte; when new diagnostics
    exist it also emits the ``lsp.diagnostics`` queue event (contract §2.1).  Both come
    from ONE delta query because the query rolls the baseline forward — a second query
    would always return empty.  Any exception is swallowed and yields ``""``.
    """
    try:
        import atlas.lsp as lsp_facade

        svc = lsp_facade.get_service()
        if svc is None:
            return ""
        line_shift = None
        if pre_content is not None and post_content is not None:
            from atlas.lsp.range_shift import build_line_shift

            line_shift = build_line_shift(pre_content, post_content)
        diags = svc.get_diagnostics_sync(path, delta=True, line_shift=line_shift)
        if not diags:
            return ""
        from atlas.lsp.reporter import report_for_file, truncate

        block = truncate("本次编辑引入的诊断:\n" + report_for_file(path, diags))
        _emit_event(runtime, path, diags, loop=loop)
        return block
    except Exception as e:  # noqa: BLE001
        logger.debug("LSP report_after_edit failed for %s: %s", path, e, exc_info=e)
        return ""


def _emit_event(runtime: Any, path: str, diags: list, *, loop=None) -> None:
    """Push the §2.1 ``lsp.diagnostics`` queue event; count==0 never reaches here."""
    queue = getattr(runtime, "event_queue", None)
    target_loop = loop if loop is not None else _loop_for_events
    if queue is None or target_loop is None:
        return
    workspace = str(getattr(runtime, "workspace", "") or "")
    from atlas.lsp.types import from_lsp

    data = {
        "path": _relative_path(path, workspace),
        "workspace": os.path.abspath(workspace) if workspace else workspace,
        "count": len(diags),
        "diagnostics": [
            {
                "line": d.line, "column": d.column, "severity": d.severity,
                "code": d.code, "message": d.message,
            }
            for d in (from_lsp(raw, path) for raw in diags[:_MAX_EVENT_DIAGNOSTICS])
        ],
    }
    coro = queue.put({"type": "lsp.diagnostics", "data": data})
    try:
        fut = asyncio.run_coroutine_threadsafe(coro, target_loop)
    except Exception:
        coro.close()  # loop 无效:协程从未被调度,收掉避免 never-awaited 告警
        raise
    try:
        fut.result(timeout=_EVENT_PUT_TIMEOUT)
    except BaseException:
        fut.cancel()
        raise


def _relative_path(path: str, workspace: str) -> str:
    """Workspace-relative slash path when computable, else the absolute path."""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(workspace)) if workspace else None
    except ValueError:  # different drives on Windows
        rel = None
    if not rel or rel == "." or rel.startswith(".."):
        return str(path)
    return rel.replace(os.sep, "/")


__all__ = ["lsp_applicable", "snapshot_before_write", "report_after_edit", "set_event_loop"]
