"""Regression tests for the DBOS scheduler wait shim (dbos_compat).

Background: DBOS sleeps a schedule thread with ``Event.wait(next_run_delay)``
without bounding the delay, so a far-future cron (``0 0 1 1 *``) exceeds
``threading.TIMEOUT_MAX`` and raises ``OverflowError: timeout value is too
large``, killing the thread. The shim services the same timeout in bounded
chunks while preserving ``Event.wait`` semantics.
"""

from __future__ import annotations

import threading
import time

from atlas.capabilities.durable import dbos_compat as compat


def test_chunked_wait_bounds_each_underlying_wait(monkeypatch) -> None:
    """No underlying wait exceeds `chunk`, and the full timeout still elapses."""
    recorded: list[float] = []
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        return clock["t"]

    def fake_wait(timeout: float | None) -> bool:
        recorded.append(timeout)  # type: ignore[arg-type]
        clock["t"] += timeout or 0.0
        return False

    monkeypatch.setattr(compat.time, "monotonic", fake_monotonic)

    assert compat.chunked_wait(fake_wait, timeout=100.0, chunk=30.0) is False
    assert recorded, "underlying wait must be called"
    assert all(value <= 30.0 + 1e-9 for value in recorded), recorded
    assert sum(recorded) >= 100.0 - 1e-9, recorded


def test_chunked_wait_returns_true_as_soon_as_event_is_set() -> None:
    """A set event short-circuits on the first chunk (no long block)."""
    recorded: list[float] = []

    def wait_true(timeout: float | None) -> bool:
        recorded.append(timeout)  # type: ignore[arg-type]
        return True

    assert compat.chunked_wait(wait_true, timeout=10**9, chunk=86400.0) is True
    assert recorded == [86400.0]


def test_chunked_wait_passthrough_for_small_or_none_timeout() -> None:
    recorded: list[float | None] = []

    def record(timeout: float | None) -> bool:
        recorded.append(timeout)
        return False

    assert compat.chunked_wait(record, timeout=5.0, chunk=10.0) is False
    assert compat.chunked_wait(record, timeout=None, chunk=10.0) is False
    assert recorded == [5.0, None]


def test_wrap_event_wait_is_idempotent_and_keeps_set_working() -> None:
    event = threading.Event()
    compat.wrap_event_wait(event, chunk=0.02)
    wrapped = event.wait
    compat.wrap_event_wait(event, chunk=0.02)  # second call must not re-wrap
    assert event.wait is wrapped

    event.set()
    # Would raise OverflowError on the raw Event.wait; the shim returns promptly.
    assert event.wait(timeout=10**9) is True


def test_wrap_event_wait_clamps_the_underlying_timeout(monkeypatch) -> None:
    event = threading.Event()
    recorded: list[float] = []
    clock = {"t": 0.0}

    def fake_os_wait(timeout: float | None) -> bool:
        recorded.append(timeout)  # type: ignore[arg-type]
        clock["t"] += timeout or 0.0
        return False

    event.wait = fake_os_wait  # type: ignore[method-assign]
    monkeypatch.setattr(compat.time, "monotonic", lambda: clock["t"])

    compat.wrap_event_wait(event, chunk=30.0)
    assert event.wait(timeout=100.0) is False
    assert all(value <= 30.0 + 1e-9 for value in recorded), recorded
    assert sum(recorded) >= 100.0 - 1e-9


def test_apply_scheduler_wait_shim_patches_dbos_loop_idempotently() -> None:
    from dbos._scheduler import _ScheduleThread

    original_loop = _ScheduleThread._loop
    original_applied = compat._APPLIED
    try:
        compat._APPLIED = False
        assert compat.apply_scheduler_wait_shim() is True
        patched = _ScheduleThread._loop
        assert getattr(patched, "_atlas_wait_shim", False) is True
        # Idempotent: a second call keeps the same loop object.
        assert compat.apply_scheduler_wait_shim() is True
        assert _ScheduleThread._loop is patched
    finally:
        _ScheduleThread._loop = original_loop
        compat._APPLIED = original_applied


def test_shim_prevents_overflow_for_a_yearly_cron_delay() -> None:
    """The exact failing shape: waiting out ~a year must not raise."""
    event = threading.Event()
    compat.wrap_event_wait(event, chunk=0.01)
    # dbos would call wait(timeout=~31_000_000) for a `0 0 1 1 *` schedule.
    stop = threading.Thread(target=lambda: (time.sleep(0.05), event.set()))
    stop.start()
    start = time.monotonic()
    result = event.wait(timeout=31_000_000.0)
    elapsed = time.monotonic() - start
    stop.join()
    assert result is True  # stop signal delivered
    assert elapsed < 5.0, f"chunked wait did not return promptly (waited {elapsed:.1f}s)"
