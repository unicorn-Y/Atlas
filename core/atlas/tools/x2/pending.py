"""Process-global registry of pending human resolutions, keyed by run id.

THE single resolution channel between the frontend cards and blocked X2 tool
calls (``browser_handoff``, foreground confirmations, vault confirmations):

- A tool call blocks in :func:`wait_for_resolution` (the run-scoped
  ``X2Context.wait_input`` routes here) and registers one future under its run.
- The REST cards resolve it: ``POST /api/computer/foreground`` and
  ``POST /api/browser/handoff`` call :func:`resolve`, which wakes EVERY pending
  waiter of that run.
- Run cancel / shutdown calls :func:`cancel_run`, which resolves pending
  waiters with ``"give_up"`` so the tool call unwinds promptly.

Resolution delivery is thread-safe: futures may be resolved from the server
loop, a worker thread or the engine loop alike (delivery goes through
``loop.call_soon_threadsafe`` and ignores closed loops).

Timeout / cancel return contract: a timed-out wait returns ``""`` and a
cancelled one returns ``"give_up"``; ``X2Context.confirm_foreground`` already
treats anything outside ``{"deny", "give_up", ""}`` as allowed, so ``""`` reads
as deny there and ``request_handoff`` maps falsy choices to done.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

GIVE_UP = "give_up"

_waiters: dict[str, list["asyncio.Future[str]"]] = {}
_lock = threading.Lock()


async def wait_for_resolution(
    run_id: str,
    prompt: str,
    options: list[str] | None = None,
    cancel_event: Any = None,
    timeout_seconds: float = 600,
) -> str:
    """Block until the human resolves the card for ``run_id``.

    ``prompt`` / ``options`` are accepted for interface parity — the card event
    itself is emitted by the caller (``X2Context.request_handoff`` /
    ``confirm_foreground``).  ``cancel_event`` may be an ``asyncio.Event`` (the
    engine run's cancel event) or a ``threading.Event``.  Returns the resolution
    value, ``""`` on timeout or ``GIVE_UP`` when the run was cancelled.
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    with _lock:
        _waiters.setdefault(str(run_id), []).append(fut)
    try:
        waiter = asyncio.ensure_future(fut)
        async_cancel = isinstance(cancel_event, asyncio.Event)
        cancel_waiter = (
            asyncio.ensure_future(cancel_event.wait()) if async_cancel else None)
        try:
            if cancel_waiter is not None:
                done, _ = await asyncio.wait(
                    {waiter, cancel_waiter}, timeout=timeout_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            else:
                done = set()
                deadline = loop.time() + timeout_seconds
                while not done:
                    done, _ = await asyncio.wait({waiter}, timeout=0.1)
                    if not done and cancel_event is not None and cancel_event.is_set():
                        return GIVE_UP
                    if not done and loop.time() >= deadline:
                        break
            if waiter in done:
                return waiter.result()
            if cancel_event is not None and cancel_event.is_set():
                return GIVE_UP
            return ""  # timed out: caller decides (confirm_foreground reads deny)
        finally:
            for task in (waiter, cancel_waiter):
                if task is not None and not task.done():
                    task.cancel()
    finally:
        with _lock:
            bucket = _waiters.get(str(run_id))
            if bucket is not None:
                try:
                    bucket.remove(fut)
                except ValueError:
                    pass
                if not bucket:
                    _waiters.pop(str(run_id), None)


def resolve(run_id: str, value: str) -> bool:
    """Resolve EVERY pending waiter of ``run_id`` with ``value``.

    Returns ``True`` when at least one live waiter received the value (double
    resolve is safe: already-done futures are skipped).
    """
    with _lock:
        futs = list(_waiters.get(str(run_id or ""), []))
    delivered = False
    for fut in futs:
        if fut.done():
            continue
        delivered = True
        _deliver(fut, str(value))
    return delivered


def cancel_run(run_id: str) -> None:
    """Resolve pending waiters of ``run_id`` with ``"give_up"`` (run cancelled)."""
    resolve(run_id, GIVE_UP)


def pending_runs() -> list[str]:
    """Run ids that still have at least one live waiter (status surface)."""
    with _lock:
        return sorted(
            run_id for run_id, futs in _waiters.items()
            if any(not fut.done() for fut in futs)
        )


def _deliver(fut: "asyncio.Future[str]", value: str) -> None:
    """Set the future's result from any thread / loop; never raises."""
    try:
        fut.get_loop().call_soon_threadsafe(_set_if_pending, fut, value)
    except RuntimeError:
        pass  # loop already closed: nothing is waiting anymore


def _set_if_pending(fut: "asyncio.Future[str]", value: str) -> None:
    if not fut.done():
        fut.set_result(value)


__all__ = ["GIVE_UP", "cancel_run", "pending_runs", "resolve", "wait_for_resolution"]
