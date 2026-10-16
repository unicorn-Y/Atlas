"""Real-world verification script for M1 lifecycle & queue acceptance.
Environment: ATLAS_DATA_DIR=D:\\atlas-memory-8901-data
"""
from __future__ import annotations

import os
import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, UTC, timedelta

# Ensure core is in sys.path
INTEGRATE_ROOT = Path("D:/atlas-mem-integrate")
sys.path.insert(0, str(INTEGRATE_ROOT / "core"))
os.environ["ATLAS_DATA_DIR"] = "D:\\atlas-memory-8901-data"

from atlas.memory.library.queue import TurnQueue
from atlas.memory.library import lifecycle
from atlas.engine.session_sync import read_session_all_messages
from atlas.memory.library.sources import memory_open
from atlas.memory.library.recall import recheck_memory
from atlas.config import DATA_ROOT

results = {}

def test_1_lifecycle_enqueue_and_provenance():
    print("[M1-T1] Testing lifecycle enqueue with real SessionDB message pointers...")
    # 1. Use append_session_message to insert into real SessionDB
    from atlas.engine.session_sync import append_session_message
    engine_root = DATA_ROOT / "engine"
    engine_root.mkdir(parents=True, exist_ok=True)
    conv_id = "test-conv-m1-lifecycle"
    
    msg_uid_1 = append_session_message(
        engine_root, conv_id, "user", "请帮我读取项目目录结构"
    )
    msg_uid_2 = append_session_message(
        engine_root, conv_id, "tool", "FileNotFoundError: [Errno 2] No such file",
        metadata={"tool_name": "local_file", "tool_call_id": "call_999", "is_error": True}
    )
    print(f"  Appended to SessionDB: msg1={msg_uid_1}, msg2={msg_uid_2}")
    now_iso = datetime.now(UTC).isoformat()

    # 2. Enqueue lifecycle event
    queue = TurnQueue(DATA_ROOT / "memory")
    event = {
        "conversation_id": conv_id,
        "message_uids": [msg_uid_1, msg_uid_2],
        "event_kind": "turn_end",
        "occurred_at": now_iso,
        "scope": "messages",
        "run_id": "run-m1-test",
        "tool_call_id": "call_999"
    }
    
    # Verify rejection if transcript content is passed
    bad_event = dict(event, content="Sneaked transcript")
    try:
        lifecycle.enqueue(queue, bad_event)
        raise AssertionError("Should have rejected content in event")
    except ValueError as e:
        print("  Good: rejected event with content:", e)

    # Valid enqueue
    row_id = lifecycle.enqueue(queue, event)
    print(f"  Enqueued lifecycle task row_id={row_id}")
    
    # 3. Read queue directly to confirm NO transcript bodies stored
    db = sqlite3.connect(queue.path)
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM pending WHERE id=?", (row_id,)).fetchone()
    assert row is not None
    assert row["user_text"] is None
    assert row["assistant_text"] is None
    assert json.loads(row["message_uids"]) == [msg_uid_1, msg_uid_2]
    assert row["conversation_id"] == conv_id
    db.close()
    print("  Good: Verified queue row holds only message UIDs and metadata, zero transcript body.")

    # 4. Open exact SessionDB source via memory_open / read_session_all_messages
    from atlas.memory.library.source_ref import SourceRef
    sref = SourceRef(conversation_id=conv_id, message_uid=msg_uid_2)
    opened = memory_open(sref, window=1, engine_root=engine_root)
    assert opened is not None and opened.get("ok") is True
    assert any("FileNotFoundError" in m["text"] for m in opened.get("messages", []))
    assert opened.get("conversation_id") == conv_id
    print("  Good: Exactly resolved message UID back to SessionDB transcript via memory_open.")
    return True

def test_2_idempotence_and_recovery():
    print("[M1-T2] Testing duplicate notification idempotence and restart recovery...")
    queue = TurnQueue(DATA_ROOT / "memory")
    now_iso = datetime.now(UTC).isoformat()
    event = {
        "conversation_id": "test-conv-m1-idempotence",
        "message_uids": ["u1", "u2"],
        "event_kind": "turn_end",
        "occurred_at": now_iso,
        "scope": "messages"
    }
    
    # Enqueue twice
    id1 = lifecycle.enqueue(queue, event)
    id2 = lifecycle.enqueue(queue, event)
    assert id1 == id2, f"Duplicate notification produced different IDs: {id1} vs {id2}"
    print(f"  Good: Duplicate notification idempotent (row id {id1} == {id2})")
    
    # Restart recovery via rebuild_uncovered_uids
    # Say u1 and u2 are in session, but only u1 is in processed_uids
    rebuilt_id = lifecycle.rebuild_uncovered_uids(
        queue,
        conversation_id="test-conv-m1-idempotence",
        message_uids=["u1", "u2", "u3"],
        processed_uids={"u1"}
    )
    assert rebuilt_id is not None
    print(f"  Good: Successfully rebuilt uncovered watermark task with row id: {rebuilt_id}")
    return True

def test_3_backoff_and_transient_retry():
    print("[M1-T3] Testing failure backoff and queue recovery...")
    queue = TurnQueue(DATA_ROOT / "memory")
    now_iso = datetime.now(UTC).isoformat()
    event = {
        "conversation_id": "test-conv-m1-retry",
        "message_uids": ["msg-fail-1"],
        "event_kind": "turn_end",
        "occurred_at": now_iso,
        "scope": "messages"
    }
    row_id = lifecycle.enqueue(queue, event)
    
    # Simulate first failure (e.g. model timeout)
    queue.fail(row_id, "ModelRateLimitError: 429 Too Many Requests")
    
    # Read row to verify attempts and backoff
    db = sqlite3.connect(queue.path)
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT attempts, last_error, next_attempt_at FROM pending WHERE id=?", (row_id,)).fetchone()
    assert row["attempts"] == 1
    assert "ModelRateLimitError" in row["last_error"]
    assert row["next_attempt_at"] is not None
    print(f"  Good: Task failed recorded: attempts={row['attempts']}, next_attempt_at={row['next_attempt_at']}")
    
    # Simulate eventual success: remove task
    queue.remove(row_id)
    rem = db.execute("SELECT id FROM pending WHERE id=?", (row_id,)).fetchone()
    assert rem is None
    db.close()
    print("  Good: Task removed after resolution.")
    return True

def test_4_repeated_tool_failure_recheck():
    print("[M1-T4] Testing repeated tool failure triggering M5 lexical recheck...")
    # Test recheck_memory directly with a realistic tool error
    error_sample = "FileNotFoundError: 'D:\\project\\config\\atlas.toml' not found"
    recheck_res = recheck_memory(error_sample, limit=3)
    assert isinstance(recheck_res, dict)
    assert "hits" in recheck_res
    assert "block" in recheck_res
    print(f"  Good: recheck_memory executed smoothly. Query='{recheck_res.get('query')}', hits count={len(recheck_res.get('hits', []))}")
    return True

if __name__ == "__main__":
    t1 = test_1_lifecycle_enqueue_and_provenance()
    t2 = test_2_idempotence_and_recovery()
    t3 = test_3_backoff_and_transient_retry()
    t4 = test_4_repeated_tool_failure_recheck()
    print(f"\nALL M1 REAL-WORLD TESTS PASSED: t1={t1}, t2={t2}, t3={t3}, t4={t4}")
