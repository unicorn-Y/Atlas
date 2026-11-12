"""Session-log zstd archiving, and the read seam that keeps archives readable.

Run logs are ``runs/<date>/<run_id>.jsonl``. ``maintain_logs`` only globs
``*.log``, so these were never rotated and accumulated one per run forever.

Compressing them is only safe because every reader can now open ``.jsonl.zst``.
Four readers used to glob ``*.jsonl`` directly, and a fifth thought ``p.stem`` was
a run id — which is wrong for ``<id>.jsonl.zst``. Those are the regressions these
tests exist to catch, so they assert the *readers*, not just the compressor.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from atlas.log_rotation import archive_run_log, maintain_run_logs
from atlas.run_replay._util import iter_events, open_run_log, run_id_of


def _run_log(root: Path, run_id: str = "abc-123", *, lines: int = 40) -> Path:
    day = root / "runs" / "2026-01-01"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{run_id}.jsonl"
    rows = [{"event": "tool_start", "tool_call_id": f"c{index}"} for index in range(lines)]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def _age(path: Path, hours: float) -> None:
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))


def test_a_finished_log_is_compressed_and_the_original_removed(tmp_path: Path) -> None:
    path = _run_log(tmp_path)
    report = archive_run_log(path)

    assert report is not None
    assert report["original_bytes"] > report["compressed_bytes"]
    assert path.exists() is False
    assert path.with_name(path.name + ".zst").exists() is True


def test_the_archive_decompresses_to_the_original_bytes(tmp_path: Path) -> None:
    path = _run_log(tmp_path, lines=200)
    original = path.read_text(encoding="utf-8")
    archive_run_log(path)

    archive = path.with_name(path.name + ".zst")
    with open_run_log(archive) as stream:
        assert stream.read() == original


def test_a_log_inside_the_age_window_is_left_alone(tmp_path: Path) -> None:
    """A young log may still be open in a running turn."""
    path = _run_log(tmp_path)

    report = maintain_run_logs(tmp_path, older_than_hours=48)
    assert report["archived"] == []
    assert path.exists() is True
    assert report["scanned"] == 1


def test_an_old_log_is_archived_by_maintain_run_logs(tmp_path: Path) -> None:
    path = _run_log(tmp_path)
    _age(path, hours=72)

    report = maintain_run_logs(tmp_path, older_than_hours=48)
    assert len(report["archived"]) == 1
    assert report["saved_bytes"] > 0
    assert path.exists() is False


def test_rotation_is_idempotent(tmp_path: Path) -> None:
    path = _run_log(tmp_path)
    _age(path, hours=72)

    first = maintain_run_logs(tmp_path, older_than_hours=48)
    second = maintain_run_logs(tmp_path, older_than_hours=48)
    assert len(first["archived"]) == 1
    assert second["archived"] == []
    # The second pass scans nothing: the `.jsonl` is gone.
    assert second["scanned"] == 0


def test_an_existing_archive_is_never_overwritten(tmp_path: Path) -> None:
    """Two rotations racing must not replace a good archive with a shorter one."""
    path = _run_log(tmp_path)
    archive = path.with_name(path.name + ".zst")
    archive.write_bytes(b"pretend this is an older archive")

    assert archive_run_log(path) is None
    assert archive.read_bytes() == b"pretend this is an older archive"
    assert path.exists() is True


def test_run_id_of_handles_both_forms(tmp_path: Path) -> None:
    path = _run_log(tmp_path)
    assert run_id_of(path) == "abc-123"
    assert run_id_of(path.with_name(path.name + ".zst")) == "abc-123"


def test_iter_events_reads_a_compressed_log(tmp_path: Path) -> None:
    path = _run_log(tmp_path, lines=7)
    archive_run_log(path)
    archive = path.with_name(path.name + ".zst")

    rows = [parsed for _, parsed, _ in iter_events(archive) if parsed is not None]
    assert len(rows) == 7
    assert rows[0]["event"] == "tool_start"


def test_the_replay_loader_lists_and_loads_a_compressed_run(tmp_path: Path) -> None:
    """The regression that matters: a rotated run must not read as missing."""
    from atlas.run_replay.loader import list_runs, load_run

    path = _run_log(tmp_path)
    archive_run_log(path)
    runs = tmp_path / "runs"

    ids = [info.id for info in list_runs(runs_dir=runs)]
    assert ids == ["abc-123"], "rotated run vanished from the listing"

    run = load_run("abc-123", runs_dir=runs)
    assert run.id == "abc-123"
    assert run.bad_lines == 0


def test_a_plain_log_still_reads_without_the_compressor(tmp_path: Path) -> None:
    path = _run_log(tmp_path, lines=3)
    with open_run_log(path) as stream:
        assert len(stream.read().splitlines()) == 3


def test_archiving_a_missing_file_reports_nothing(tmp_path: Path) -> None:
    assert archive_run_log(tmp_path / "nope.jsonl") is None


@pytest.mark.parametrize("suffix", [".jsonl", ".jsonl.zst"])
def test_run_id_of_ignores_a_trailing_suffix_only(tmp_path: Path, suffix: str) -> None:
    assert run_id_of(Path(f"some-id{suffix}")) == "some-id"
