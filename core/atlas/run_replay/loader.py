"""Discovery and streaming load of Atlas run event logs.

On-disk layout (verified against the real archive, 343 files):

    data/logs/runs/<YYYY-MM-DD>/<run_id>.jsonl

* Exactly two levels deep. The file stem **is** the ``run_id`` (a UUID), and the
  same value is repeated inside every event as ``run_id``.
* One run normally owns one file. A run whose ``_run_paths`` memo is cleared by
  ``run_end`` and then receives more events can own **two** files in two
  different date directories. ``list_runs`` therefore groups by run id and merges
  those files.
* Sibling artifact directories (``tool-output/``, ``compact-output/``) live next
  to the JSONL files but are never read here; ``output_ref`` values inside the
  log are already absolute paths.

Both entry points open files in text read mode only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Iterator

from ._util import as_int, as_str, iter_events, loads, parse_ts_ms, run_id_of
from .models import Run, RunInfo

__all__ = [
    "RunNotFoundError",
    "default_runs_dir",
    "iter_run_files",
    "list_runs",
    "load_run",
]


class RunNotFoundError(LookupError):
    """Raised when no run file matches the given id or path."""


def default_runs_dir() -> Path:
    """Return the run-log directory, honouring ``ATLAS_RUNS_DIR``.

    Resolution order:

    1. ``ATLAS_RUNS_DIR`` -- explicit override, used by tests and by anyone
       pointing the tool at an archive copy;
    2. ``<DATA_ROOT>/data/logs/runs`` where ``DATA_ROOT`` comes from
       :mod:`atlas.config` (which itself honours ``ATLAS_DATA_DIR``).

    The config import is lazy so this package stays usable without the rest of
    Atlas, and so tests can redirect ``ATLAS_DATA_DIR`` afterwards.
    """
    override = os.environ.get("ATLAS_RUNS_DIR")
    if override:
        return Path(override).expanduser()
    try:
        from atlas.config import DATA_ROOT  # noqa: PLC0415 - lazy by design
    except Exception:  # pragma: no cover - only when Atlas is not importable
        return Path.home() / "Atlas" / "data" / "logs" / "runs"
    return Path(DATA_ROOT) / "data" / "logs" / "runs"


def iter_run_files(runs_dir: Path | str | None = None) -> Iterator[Path]:
    """Yield every run log file under ``runs_dir`` in stable path order.

    Missing or unreadable directories yield nothing instead of raising: a fresh
    install legitimately has no ``runs`` directory yet.
    """
    root = Path(runs_dir) if runs_dir is not None else default_runs_dir()
    if not root.is_dir():
        return
    candidates: list[Path] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            try:
                if entry.is_dir():
                    candidates.extend(sorted(entry.glob("*.jsonl"), key=lambda p: p.name))
                    # Rotation compresses finished runs; a compressed archive is
                    # still a readable run, so listing must not skip it.
                    candidates.extend(sorted(entry.glob("*.jsonl.zst"), key=lambda p: p.name))
                elif entry.suffix in (".jsonl", ".zst"):
                    candidates.append(entry)
            except OSError:
                continue
    except OSError:
        return
    for path in candidates:
        try:
            if path.is_file():
                yield path
        except OSError:
            continue


def _scan_file(path: Path) -> dict:
    """Summarise one file: line count, bad-line count, first/last event, mtime.

    Every line is JSON-decoded so this counter always agrees with
    :attr:`Run.bad_lines`, but nothing is retained beyond the first and last
    event, so ``list_runs`` stays one sequential read per file with memory
    bounded by a single line.
    """
    counts = 0
    bad = 0
    first: dict | None = None
    last: dict | None = None
    run_end_raw = ""
    ends_with_newline = True
    session_id: str | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                counts += 1
                ends_with_newline = raw.endswith("\n")
                stripped = raw.strip()
                if not stripped:
                    bad += 1
                    continue
                # Every line is decoded so that ``RunInfo.bad_lines`` agrees
                # exactly with :attr:`Run.bad_lines`; a cheaper structural test
                # cannot catch a brace-wrapped line whose bytes are still
                # unparseable (a crash-merged half line, for instance).
                parsed = loads(stripped)
                if parsed is None:
                    bad += 1
                    continue
                if first is None:
                    first = parsed
                last = parsed
                # run_start may not be the first line (api_timing and request
                # envelopes land first), so capture the owning session from any
                # run_start event while the file is being read anyway.
                if session_id is None and parsed.get("event") == "run_start":
                    session_id = as_str(parsed.get("session_id"))
                # Cheap substring test before paying for a second decode: only
                # ``run_end`` carries the authoritative duration. Both separator
                # styles are matched so a compact re-serialisation still counts,
                # and a mere *mention* of "run_end" inside a tool output cannot
                # masquerade as the real terminator (the key must be present).
                if '"event": "run_end"' in stripped or '"event":"run_end"' in stripped:
                    run_end_raw = stripped
    except OSError:
        return {
            "size": 0,
            "mtime": 0.0,
            "event_count": 0,
            "bad_lines": 0,
            "first": None,
            "last": None,
            "truncated": False,
            "duration_ms": None,
            "end_status": None,
        }

    duration_ms: int | None = None
    end_status: str | None = None
    if run_end_raw:
        parsed_end = loads(run_end_raw)
        if parsed_end is not None and parsed_end.get("event") == "run_end":
            duration_ms = as_int(parsed_end.get("duration_ms"))
            end_status = as_str(parsed_end.get("status"))

    try:
        stat = path.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        size, mtime = 0, 0.0

    # A final line with no trailing newline means the writer was cut off
    # mid-append (crash, kill, disk full) -- surface it as truncation.
    truncated = bool(counts and not ends_with_newline)

    return {
        "size": size,
        "mtime": mtime,
        "event_count": counts - bad,
        "bad_lines": bad,
        "first": first if isinstance(first, dict) else None,
        "last": last if isinstance(last, dict) else None,
        "session_id": session_id,
        "truncated": truncated,
        "duration_ms": duration_ms,
        "end_status": end_status,
    }


def _group_files(files: Iterable[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in files:
        groups.setdefault(run_id_of(path), []).append(path)
    for paths in groups.values():
        paths.sort(key=lambda p: (str(p.parent.name), p.name))
    return groups


def _merge_info(run_id: str, paths: list[Path]) -> RunInfo:
    """Merge the one-or-more files of a single run id into one :class:`RunInfo`."""
    size = 0
    mtime = 0.0
    event_count = 0
    bad_lines = 0
    # A file cut off mid-append holds one line that is *counted* as a line but
    # never usable as an event: counting it as neither would silently lose data.
    unterminated = 0
    start_time: str | None = None
    end_time: str | None = None
    session_id: str | None = None
    status: str | None = None
    main_path = paths[0]
    main_count = -1
    duration_ms: int | None = None

    for path in paths:
        scan = _scan_file(path)
        size += scan["size"]
        mtime = max(mtime, scan["mtime"])
        event_count += scan["event_count"]
        bad_lines += scan["bad_lines"]
        if scan["truncated"]:
            unterminated += 1
        if scan["duration_ms"] is not None:
            duration_ms = scan["duration_ms"]
        if scan["end_status"]:
            status = scan["end_status"]
        if scan["event_count"] > main_count:
            main_count = scan["event_count"]
            main_path = path
        first, last = scan["first"], scan["last"]
        # Captured by the full-file scan below: run_start is not always the
        # first line (api_timing lands first), so trust the scan result.
        session_id = session_id or scan.get("session_id")
        if first:
            if first.get("event") == "run_start":
                session_id = session_id or as_str(first.get("session_id"))
            stamp = as_str(first.get("timestamp"))
            if stamp and (start_time is None or stamp < start_time):
                start_time = stamp
            elif start_time is None:
                start_time = stamp
        if last:
            stamp = as_str(last.get("timestamp"))
            if stamp and (end_time is None or stamp > end_time):
                end_time = stamp
            if last.get("event") == "run_end":
                status = as_str(last.get("status")) or status

    return RunInfo(
        id=run_id,
        path=str(main_path),
        size=size,
        mtime=mtime,
        event_count=event_count,
        session_id=session_id,
        start_time=start_time,
        end_time=end_time,
        status=status,
        files=[str(p) for p in paths],
        bad_lines=bad_lines,
        duration_ms=duration_ms,
    )


def list_runs(
    limit: int | None = 50,
    runs_dir: Path | str | None = None,
) -> list[RunInfo]:
    """List runs newest-first.

    :param limit: maximum rows to return; ``None`` or a negative value returns
        everything.
    :param runs_dir: override the log directory (defaults to
        :func:`default_runs_dir`).

    Each row costs one sequential read of its file(s); nothing is retained. A run
    split across two date directories appears **once**, with ``files`` listing
    both and sizes/counts summed.
    """
    groups = _group_files(iter_run_files(runs_dir))
    infos = [_merge_info(run_id, paths) for run_id, paths in groups.items()]

    def sort_key(info: RunInfo) -> tuple[float, float]:
        started = parse_ts_ms(info.start_time)
        if started is None:
            started = info.mtime * 1000.0
        return (started, info.mtime)

    infos.sort(key=sort_key, reverse=True)
    if limit is not None and limit >= 0:
        return infos[:limit]
    return infos


def _resolve(target: str | Path, runs_dir: Path | str | None) -> list[Path]:
    """Turn a run id or a file path into the list of files belonging to that run."""
    if isinstance(target, Path):
        path = target
    else:
        text = str(target)
        path = Path(text)
        if not path.is_file():
            wanted = text[:-6] if text.endswith(".jsonl") else text
            found = [p for p in iter_run_files(runs_dir) if run_id_of(p) == wanted]
            if not found and wanted:
                # A prefix is accepted because run ids are long UUIDs that no one
                # types or pastes in full; ambiguity is an error, not a guess.
                found = [p for p in iter_run_files(runs_dir) if run_id_of(p).startswith(wanted)]
                stems = sorted({run_id_of(p) for p in found})
                if len(stems) > 1:
                    raise RunNotFoundError(
                        f"{target!r} is ambiguous: {', '.join(s[:12] for s in stems[:6])}"
                        + (" ..." if len(stems) > 6 else "")
                    )
            if not found:
                raise RunNotFoundError(f"no run matches {target!r}")
            return found
    if not path.is_file():
        raise RunNotFoundError(f"no run log file at {path}")
    # An explicit path still picks up same-id siblings in another date directory
    # (the run that spans midnight, or the post-`run_end` continuation file).
    siblings = [p for p in iter_run_files(path.parent.parent) if run_id_of(p) == run_id_of(path)]
    if not siblings:
        return [path]
    return sorted(set(siblings) | {path}, key=lambda p: (str(p.parent.name), p.name))


def load_run(target: str | Path, runs_dir: Path | str | None = None) -> Run:
    """Stream one run into a :class:`Run`.

    ``target`` is either a run id (``cfd2b631-...``) or a path to a ``.jsonl``
    file. Files are read line by line; malformed lines are counted in
    :attr:`Run.bad_lines` with their line numbers kept, and parsing never raises.

    Only semantically meaningful events are materialised (model calls, tool
    calls, errors, run boundary); high-frequency bookkeeping events such as
    ``api_timing`` and ``tool_offer`` are counted only. Memory scales with the
    number of real steps, not with file size.
    """
    paths = _resolve(target, runs_dir)
    if not paths:
        raise RunNotFoundError(f"no run matches {target!r}")

    from .timeline import RunBuilder  # noqa: PLC0415 - avoids an import cycle

    builder = RunBuilder(run_id=run_id_of(paths[0]))
    for path in paths:
        builder.begin_file(path)
        for number, event, raw in iter_events(path):
            builder.add_line(number, event, raw)
        builder.end_file(path)

    return builder.build(paths)
