"""Compatibility shims for the pinned DBOS dependency.

Why this exists
---------------
DBOS runs one background thread per cron schedule. That thread sleeps until the
next occurrence with::

    if self._stop_event.wait(timeout=sleep_time + jitter):  # dbos/_scheduler.py
        return

``sleep_time`` is the raw distance to the next fire time. CPython rejects any
``threading`` wait longer than ``threading.TIMEOUT_MAX`` (~4_294_967 s ≈ 49.7
days) with ``OverflowError: timeout value is too large`` — and DBOS does not
bound it, so a legitimately infrequent cron (e.g. ``0 0 1 1 *``, Atlas's
"yearly" automation) kills its scheduler thread and the schedule never fires.
This is present in dbos 3.0.0 and still in 3.2.0 (verified against both), so
pinning a newer release does not help.

The fix
-------
Service the *same* timeout in bounded chunks (default 6h) while preserving
``Event.wait``'s exact contract — it returns ``True`` only if the event was set
within ``timeout``, else ``False`` after the full duration elapses. The DBOS
loop therefore still wakes exactly once per real occurrence, so the cron
iterator is not advanced early (a naive clamp would fire schedules prematurely).

The shim patches ``_ScheduleThread._loop`` so each schedule wraps its own
``_stop_event.wait`` at thread start. It keeps the same event object, so the
external ``.set()`` used to stop a schedule still works.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import structlog

log = structlog.get_logger(__name__)

# Chunk size for a single OS wait. Well under threading.TIMEOUT_MAX on every
# platform and cheap (a no-op wake-up a few times a day per schedule).
_DEFAULT_CHUNK_SECONDS = min(6 * 3600.0, threading.TIMEOUT_MAX / 2)

_APPLY_LOCK = threading.Lock()
_APPLIED = False


def chunked_wait(
    orig_wait: Callable[[float | None], bool],
    timeout: float | None,
    chunk: float,
) -> bool:
    """Replicate ``Event.wait(timeout)`` while bounding each underlying wait.

    Returns ``True`` when ``orig_wait`` reports the event was set before the
    full ``timeout`` elapsed, ``False`` otherwise — the same contract as
    ``threading.Event.wait``.
    """
    if timeout is None or timeout <= chunk:
        return orig_wait(timeout)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if orig_wait(min(remaining, chunk)):
            return True


def wrap_event_wait(event: threading.Event, chunk: float) -> None:
    """Bound ``event.wait``'s OS wait in place. Idempotent per instance."""
    if getattr(event, "_atlas_chunked_wait", False):
        return
    original_wait = event.wait

    def _wait(timeout: float | None = None) -> bool:
        return chunked_wait(original_wait, timeout, chunk)

    event.wait = _wait  # type: ignore[method-assign] - plain object, has __dict__
    event._atlas_chunked_wait = True  # type: ignore[attr-defined]


def apply_scheduler_wait_shim(chunk_seconds: float | None = None) -> bool:
    """Bound DBOS's per-schedule wait; safe to call repeatedly.

    Returns ``True`` when the shim is in place (already applied or just applied),
    ``False`` when the DBOS internals it targets are unavailable.
    """
    global _APPLIED
    with _APPLY_LOCK:
        if _APPLIED:
            return True
        try:
            from dbos._scheduler import _ScheduleThread  # noqa: PLC0415
        except (ImportError, AttributeError):  # dbos absent or internals moved
            log.warning("dbos.scheduler_wait_shim_unavailable")
            return False
        chunk = float(chunk_seconds if chunk_seconds is not None else _DEFAULT_CHUNK_SECONDS)
        original_loop = _ScheduleThread._loop

        def _loop(self: Any) -> None:
            event = getattr(self, "_stop_event", None)
            if event is not None:
                wrap_event_wait(event, chunk)
            original_loop(self)

        _loop._atlas_wait_shim = True  # type: ignore[attr-defined]
        _ScheduleThread._loop = _loop
        _APPLIED = True
        log.info("dbos.scheduler_wait_shim_applied", chunk_seconds=chunk)
        return True
