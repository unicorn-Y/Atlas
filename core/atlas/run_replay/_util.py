"""Small, dependency-free helpers shared by the run-replay modules.

Every helper is total: it never raises on unexpected input, it returns
``None``/a default instead. The run log is append-only production data, so a
single malformed field must never take down a report.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

__all__ = [
    "as_bool",
    "as_int",
    "as_str",
    "iter_events",
    "loads",
    "open_run_log",
    "parse_ts",
    "run_id_of",
    "run_log_variants",
    "parse_ts_ms",
]


def loads(line: str) -> dict[str, Any] | None:
    """Parse one JSONL line into a dict, or ``None`` when it is not usable.

    Non-object JSON (list/number/string) is also rejected: the writer only ever
    emits objects, so anything else means corruption, not a new schema.
    """
    try:
        value = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    return value


def as_int(value: Any) -> int | None:
    """Coerce to ``int`` without raising; ``bool`` is rejected as a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def as_str(value: Any) -> str | None:
    """Coerce to ``str``; empty strings are treated as absent."""
    if isinstance(value, str):
        return value or None
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def as_bool(value: Any) -> bool | None:
    """Coerce to ``bool``; ``None`` when the value cannot be interpreted."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
    return None


def parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp from the log (``...+00:00``), timezone-aware."""
    text = as_str(value)
    if not text:
        return None
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalised)
    except ValueError:
        return None


def parse_ts_ms(value: Any) -> float | None:
    """Timestamp as epoch milliseconds, or ``None`` when unparseable."""
    moment = parse_ts(value)
    if moment is None:
        return None
    try:
        return moment.timestamp() * 1000.0
    except (OverflowError, OSError, ValueError):
        return None


def open_run_log(path: Path):  # noqa: ANN201 - text stream, see docstring
    """Open a run log for reading, transparently handling zstd-compressed archives.

    Run logs are plain ``.jsonl`` while a run is live. Rotation later compresses
    the finished ones to ``.jsonl.zst``, because these files were never touched by
    :mod:`atlas.log_rotation` — it only globs ``*.log`` — and they accumulate one
    file per run forever.

    Every reader must therefore go through this function instead of ``open``.
    There are four of them (replay, repair, subagent usage recovery, the workspace
    diagnostic endpoint) and they each globbed ``*.jsonl`` directly; compressing
    without this seam would have turned a handful of old runs into "archive
    missing" errors that only appear months later.
    """
    if path.suffix == ".zst":
        import io

        import zstandard

        # The raw handle must outlive this call, so it is neither wrapped in a
        # ``with`` (which would close it on return) nor dropped — the text wrapper
        # is given a reference and closes it when the caller closes the stream.
        raw = path.open("rb")
        try:
            reader = zstandard.ZstdDecompressor().stream_reader(raw, closefd=True)
            return io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
        except Exception:
            raw.close()
            raise
    return path.open("r", encoding="utf-8", errors="replace")


def run_log_variants(path: Path) -> list[Path]:
    """The readable forms of one run log, compressed first if it exists.

    A run id can legitimately exist twice — the live ``.jsonl`` and a stale
    ``.jsonl.zst`` left by rotation — and the compressed one is always the
    finished one, so it wins. Callers that glob for ``<run_id>.jsonl`` should
    resolve through this instead of assuming the plain name.
    """
    compressed = path.with_name(path.name + ".zst")
    return [compressed, path] if compressed.exists() else [path]


def run_id_of(path: Path) -> str:
    """The run id a log file belongs to, regardless of whether it is compressed.

    ``Path.stem`` is not enough: ``<id>.jsonl.zst`` stems to ``<id>.jsonl``, so a
    rotated run would stop matching its own id and report as missing. Both the
    live and the archived form must resolve to the same string.
    """
    name = path.name
    if name.endswith(".jsonl.zst"):
        return name[: -len(".jsonl.zst")]
    if name.endswith(".jsonl"):
        return name[: -len(".jsonl")]
    return path.stem


def iter_events(path: Path) -> Iterator[tuple[int, dict[str, Any] | None, str]]:
    """Yield ``(line_number, parsed_or_None, raw_line)`` for one JSONL file.

    The file is consumed **line by line** in read-only text mode, so memory is
    bounded by the longest single line rather than by the file size. Blank lines
    are yielded with ``None`` as well; callers decide whether to count them as
    damage (they are: the writer never emits blank lines).

    ``.jsonl.zst`` archives are decompressed on the fly; see
    :func:`open_run_log` for why that case exists at all.
    """
    try:
        handle = open_run_log(path)
    except OSError:
        return
    try:
        for number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            yield number, (loads(stripped) if stripped else None), raw
    finally:
        handle.close()
