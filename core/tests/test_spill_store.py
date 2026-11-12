"""Retention for spilled tool output.

The policy is small but two of its rules are load-bearing and easy to get wrong:
a young file must survive even when the size cap is badly exceeded, and a dry run
must be provably side-effect free. Both are tested directly rather than through a
count that could pass for the wrong reason.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from atlas import spill_store as spill


def _age(path: Path, hours: float) -> None:
    """Backdate ``path`` so the age policy sees it as old."""
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))


@pytest.fixture()
def logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake logs root with two dated run directories."""
    root = tmp_path / "logs"
    for day in ("2026-01-01", "2026-01-02"):
        (root / "runs" / day / "tool-output").mkdir(parents=True)
    monkeypatch.setattr(spill, "_logs_root", lambda: root)
    return root


def _write(path: Path, size: int) -> Path:
    path.write_text("x" * size, encoding="utf-8")
    return path


def test_spill_dirs_finds_every_run_subdir(logs: Path) -> None:
    (logs / "runs" / "2026-01-03" / "compact-output").mkdir(parents=True)
    found = spill.spill_dirs()
    assert len(found) == 3
    assert all(item.name in spill.SPILL_DIR_NAMES for item in found)


def test_spill_dirs_on_a_missing_root_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spill, "_logs_root", lambda: tmp_path / "nope")
    assert spill.spill_dirs() == []


def test_inventory_reports_totals_and_the_largest_file(logs: Path) -> None:
    _write(logs / "runs" / "2026-01-01" / "tool-output" / "a.txt", 100)
    _write(logs / "runs" / "2026-01-01" / "tool-output" / "b.txt", 900)
    _write(logs / "runs" / "2026-01-02" / "tool-output" / "c.txt", 50)

    state = spill.inventory()
    assert state["files"] == 3
    assert state["bytes"] == 1050
    assert state["directory_count"] == 2
    assert state["largest_bytes"] == 900
    assert state["largest_path"].endswith("b.txt")


def test_inventory_on_an_empty_root_says_zero(logs: Path) -> None:
    state = spill.inventory()
    assert state["files"] == 0
    assert state["bytes"] == 0
    assert state["largest_path"] is None


def test_old_files_are_removed_and_young_ones_are_not(logs: Path) -> None:
    old = _write(logs / "runs" / "2026-01-01" / "tool-output" / "old.txt", 10)
    young = _write(logs / "runs" / "2026-01-02" / "tool-output" / "young.txt", 10)
    _age(old, hours=24 * 30)

    report = spill.prune(keep_days=14, min_age_hours=24)
    assert old.exists() is False
    assert young.exists() is True
    assert report["removed_count"] == 1
    assert report["skipped"] == 1


def test_a_young_file_survives_even_when_the_size_cap_is_blown(logs: Path) -> None:
    """The in-flight protection outranks the size target.

    A session that is still running may hold this path; deleting it to satisfy a
    byte budget would trade a live run's evidence for a number.
    """
    young = _write(logs / "runs" / "2026-01-02" / "tool-output" / "young.txt", 5000)

    report = spill.prune(keep_days=14, keep_total_bytes=1, min_age_hours=24)
    assert young.exists() is True
    assert report["removed_count"] == 0
    assert report["kept_bytes"] == 5000


def test_size_cap_removes_oldest_first(logs: Path) -> None:
    oldest = _write(logs / "runs" / "2026-01-01" / "tool-output" / "oldest.txt", 400)
    newer = _write(logs / "runs" / "2026-01-02" / "tool-output" / "newer.txt", 400)
    _age(oldest, hours=24 * 10)
    _age(newer, hours=24 * 5)

    report = spill.prune(keep_days=90, keep_total_bytes=500, min_age_hours=24)
    assert oldest.exists() is False
    assert newer.exists() is True
    assert report["removed_count"] == 1
    assert report["kept_bytes"] == 400


def test_dry_run_deletes_nothing_but_reports_the_same_plan(logs: Path) -> None:
    old = _write(logs / "runs" / "2026-01-01" / "tool-output" / "old.txt", 700)
    _age(old, hours=24 * 30)

    plan = spill.prune(keep_days=14, dry_run=True)
    real = spill.prune(keep_days=14)

    assert plan["removed"] == real["removed"]
    assert plan["freed_bytes"] == real["freed_bytes"] == 700
    assert plan["dry_run"] is True
    assert old.exists() is False  # the *real* run removed it, not the dry one


def test_prune_is_idempotent(logs: Path) -> None:
    old = _write(logs / "runs" / "2026-01-01" / "tool-output" / "old.txt", 10)
    _age(old, hours=24 * 30)

    first = spill.prune(keep_days=14)
    second = spill.prune(keep_days=14)
    assert first["removed_count"] == 1
    assert second["removed_count"] == 0
    assert second["freed_bytes"] == 0


def test_a_subdirectory_is_never_removed(logs: Path) -> None:
    nested = logs / "runs" / "2026-01-01" / "tool-output" / "nested"
    nested.mkdir()
    _age(nested, hours=24 * 30)

    spill.prune(keep_days=14)
    assert nested.is_dir() is True


def test_describe_says_something_true_in_both_states(logs: Path) -> None:
    assert "没有溢出" in spill.describe()

    old = _write(logs / "runs" / "2026-01-01" / "tool-output" / "a.txt", 2 * 1024 * 1024)
    _age(old, hours=24 * 30)
    sentence = spill.describe()
    assert "2.0 MB" in sentence
    assert "1 个文件" in sentence
