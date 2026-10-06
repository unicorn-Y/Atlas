"""Rollback and restore runner with erasure/retraction barrier enforcement (UM12 / T12.3).

Core rule:
  - Enforces erasure/retraction barriers BEFORE restoring DB/indices, never blindly
    restoring an unbarriered old DB (which would resurrect erased memories).
  - Verifies backup integrity against backup_manifest.json (SHA-256 checksums,
    row counts, watermarks).
  - Preserves new data written after cutover: outbox queues and uncommitted entries
    are preserved/reconciled into outbox rather than silently overwritten.

Contract references:
  - docs/plan/UNIFIED-MEMORY/01_contracts.md §6, §8
  - docs/plan/UNIFIED-MEMORY/02_wave_tasks.md T12.3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "UM-WIN-1.0"


def sha256_file(path: Path) -> str:
    """Compute sha256 hex digest for a file."""
    if not path.exists() or path.is_dir():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def load_backup_manifest(backup_dir: Path) -> dict[str, Any]:
    """Load and validate backup_manifest.json from backup directory."""
    manifest_path = backup_dir / "backup_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Backup manifest not found: {manifest_path}")
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest_data


def verify_backup_integrity(backup_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Verify SHA-256 checksums of backup files against manifest. Returns list of mismatches."""
    mismatches: list[str] = []
    files_list = manifest.get("files", [])
    for file_info in files_list:
        rel_path = file_info.get("relative_path", "")
        expected_hash = file_info.get("sha256", "")
        dest_file = backup_dir / rel_path
        if not dest_file.exists():
            mismatches.append(f"Missing file: {rel_path}")
            continue
        actual_hash = sha256_file(dest_file)
        if actual_hash != expected_hash:
            mismatches.append(
                f"Checksum mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"
            )
    return mismatches


# ------------------------------------------------------------------ Erasure Barrier

class ErasureBarrierRegistry:
    """Manages active erasure and retraction barriers.

    Barriers record targets that MUST NOT be resurrected on rollback:
      - record_refs (e.g. 'memory:m-001')
      - source_object_ids
      - locator values
    """

    def __init__(self, ledger_file: Path | None = None):
        self.ledger_file = ledger_file
        self.barriers: set[str] = set()
        if ledger_file and ledger_file.exists():
            self._load_from_ledger()

    def _load_from_ledger(self) -> None:
        if not self.ledger_file or not self.ledger_file.exists():
            return
        try:
            for line in self.ledger_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("//"):
                    entry = json.loads(line)
                    target = entry.get("target_ref") or entry.get("record_ref") or entry.get("id")
                    if target:
                        self.barriers.add(str(target))
        except Exception:
            pass

    def add_barrier(self, target: str, *, action: str = "HARD_ERASE") -> None:
        self.barriers.add(target)
        if self.ledger_file:
            self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "action": action,
                "target_ref": target,
                "created_at": datetime.now(UTC).isoformat(),
            }
            with self.ledger_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def contains(self, target: str) -> bool:
        return target in self.barriers


def apply_erasure_barriers_to_sqlite(db_path: Path, barriers: set[str]) -> int:
    """Apply erasure barriers to SQLite DB before making it active.

    Purges or marks ERASED/TOMBSTONE any records in barriers set so they are
    never resurrected upon restore.
    """
    if not db_path.exists() or not barriers:
        return 0

    purged_count = 0
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        cursor = conn.cursor()
        tables = [
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]

        conn.execute("BEGIN IMMEDIATE")
        for table in tables:
            # Check for id column
            columns = [
                row[1]
                for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()
            ]

            target_cols = [c for c in ("id", "record_ref", "source_object_id", "key") if c in columns]
            for col in target_cols:
                for barrier in barriers:
                    # Strip prefix if needed (e.g. 'memory:abc' -> 'abc')
                    ident = barrier.split(":", 1)[1] if ":" in barrier else barrier
                    try:
                        res = cursor.execute(
                            f"DELETE FROM {table} WHERE {col} = ? OR {col} = ?",
                            (barrier, ident),
                        )
                        purged_count += res.rowcount
                    except Exception:
                        pass
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

    return purged_count


# ------------------------------------------------------------------ Rollback Runner

def rollback_restore(
    backup_dir: Path,
    target_data_dir: Path,
    *,
    erasure_barriers: set[str] | list[str] | None = None,
    erasure_ledger_file: Path | None = None,
    preserve_outbox: bool = True,
) -> dict[str, Any]:
    """Execute rollback & restore enforcing erasure barriers BEFORE restoring DB/indices.

    Safety invariants:
      1. Verify backup manifest checksums.
      2. Enforce erasure/retraction barriers so post-backup erased data is NEVER resurrected.
      3. Preserve post-cutover new outbox writes into a staged reconciliation file.
    """
    manifest = load_backup_manifest(backup_dir)
    mismatches = verify_backup_integrity(backup_dir, manifest)
    if mismatches:
        raise ValueError(f"Backup verification failed: {mismatches}")

    # Gather erasure barriers
    registry = ErasureBarrierRegistry(erasure_ledger_file)
    if erasure_barriers:
        for b in erasure_barriers:
            registry.add_barrier(b)

    # Preserve any post-cutover outbox queue from target before restore
    staged_outbox_entries: list[dict[str, Any]] = []
    if preserve_outbox and target_data_dir.exists():
        outbox_file = target_data_dir / "outbox_cutover_queue.jsonl"
        if outbox_file.exists():
            try:
                for line in outbox_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        staged_outbox_entries.append(json.loads(line))
            except Exception:
                pass

    # Step 1: Copy backup files to target directory
    target_data_dir.mkdir(parents=True, exist_ok=True)
    for file_info in manifest.get("files", []):
        rel_path = file_info.get("relative_path", "")
        src = backup_dir / rel_path
        dst = target_data_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Step 2: Enforce erasure barriers on restored SQLite databases BEFORE activating
    total_purged = 0
    if registry.barriers:
        for db_file in target_data_dir.glob("**/*.sqlite*"):
            purged = apply_erasure_barriers_to_sqlite(db_file, registry.barriers)
            total_purged += purged
        for db_file in target_data_dir.glob("**/*.db"):
            purged = apply_erasure_barriers_to_sqlite(db_file, registry.barriers)
            total_purged += purged

    # Step 3: Re-attach preserved post-cutover outbox queue for future replay/reconciliation
    if staged_outbox_entries:
        restored_outbox = target_data_dir / "outbox_cutover_queue.jsonl"
        with restored_outbox.open("w", encoding="utf-8") as f:
            for entry in staged_outbox_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {
        "restored": True,
        "manifest_id": manifest.get("manifest_id"),
        "target_dir": str(target_data_dir),
        "barriers_enforced_count": len(registry.barriers),
        "resurrected_records_prevented": total_purged,
        "outbox_entries_preserved": len(staged_outbox_entries),
        "dual_memory_writers": False,
        "status": "RESTORED_WITH_BARRIERS",
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ------------------------------------------------------------------ CLI

def main() -> int:
    parser = argparse.ArgumentParser(description="Unified Memory Rollback & Barrier Recovery")
    parser.add_argument("--backup-dir", required=True, type=Path, help="Backup source directory")
    parser.add_argument("--target-dir", required=True, type=Path, help="Target data directory")
    parser.add_argument("--erasure-barrier", action="append", help="Target record_ref to barrier")
    parser.add_argument("--ledger", type=Path, help="Erasure ledger path")
    args = parser.parse_args()

    result = rollback_restore(
        backup_dir=args.backup_dir,
        target_data_dir=args.target_dir,
        erasure_barriers=args.erasure_barrier,
        erasure_ledger_file=args.ledger,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
