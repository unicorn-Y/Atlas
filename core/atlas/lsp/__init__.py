"""Language Server Protocol (LSP) integration for Atlas.

# Ported from NousResearch/hermes-agent agent/lsp/__init__.py @ 562ad75baec0c8360f6ce2d48b7d9de56506956c (MIT)

Real language servers (pyright, gopls, ...) run as subprocesses and their
``publishDiagnostics`` feed the post-edit lint delta of the Atlas edit tools.  LSP is **gated
on git workspace detection** so plain home directories never spawn daemons; ``get_service()``
returns the singleton or ``None`` when disabled.

Differences from the Hermes original: a single process-wide service (no multi-profile
``HERMES_HOME`` routing), and the C6 wiring facade — :func:`snapshot_baseline`,
:func:`diagnostics_for`, :func:`missing_hint`, :func:`edit_report` — every function of which
is silent and total: LSP being disabled, broken or absent never raises, it returns empty values.
"""
from __future__ import annotations

import atexit
import logging
import threading
from typing import Optional

from atlas.lsp.manager import LSPService
from atlas.lsp.types import Diagnostic

logger = logging.getLogger("atlas.lsp")

_service: Optional[LSPService] = None
_atexit_registered = False
_service_lock = threading.Lock()


def _active(svc: Optional[LSPService]) -> Optional[LSPService]:
    return svc if (svc is not None and svc.is_active()) else None


def _register_atexit_once() -> None:
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(_atexit_shutdown)
        _atexit_registered = True


def get_service() -> Optional[LSPService]:
    """Return the process-wide LSP service singleton, or ``None`` when disabled.

    Also registers an :mod:`atexit` hook so a clean exit tears down spawned servers:
    without it every CLI exit leaks pyright processes for a few seconds while their
    stdout buffers drain.  (SIGKILL/os._exit skip atexit — fine, the kernel reaps the
    stateless servers with their parent.)
    """
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = LSPService.create_from_config()
                _register_atexit_once()
    return _active(_service)


def release_workspace(path: str) -> int:
    """Shut down the LSP clients serving ``path`` (a worktree about to be removed), without shutting
    down unrelated workspaces.  Never creates a service.  Returns the count."""
    with _service_lock:
        svc = _service
    if svc is None:
        return 0
    try:
        return svc.release_workspace(path)
    except Exception as e:  # noqa: BLE001
        logger.debug("LSP workspace release failed for %s: %s", path, e)
        return 0


def shutdown_service() -> None:
    """Tear down the LSP service if one was started.  Idempotent."""
    global _service
    with _service_lock:
        svc, _service = _service, None
    if svc is not None:
        try:
            svc.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.debug("LSP shutdown error: %s", e)


def _atexit_shutdown() -> None:
    """atexit wrapper; logs at debug since the user has already seen the final output."""
    try:
        shutdown_service()
    except Exception as e:  # noqa: BLE001
        logger.debug("atexit LSP shutdown failed: %s", e)


# ---- C6 wiring facade — never raises; empty values when LSP is off/unavailable ----


def snapshot_baseline(path: str) -> None:
    """Snapshot the current diagnostics of ``path`` as the delta baseline.  Call BEFORE a write.
    Silent no-op when LSP is disabled or unavailable."""
    svc = get_service()
    if svc is None:
        return
    try:
        svc.snapshot_baseline(path)
    except Exception as e:  # noqa: BLE001
        logger.debug("LSP baseline snapshot failed for %s: %s", path, e)


def diagnostics_for(path: str, *, delta: bool = False) -> list[Diagnostic]:
    """Diagnostics for ``path`` converted to Atlas :class:`atlas.lsp.types.Diagnostic`;
    ``[]`` when LSP is disabled/unavailable or the file is clean."""
    svc = get_service()
    if svc is None:
        return []
    try:
        raw = svc.get_diagnostics_sync(path, delta=delta)
    except Exception as e:  # noqa: BLE001
        logger.debug("LSP diagnostics failed for %s: %s", path, e)
        return []
    from atlas.lsp.types import from_lsp
    return [from_lsp(d, path) for d in (raw or [])]


def missing_hint(path: str) -> str:
    """Short Chinese install hint when the language server for ``path`` is not installed;
    ``""`` = available (or LSP off / nothing probed)."""
    svc = get_service()
    if svc is None:
        return ""
    try:
        return svc.describe_missing(path) or ""
    except Exception as e:  # noqa: BLE001
        logger.debug("LSP missing hint failed for %s: %s", path, e)
        return ""


def edit_report(path: str, pre_content: Optional[str] = None, post_content: Optional[str] = None) -> str:
    """The single C6 wiring entry point: report only what an edit introduced.

    With both ``pre_content`` and ``post_content`` a line shift is built so pre-existing
    diagnostics that merely moved don't count as introduced; the delta filter runs against the
    :func:`snapshot_baseline` taken before the write.  Returns ``""`` when nothing new appeared
    or LSP is unavailable — this function never raises.
    """
    svc = get_service()
    if svc is None:
        return ""
    try:
        line_shift = None
        if pre_content is not None and post_content is not None:
            from atlas.lsp.range_shift import build_line_shift
            line_shift = build_line_shift(pre_content, post_content)
        diags = svc.get_diagnostics_sync(path, delta=True, line_shift=line_shift)
        if not diags:
            return ""
        from atlas.lsp.reporter import report_for_file, truncate
        return truncate("本次编辑引入的诊断:\n" + report_for_file(path, diags))
    except Exception as e:  # noqa: BLE001
        logger.debug("LSP edit report failed for %s: %s", path, e)
        return ""


__all__ = [
    "Diagnostic", "LSPService", "get_service", "shutdown_service", "release_workspace",
    "snapshot_baseline", "diagnostics_for", "missing_hint", "edit_report",
]
