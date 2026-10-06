"""Acceptance tests for T12.3 Cutover Dry-Run, Rollback & Barrier Recovery.

Criteria (02_wave_tasks.md T12.3 & 01_contracts.md §6, §8):
  - Required acceptance test:
      def test_failed_cutover_keeps_previous_consistent_version(h):
          h.seed("legacy"); h.fault("cutover_startup_failure", True)
          result = h.tool("fixture_cutover_dry_run", {})
          assert result["rolled_back"] and not result["dual_memory_writers"]
  - Cutover dry-run on copy of data produces read-only diff and consistent backup manifest.
  - Zero dual-memory writers (dual_memory_writers == False) via write pause & outbox queue.
  - Rollback preserves new data written post-cutover into outbox staging.
  - Rollback after HARD_ERASE applies erasure/retraction barriers BEFORE restoring DB/indices,
    never resurrecting erased records.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest

from scripts.unified_memory.cutover import (
    attach_lane_helpers,
    cutover_dry_run,
    generate_backup_manifest,
    generate_cutover_preview,
)
from scripts.unified_memory.rollback import (
    ErasureBarrierRegistry,
    apply_erasure_barriers_to_sqlite,
    rollback_restore,
    verify_backup_integrity,
)
from tests.unified_memory.harness import UMHarness


@pytest.fixture
def h(um: UMHarness) -> Any:
    attach_lane_helpers(um)
    return um


# ================================================================== Acceptance Test

@pytest.mark.integration
def test_failed_cutover_keeps_previous_consistent_version(h: Any):
    """T12.3 Acceptance criterion: startup failure rolls back cleanly with zero dual writers."""
    h.seed("legacy")
    h.fault("cutover_startup_failure", True)
    result = h.tool("fixture_cutover_dry_run", {})
    assert result["rolled_back"] and not result["dual_memory_writers"]


# ================================================================== Cutover Dry-Run Success Drill

@pytest.mark.integration
def test_cutover_dry_run_success_preview_and_manifest(h: Any):
    """Cutover dry run without faults produces consistent manifest, diff preview, and zero dual writers."""
    h.seed("legacy")
    h.fault("cutover_startup_failure", False)
    result = h.tool("fixture_cutover_dry_run", {})

    assert result["dry_run"] is True
    assert result["success"] is True
    assert result["rolled_back"] is False
    assert result["dual_memory_writers"] is False

    # Check preview diff
    preview = result.get("preview", {})
    assert preview.get("read_only") is True
    assert preview.get("destructive") is False

    # Check backup manifest
    manifest = result.get("backup_manifest", {})
    assert manifest.get("status") == "CONSISTENT"
    assert manifest.get("contract_version") == "UM-WIN-1.0"
    assert "watermarks" in manifest
    assert "files" in manifest
    for file_info in manifest["files"]:
        assert file_info["sha256"].startswith("sha256:")


# ================================================================== Post-Cutover New Data Preservation

@pytest.mark.unit
def test_post_cutover_new_data_preserved_on_rollback(tmp_path: Path):
    """New writes queued post-cutover are preserved in outbox queue across rollbacks."""
    source_dir = tmp_path / "data"
    source_dir.mkdir()
    db_file = source_dir / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT)")
    conn.execute("INSERT INTO memories VALUES ('m-001', '原始记忆')")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backup"
    manifest = generate_backup_manifest(source_dir, backup_dir)
    assert manifest["status"] == "CONSISTENT"

    # Simulate post-cutover write into outbox staging
    outbox_file = source_dir / "outbox_cutover_queue.jsonl"
    post_cutover_write = {
        "write_id": "post-write-001",
        "entry": {"text": "切换后新输入的内容，不可在回滚中丢失"},
    }
    outbox_file.write_text(json.dumps(post_cutover_write) + "\n", encoding="utf-8")

    # Perform rollback restore
    restore_result = rollback_restore(
        backup_dir=backup_dir,
        target_data_dir=source_dir,
        preserve_outbox=True,
    )
    assert restore_result["restored"] is True
    assert restore_result["outbox_entries_preserved"] == 1

    # Verify preserved outbox file still exists and contains the write
    assert outbox_file.exists()
    content = outbox_file.read_text(encoding="utf-8")
    assert "post-write-001" in content


# ================================================================== Post-Erasure Barrier Recovery

@pytest.mark.unit
def test_post_erasure_rollback_barrier_prevents_resurrection(tmp_path: Path):
    """Rollback after HARD_ERASE applies barriers BEFORE restoring DB so erased records never resurrect."""
    source_dir = tmp_path / "memory_store"
    source_dir.mkdir()
    db_path = source_dir / "memories.db"

    # 1. Initial database with active memory
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, record_ref TEXT, content TEXT)")
    conn.execute("INSERT INTO memories VALUES ('m-secret', 'memory:m-secret', '敏感用户隐私数据')")
    conn.execute("INSERT INTO memories VALUES ('m-normal', 'memory:m-normal', '正常用户记忆')")
    conn.commit()
    conn.close()

    # 2. Backup is generated containing the secret
    backup_dir = tmp_path / "backup"
    generate_backup_manifest(source_dir, backup_dir)

    # 3. User executes HARD_ERASE on the secret memory in active database
    ledger_path = tmp_path / "erasure_ledger.jsonl"
    registry = ErasureBarrierRegistry(ledger_path)
    registry.add_barrier("memory:m-secret", action="HARD_ERASE")

    # 4. Disaster recovery / Rollback is triggered
    restore_result = rollback_restore(
        backup_dir=backup_dir,
        target_data_dir=source_dir,
        erasure_ledger_file=ledger_path,
    )
    assert restore_result["restored"] is True
    assert restore_result["barriers_enforced_count"] >= 1
    assert restore_result["resurrected_records_prevented"] >= 1

    # 5. Verify restored database: secret memory is completely purged, normal memory preserved
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    secret_row = cursor.execute("SELECT * FROM memories WHERE id='m-secret' OR record_ref='memory:m-secret'").fetchone()
    normal_row = cursor.execute("SELECT * FROM memories WHERE id='m-normal'").fetchone()
    conn.close()

    assert secret_row is None, "HARD_ERASE memory was illegally resurrected after rollback!"
    assert normal_row is not None, "Normal memory should be safely restored"
