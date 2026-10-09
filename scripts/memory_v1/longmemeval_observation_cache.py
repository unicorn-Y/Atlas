"""Durable, fingerprinted LongMemEval observation snapshots for F2-B."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import shutil
import uuid
from pathlib import Path
from typing import Any


TEMP_ROOT = Path(r"D:\Temp")
CACHE_VERSION = 1
SNAPSHOT_DIRECTORIES = ("atlas-data", "hermes-home", "memoryos", "outbox")
SNAPSHOT_FILES = (
    "source_dialogue.jsonl",
    "observer_batches.jsonl",
    "model_calls.jsonl",
    "model_call_timing.jsonl",
)
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _temp_child(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(TEMP_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError("LongMemEval observation cache paths must stay under D:\\Temp") from exc
    return resolved


def question_fingerprint(row: dict[str, Any], identity: dict[str, Any]) -> str:
    """Hash only source-history inputs plus observer/runtime identity, never the gold answer."""
    source = {
        "question_id": str(row.get("question_id") or ""),
        "haystack_sessions": row.get("haystack_sessions"),
        "haystack_session_ids": row.get("haystack_session_ids"),
        "haystack_dates": row.get("haystack_dates"),
    }
    if not source["question_id"]:
        raise ValueError("observation cache fingerprint requires a question ID")
    payload = {"cache_version": CACHE_VERSION, "identity": identity, "source": source}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def question_cache_key(question_id: str) -> str:
    value = str(question_id or "")
    if not value:
        raise ValueError("observation cache key requires a question ID")
    return "question-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def question_cache_entry_path(cache_root: Path, question_id: str, fingerprint: str) -> Path:
    cache_root = _temp_child(cache_root)
    if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
        raise ValueError("observation cache fingerprint must be a lowercase SHA-256")
    return cache_root / "questions" / question_cache_key(question_id) / fingerprint


def _validate_checkpoint(checkpoint: dict[str, Any]) -> None:
    if (
        checkpoint.get("phase") != "OBSERVATION_COMPLETE"
        or checkpoint.get("observe_complete") is not True
        or checkpoint.get("outbox_drained") is not True
        or checkpoint.get("semantic_ready") is not True
        or checkpoint.get("answer_stage_started") is True
    ):
        raise ValueError("refusing to cache an observation without a complete, settled checkpoint")


def _files_manifest(snapshot: Path) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(snapshot.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("observation cache snapshot contains a symlink")
        if path.is_file():
            relative = path.relative_to(snapshot).as_posix()
            files[relative] = {"sha256": _sha256_file(path), "size": path.stat().st_size}
    return files


def _ignore_sqlite_sidecars(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if any(name.lower().endswith(suffix) for suffix in SQLITE_SIDECAR_SUFFIXES)
    }


def _backup_sqlite_databases(source_root: Path, snapshot: Path) -> None:
    """Copy consistent committed SQLite state, including databases currently in WAL mode."""
    for target in sorted(snapshot.rglob("*")):
        if not target.is_file() or target.suffix.lower() not in SQLITE_SUFFIXES:
            continue
        relative = target.relative_to(snapshot)
        source = source_root / relative
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"SQLite snapshot source is missing or unsafe: {relative.as_posix()}")
        temporary = target.with_name(target.name + ".backup-tmp")
        source_db = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        destination_db = sqlite3.connect(str(temporary), timeout=30)
        try:
            source_db.execute("PRAGMA query_only=ON")
            source_db.backup(destination_db, pages=128, sleep=0.05)
            destination_db.commit()
            result = destination_db.execute("PRAGMA integrity_check").fetchone()
            if result != ("ok",):
                raise RuntimeError(
                    f"SQLite snapshot integrity_check failed for {relative.as_posix()}: {result!r}"
                )
        finally:
            destination_db.close()
            source_db.close()
        os.replace(temporary, target)


def _copy_snapshot_assets(source_root: Path, snapshot: Path) -> None:
    for name in SNAPSHOT_DIRECTORIES:
        source = source_root / name
        if source.is_symlink():
            raise RuntimeError(f"refusing symlinked observation root: {name}")
        if source.is_dir():
            shutil.copytree(source, snapshot / name, symlinks=True, ignore=_ignore_sqlite_sidecars)
    for name in SNAPSHOT_FILES:
        source = source_root / name
        if source.is_symlink():
            raise RuntimeError(f"refusing symlinked observation artifact: {name}")
        if source.is_file():
            shutil.copy2(source, snapshot / name)
    _backup_sqlite_databases(source_root, snapshot)


def save_observation_snapshot(
    cache_root: Path,
    question_id: str,
    fingerprint: str,
    source_root: Path,
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Atomically publish a settled service/outbox snapshot; existing entries are immutable."""
    cache_root = _temp_child(cache_root)
    source_root = _temp_child(source_root)
    _validate_checkpoint(checkpoint)
    if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
        raise ValueError("observation cache fingerprint must be a lowercase SHA-256")
    if not source_root.is_dir():
        raise FileNotFoundError("observation source root is missing")

    target = question_cache_entry_path(cache_root, question_id, fingerprint)
    parent = target.parent
    if target.exists():
        return _read_and_validate_entry(target, question_id, fingerprint)

    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / f".tmp-{uuid.uuid4().hex}"
    snapshot = stage / "snapshot"
    snapshot.mkdir(parents=True)
    try:
        _copy_snapshot_assets(source_root, snapshot)
        (snapshot / "observation_checkpoint.json").write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        required = (
            "outbox/unified_outbox.sqlite3",
            "memoryos/db/memoryos.sqlite3",
            "source_dialogue.jsonl",
            "observer_batches.jsonl",
        )
        missing = [name for name in required if not (snapshot / name).is_file()]
        if missing:
            raise FileNotFoundError("observation snapshot is incomplete: " + ", ".join(missing))
        entry = {
            "cache_version": CACHE_VERSION,
            "question_id": str(question_id),
            "fingerprint": fingerprint,
            "checkpoint": checkpoint,
            "files": _files_manifest(snapshot),
        }
        (stage / "entry.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        try:
            os.replace(stage, target)
        except OSError:
            if not target.exists():
                raise
        return _read_and_validate_entry(target, question_id, fingerprint)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _read_and_validate_entry(target: Path, question_id: str, fingerprint: str) -> dict[str, Any]:
    entry_path = target / "entry.json"
    if not entry_path.is_file():
        raise ValueError("observation cache entry is incomplete; refusing implicit re-observation")
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    if (
        entry.get("cache_version") != CACHE_VERSION
        or entry.get("question_id") != str(question_id)
        or entry.get("fingerprint") != fingerprint
        or not isinstance(entry.get("files"), dict)
    ):
        raise ValueError("observation cache entry identity does not match its path")
    _validate_checkpoint(entry.get("checkpoint") if isinstance(entry.get("checkpoint"), dict) else {})
    snapshot = target / "snapshot"
    expected = entry["files"]
    actual = _files_manifest(snapshot)
    if actual != expected:
        raise ValueError("observation cache snapshot content is missing or changed")
    return entry


def restore_observation_snapshot(
    cache_root: Path,
    question_id: str,
    fingerprint: str,
    destination: Path,
) -> dict[str, Any] | None:
    """Clone a matching immutable observation snapshot into a disposable answer world."""
    cache_root = _temp_child(cache_root)
    destination = _temp_child(destination)
    if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
        raise ValueError("observation cache fingerprint must be a lowercase SHA-256")
    target = question_cache_entry_path(cache_root, question_id, fingerprint)
    if not target.exists():
        return None
    entry = _read_and_validate_entry(target, question_id, fingerprint)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("answer runtime destination must be empty before snapshot restore")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(target / "snapshot", destination, dirs_exist_ok=True, symlinks=True)
    return entry


__all__ = [
    "question_fingerprint", "question_cache_key", "question_cache_entry_path", "save_observation_snapshot",
    "restore_observation_snapshot",
]
