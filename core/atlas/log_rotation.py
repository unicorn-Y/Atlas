"""Compressed log rotation.

Rotates oversized text logs to zstd-compressed archives, then prunes old
archives by age and by total size. Windows-safe: the active file is never
moved while a writer holds it, we copy-then-truncate instead of rename.

All failures are swallowed and reported as ``None`` — log maintenance must
never crash the process it is maintaining.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

DEFAULT_MAX_BYTES = 32 * 1024 * 1024  # 32 MiB per file
DEFAULT_KEEP_DAYS = 14
DEFAULT_KEEP_TOTAL = 512 * 1024 * 1024  # 512 MiB of archives


def _zstd_compress_file(source: Path, target: Path) -> int:
    """Compress ``source`` into ``target``. Returns compressed byte count.

    Integrity is verified by decompressing and comparing, not by a size heuristic:
    highly repetitive logs legitimately compress 4000:1, so "frame looks too small"
    is not evidence of a bug.
    """
    import hashlib

    import zstandard

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = source.read_bytes()
    compressed = zstandard.ZstdCompressor(level=10).compress(payload)
    target.write_bytes(compressed)
    restored = zstandard.ZstdDecompressor().decompress(
        compressed, max_output_size=max(len(payload), 1)
    )
    if hashlib.sha256(restored).digest() != hashlib.sha256(payload).digest():
        target.unlink(missing_ok=True)
        raise OSError("zstd round-trip mismatch")
    return len(compressed)


def rotate_log(
    path: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    compress: bool = True,
) -> dict[str, Any] | None:
    """Rotate ``path`` if it exceeds ``max_bytes``.

    Returns a report dict on rotation, ``None`` when nothing was done.
    """
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_size <= max_bytes:
        return None

    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(stat.st_mtime))
    archive = path.with_name(f"{path.name}.{stamp}.zst" if compress else f"{path.name}.{stamp}")
    if archive.exists():
        archive = path.with_name(f"{path.name}.{stamp}-{os.getpid()}.zst")

    original = stat.st_size
    compressed: int | None = None
    try:
        if compress:
            compressed = _zstd_compress_file(path, archive)
        else:
            archive.write_bytes(path.read_bytes())
            compressed = archive.stat().st_size
    except Exception as exc:  # noqa: BLE001 - maintenance must not raise
        log.warning("log.rotate.compress_failed", path=str(path), error=str(exc))
        return None

    # Truncate in place: a live writer on Windows keeps its handle, and a
    # rename would either fail or split the stream across two files.
    try:
        with path.open("w", encoding="utf-8"):
            pass
    except OSError as exc:
        log.warning("log.rotate.truncate_failed", path=str(path), error=str(exc))
        return None

    return {
        "path": str(path),
        "archive": str(archive),
        "original_bytes": original,
        "compressed_bytes": compressed,
        "ratio": round(compressed / original, 4) if original else None,
    }


def prune_archives(
    directory: str | Path,
    *,
    keep_days: int = DEFAULT_KEEP_DAYS,
    keep_total_bytes: int = DEFAULT_KEEP_TOTAL,
) -> dict[str, Any]:
    """Delete archives older than ``keep_days``, then oldest-first to fit the cap."""
    directory = Path(directory)
    removed: list[str] = []
    freed = 0
    if not directory.is_dir():
        return {"removed": removed, "freed_bytes": 0, "kept": 0}

    cutoff = time.time() - keep_days * 86400
    archives: list[tuple[float, int, Path]] = []
    for item in directory.glob("*.zst"):
        try:
            st = item.stat()
        except OSError:
            continue
        archives.append((st.st_mtime, st.st_size, item))

    survivors: list[tuple[float, int, Path]] = []
    for mtime, size, item in sorted(archives):
        if mtime < cutoff:
            try:
                item.unlink()
                removed.append(item.name)
                freed += size
            except OSError:
                survivors.append((mtime, size, item))
        else:
            survivors.append((mtime, size, item))

    total = sum(size for _, size, _ in survivors)
    for _, size, item in sorted(survivors):
        if total <= keep_total_bytes:
            break
        try:
            item.unlink()
            removed.append(item.name)
            freed += size
            total -= size
        except OSError:
            pass

    return {"removed": removed, "freed_bytes": freed, "kept": total}


def archive_run_log(
    path: Path,
    *,
    keep_bytes: int = 0,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Compress one finished run log to ``<name>.zst`` and remove the original.

    Run logs live at ``runs/<date>/<run_id>.jsonl`` and are written by
    ``atlas.logs.append_run_event``. ``maintain_logs`` never touched them: it globs
    ``*.log``, and these are ``.jsonl`` one directory deeper. So they accumulated
    one file per run forever — 398 files on one install, with the largest at 1.1 MB.

    Safety rules, in order:

    * ``keep_bytes`` protects an active run. A log is only finished once
      ``run_end`` has been written; the caller passes the live file's size, and a
      file that has grown past it is still being appended to.
    * The archive is written and **verified by decompression** before the original
      is unlinked, the same contract ``_zstd_compress_file`` uses for ``*.log``.
    * Any failure returns ``None`` with the original intact.

    Every reader resolves ``.jsonl.zst`` through ``atlas.run_replay._util``, so
    compression does not make a run unreadable — replay, repair, subagent usage
    recovery and the rollout endpoint all go through that seam.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if keep_bytes and size >= keep_bytes:
        return None
    target = path.with_name(path.name + ".zst")
    if target.exists():
        # A previous rotation already produced an archive; leave both alone rather
        # than overwrite evidence with a possibly shorter version.
        return None
    try:
        import hashlib

        import zstandard

        payload = path.read_bytes()
        compressed = zstandard.ZstdCompressor(level=10).compress(payload)
        restored = zstandard.ZstdDecompressor().decompress(
            compressed, max_output_size=max(len(payload), 1)
        )
        if hashlib.sha256(restored).digest() != hashlib.sha256(payload).digest():
            return None
        target.write_bytes(compressed)
        path.unlink()
    except Exception:  # noqa: BLE001 - maintenance must never break the caller
        log.warning("log_rotation.run_archive_failed", path=str(path), exc_info=True)
        return None
    original = len(payload)
    return {
        "path": str(path),
        "archive": str(target),
        "original_bytes": original,
        "compressed_bytes": len(compressed),
        "ratio": round(len(compressed) / original, 4) if original else None,
    }


def maintain_run_logs(
    directory: str | Path | None = None,
    *,
    older_than_hours: int = 48,
    keep_total_bytes: int = DEFAULT_KEEP_TOTAL,
    now: float | None = None,
) -> dict[str, Any]:
    """Archive every run log under ``runs/`` that is finished and older than the cutoff.

    Finished means: no writer can still be appending. The kernel opens the file in
    append mode and writes ``run_end`` at the end, and the mtime moves with every
    write, so an mtime older than ``older_than_hours`` is the only signal available
    without a lock. 48 hours is deliberately generous — a long-running agent turn
    still holds its own file, and compressing it mid-run would corrupt the log.
    """
    if directory is None:
        from atlas.config import PROJECT_ROOT

        directory = PROJECT_ROOT / "data" / "logs"
    directory = Path(directory)
    runs = directory / "runs"
    archived: list[dict[str, Any]] = []
    scanned = 0
    if runs.is_dir():
        cutoff = (now if now is not None else time.time()) - max(0, older_than_hours) * 3600
        for item in sorted(runs.glob("*/*.jsonl")):
            scanned += 1
            try:
                if item.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            report = archive_run_log(item)
            if report:
                archived.append(report)
    saved = sum((r["original_bytes"] or 0) - (r["compressed_bytes"] or 0) for r in archived)
    return {
        "directory": str(runs),
        "scanned": scanned,
        "archived": archived,
        "saved_bytes": saved,
        "keep_total_bytes": keep_total_bytes,
        "older_than_hours": older_than_hours,
    }


def maintain_logs(
    directory: str | Path | None = None,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep_days: int = DEFAULT_KEEP_DAYS,
    keep_total_bytes: int = DEFAULT_KEEP_TOTAL,
) -> dict[str, Any]:
    """Rotate every oversized ``*.log`` in ``directory``, then prune archives."""
    if directory is None:
        from atlas.config import PROJECT_ROOT

        directory = PROJECT_ROOT / "data" / "logs"
    directory = Path(directory)

    rotated: list[dict[str, Any]] = []
    scanned = 0
    if directory.is_dir():
        for item in sorted(directory.glob("*.log")):
            scanned += 1
            report = rotate_log(item, max_bytes=max_bytes)
            if report:
                rotated.append(report)

    pruned = prune_archives(
        directory, keep_days=keep_days, keep_total_bytes=keep_total_bytes
    )
    return {
        "directory": str(directory),
        "scanned": scanned,
        "rotated": rotated,
        "pruned": pruned,
        "saved_bytes": sum(
            (r["original_bytes"] or 0) - (r["compressed_bytes"] or 0) for r in rotated
        ),
    }


# How long after startup the first sweep runs, and how often after that.
# The delay matters: startup is already the busiest moment in the process, and
# compressing a few hundred logs would compete with the first turns for disk.
RETENTION_STARTUP_DELAY_SECONDS = 300
RETENTION_INTERVAL_SECONDS = 6 * 3600


def run_retention_once(
    directory: str | Path | None = None,
    *,
    older_than_hours: int = 48,
    keep_days: int = DEFAULT_KEEP_DAYS,
    keep_total_bytes: int = DEFAULT_KEEP_TOTAL,
    now: float | None = None,
) -> dict[str, Any]:
    """One complete retention sweep: run logs, text logs, and spill files.

    Kept separate from the loop so it can be called directly (CLI, tests, or a
    future "clean up now" button) and so the loop itself contains no logic.
    Every part is independently guarded: a missing zstandard, a locked spill file,
    or an unreadable directory must not stop the other two from running.
    """
    report: dict[str, Any] = {"run_logs": None, "text_logs": None, "spill": None,
                              "freed_bytes": 0, "errors": []}

    try:
        runs = maintain_run_logs(directory, older_than_hours=older_than_hours,
                                 keep_total_bytes=keep_total_bytes, now=now)
    except Exception as exc:  # noqa: BLE001 —— 维护任务不能把主进程带走
        report["errors"].append(f"run_logs: {exc}")
        log.warning("retention.run_logs_failed", error=str(exc))
    else:
        report["run_logs"] = {"scanned": runs["scanned"], "archived": len(runs["archived"]),
                              "saved_bytes": runs["saved_bytes"]}
        report["freed_bytes"] += runs["saved_bytes"]

    try:
        texts = maintain_logs(directory, keep_days=keep_days,
                              keep_total_bytes=keep_total_bytes)
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"text_logs: {exc}")
        log.warning("retention.text_logs_failed", error=str(exc))
    else:
        report["text_logs"] = {"scanned": texts["scanned"], "rotated": len(texts["rotated"]),
                               "saved_bytes": texts["saved_bytes"]}
        report["freed_bytes"] += texts["saved_bytes"]

    try:
        from atlas import spill_store

        # The spill root must be derived from ``directory``, never left to
        # ``spill_store``'s own default. A sweep pointed at a temp or archived log
        # directory would otherwise reach into the *live* one and delete real
        # files — the caller asked to maintain one tree, not every tree.
        spill_root = Path(directory) if directory is not None else None
        plan = spill_store.prune(
            spill_root, keep_days=keep_days, keep_total_bytes=keep_total_bytes
        )
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"spill: {exc}")
        log.warning("retention.spill_failed", error=str(exc))
    else:
        removed = plan.get("removed") or []
        report["spill"] = {"removed": len(removed),
                           "freed_bytes": plan.get("freed_bytes", 0)}
        report["freed_bytes"] += plan.get("freed_bytes", 0) or 0

    if report["freed_bytes"]:
        log.info("retention.swept", freed_bytes=report["freed_bytes"],
                 errors=len(report["errors"]))
    return report


async def retention_loop(
    directory: str | Path | None = None, *,
    startup_delay: float = RETENTION_STARTUP_DELAY_SECONDS,
    interval: float = RETENTION_INTERVAL_SECONDS,
) -> None:
    """Sweep old logs and spill files periodically, in the background.

    Without this, ``maintain_run_logs`` was reachable only from
    ``atlas logs maintain`` — meaning the default path, a user who never opens a
    terminal, kept every run log forever. Compression exists only where something
    calls it; this is that caller.

    ``ATLAS_LOG_RETENTION=0`` disables it. The loop never raises: a cancelled task
    propagates (shutdown), anything else is logged and the loop continues, because
    a maintenance task that dies silently is worse than one that does nothing.
    """
    import asyncio
    import os

    if os.environ.get("ATLAS_LOG_RETENTION", "1") == "0":
        return
    try:
        await asyncio.sleep(startup_delay)
        while True:
            try:
                await asyncio.to_thread(run_retention_once, directory)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 —— 定时任务不能死
                log.exception("retention.loop_failed")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise

