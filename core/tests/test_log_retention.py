"""Log and spill retention: the sweep, and the caller that did not exist.

``archive_run_log`` and ``maintain_run_logs`` worked and were tested, but nothing
in the running server ever called them — the only caller was ``atlas logs
maintain``. For the default user, who never opens a terminal, every run log was
kept forever.

These tests cover the two things that were actually missing:

* ``run_retention_once`` — one sweep over run logs, text logs, and spill files.
* ``retention_loop`` — the periodic caller, including that it can be stopped.

They also pin a bug found while writing them: a sweep pointed at one directory
must not reach into the live one through ``spill_store``'s default root.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from atlas import log_rotation


def _old(path: Path, *, seconds: float = 400_000) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _expired(path: Path) -> None:
    """Older than ``keep_days`` (14), which is what actually expires a spill file.

    Deliberately not "25 hours": the 24-hour floor only protects in-flight runs,
    and a 25-hour-old file is still inside the 14-day window and must be kept.
    """
    _old(path, seconds=30 * 86400)


@pytest.fixture()
def log_root(tmp_path) -> Path:
    runs = tmp_path / "runs" / "2026-01-01"
    runs.mkdir(parents=True)
    (tmp_path / "runs" / "2026-01-01" / "tool-output").mkdir(parents=True)
    return tmp_path


def test_a_sweep_archives_an_old_run_log(log_root) -> None:
    target = log_root / "runs" / "2026-01-01" / "r1.jsonl"
    target.write_text('{"event": "run_start"}\n' * 200, encoding="utf-8")
    _old(target)

    report = log_rotation.run_retention_once(log_root)

    assert report["run_logs"]["archived"] == 1
    assert not target.exists()
    assert list((log_root / "runs").rglob("*.zst"))


def test_a_sweep_leaves_a_fresh_run_log_alone(log_root) -> None:
    """A run that is still writing must not be compressed underneath itself."""
    target = log_root / "runs" / "2026-01-01" / "live.jsonl"
    target.write_text('{"event": "run_start"}\n', encoding="utf-8")

    report = log_rotation.run_retention_once(log_root)

    assert report["run_logs"]["archived"] == 0
    assert target.exists()


def test_a_sweep_rotates_an_oversized_text_log(log_root) -> None:
    big = log_root / "atlas.log"
    big.write_text("y" * (40 * 1024 * 1024), encoding="utf-8")

    report = log_rotation.run_retention_once(log_root)

    assert report["text_logs"]["rotated"] == 1
    assert list(log_root.glob("*.zst"))


def test_a_sweep_reports_the_bytes_it_freed(log_root) -> None:
    big = log_root / "atlas.log"
    big.write_text("z" * (40 * 1024 * 1024), encoding="utf-8")

    report = log_rotation.run_retention_once(log_root)

    assert report["freed_bytes"] > 0
    assert report["errors"] == []


def test_an_empty_directory_is_not_an_error(tmp_path) -> None:
    report = log_rotation.run_retention_once(tmp_path)
    assert report["errors"] == []
    assert report["run_logs"]["scanned"] == 0
    assert report["freed_bytes"] == 0


def test_the_sweep_does_not_delete_spill_files_outside_the_directory_it_was_given(
    log_root, monkeypatch
) -> None:
    """The regression that made this test exist.

    ``spill_store.prune()`` with no argument falls back to the *live* log root.
    A sweep over a temp directory therefore deleted real spilled tool output from
    the user's live ``data/logs`` tree. The sweep must confine every part of
    itself to the directory it was handed.
    """
    live = log_root / "elsewhere" / "runs" / "2026-01-01" / "tool-output"
    live.mkdir(parents=True)
    victim = live / "spill.log"
    victim.write_text("real tool output", encoding="utf-8")
    _expired(victim)

    monkeypatch.setattr("atlas.logs.LOG_DIR", log_root / "elsewhere" / "logs")

    report = log_rotation.run_retention_once(log_root)

    assert victim.exists(), "the sweep reached outside the directory it was given"
    assert report["spill"]["removed"] == 0


def test_spill_files_inside_the_given_directory_are_still_pruned(log_root) -> None:
    """Confining the sweep must not disable it."""
    spill = log_root / "runs" / "2026-01-01" / "tool-output" / "old.log"
    spill.write_text("stale", encoding="utf-8")
    _expired(spill)

    report = log_rotation.run_retention_once(log_root)

    assert not spill.exists()
    assert report["spill"]["removed"] == 1


def test_a_recent_spill_file_survives_the_sweep(log_root) -> None:
    """A file from yesterday is not garbage: it is evidence for a run that the
    user can still open. Only the 14-day window expires it."""
    spill = log_root / "runs" / "2026-01-01" / "tool-output" / "recent.log"
    spill.write_text("still interesting", encoding="utf-8")
    _old(spill, seconds=25 * 3600)

    report = log_rotation.run_retention_once(log_root)

    assert spill.exists()
    assert report["spill"]["removed"] == 0


def test_an_in_flight_spill_file_survives_even_when_it_is_old(log_root) -> None:
    """A long turn can hold a spill file open for a long time. Deleting the file a
    running tool is still writing is worse than keeping it a day too long."""
    spill = log_root / "runs" / "2026-01-01" / "tool-output" / "inflight.log"
    spill.write_text("being written", encoding="utf-8")

    report = log_rotation.run_retention_once(log_root)

    assert spill.exists()
    assert report["spill"]["removed"] == 0


def test_one_broken_part_does_not_stop_the_others(log_root, monkeypatch) -> None:
    """A maintenance sweep that aborts on its first failure is a sweep that
    silently stops maintaining."""
    big = log_root / "atlas.log"
    big.write_text("w" * (40 * 1024 * 1024), encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise RuntimeError("run log archiving is broken")

    monkeypatch.setattr(log_rotation, "maintain_run_logs", explode)

    report = log_rotation.run_retention_once(log_root)

    assert any("run_logs" in item for item in report["errors"])
    assert report["text_logs"]["rotated"] == 1


def test_the_loop_is_disabled_by_an_environment_variable(monkeypatch) -> None:
    """Nobody should have to patch code to stop background maintenance."""
    monkeypatch.setenv("ATLAS_LOG_RETENTION", "0")

    async def run() -> None:
        # Returns immediately instead of sleeping for the startup delay.
        await asyncio.wait_for(log_rotation.retention_loop(), timeout=2.0)

    asyncio.run(run())


def test_the_loop_sweeps_and_then_sleeps(tmp_path, monkeypatch) -> None:
    """One real iteration, with the delays collapsed to zero."""
    calls: list[Path | None] = []

    def fake_sweep(directory=None, **_kwargs):
        calls.append(directory)
        return {"run_logs": None, "text_logs": None, "spill": None,
                "freed_bytes": 0, "errors": []}

    monkeypatch.setattr(log_rotation, "run_retention_once", fake_sweep)
    monkeypatch.delenv("ATLAS_LOG_RETENTION", raising=False)

    async def run() -> None:
        task = asyncio.create_task(
            log_rotation.retention_loop(tmp_path, startup_delay=0, interval=0)
        )
        for _ in range(100):
            if calls:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert calls and calls[0] == tmp_path


def test_the_loop_survives_a_failing_sweep(tmp_path, monkeypatch) -> None:
    """A periodic task that dies on its first exception is worse than none: the
    silence looks like "nothing to do"."""
    attempts: list[int] = []

    def explode(directory=None, **_kwargs):
        attempts.append(1)
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(log_rotation, "run_retention_once", explode)
    monkeypatch.delenv("ATLAS_LOG_RETENTION", raising=False)

    async def run() -> None:
        task = asyncio.create_task(
            log_rotation.retention_loop(tmp_path, startup_delay=0, interval=0)
        )
        for _ in range(100):
            if len(attempts) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert len(attempts) >= 2, "the loop stopped after one failure"


def test_cancellation_propagates_instead_of_being_swallowed(tmp_path) -> None:
    """Shutdown must not have to wait out a maintenance sleep."""
    async def run() -> None:
        task = asyncio.create_task(
            log_rotation.retention_loop(tmp_path, startup_delay=60, interval=60)
        )
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    asyncio.run(run())
