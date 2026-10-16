"""Real-world verification script for M5 layered recall, search, source opening and index rebuild.
Environment: ATLAS_DATA_DIR=D:\\atlas-memory-8901-data
"""
from __future__ import annotations

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, UTC

INTEGRATE_ROOT = Path("D:/atlas-mem-integrate")
sys.path.insert(0, str(INTEGRATE_ROOT / "core"))
os.environ["ATLAS_DATA_DIR"] = "D:\\atlas-memory-8901-data"

import atlas.memory.library.embed as emb
emb.embed_texts = lambda texts: None

from atlas.config import DATA_ROOT
from atlas.engine.session_sync import append_session_message
from atlas.memory.library import MemoryLibrary
from atlas.memory.library.source_ref import SourceRef
from atlas.memory.library.sources import memory_open, search_raw
from atlas.memory.library.recall import recheck_memory

def test_m5_real():
    print("[M5-TEST] Initializing MemoryLibrary...")
    lib = MemoryLibrary(root=DATA_ROOT / "memory")
    lib.ready()
    engine_root = DATA_ROOT / "engine"
    
    # -------------------------------------------------------------
    # 1. Resident overview block (_resident_block)
    # -------------------------------------------------------------
    print("  Testing _resident_block loading M4's 总览.md...")
    block = lib._resident_block()
    print(f"  _resident_block output length: {len(block)} chars.")
    assert len(block) > 0, "Resident block should not be empty"
    assert "保持谨慎" in block or "关于你" in block or "总览" in block
    print("  Good: _resident_block successfully loads overview.")
    
    # -------------------------------------------------------------
    # 2. Layered search & claim filtering (M7 is_current_claim)
    # -------------------------------------------------------------
    print("\n  Testing layered search with claim currentness...")
    hits = lib.search("居住", limit=5)
    print(f"  Search for '居住': {len(hits)} hits.")
    assert len(hits) > 0, "Should find claim for '居住'"
    top_hit = hits[0]
    print(f"  Top hit text: {top_hit['text']}")
    print(f"  Top hit rank_reasons: {top_hit.get('rank_reasons')}")
    print(f"  Top hit claim_current: {top_hit.get('claim_current')}")
    assert "杭州" in top_hit["text"], "Top hit should be the current claim '杭州', not old '上海'"
    
    # -------------------------------------------------------------
    # 3. search_raw and memory_open
    # -------------------------------------------------------------
    print("\n  Testing search_raw bounded excerpt and memory_open...")
    test_conv = "conv-m5-search-raw"
    msg_uid = append_session_message(
        engine_root, test_conv, "user",
        "在集群环境下我们排查了致命错误：Deadlock detected on resource lock_worker_queue_01. 建议降低并发度到 4。"
    )
    
    raw_hits = search_raw("Deadlock detected", limit=3)
    print(f"  search_raw hits: {len(raw_hits)}")
    assert len(raw_hits) > 0, "search_raw should find the deadlock message"
    first_raw = raw_hits[0]
    print(f"  Snippet: {first_raw['snippet']}")
    assert len(first_raw["snippet"]) <= 320, "search_raw snippet must be <= 320 chars"
    assert "content" not in first_raw and "messages" not in first_raw, "search_raw must not return full body"
    
    # Open through memory_open
    ref_obj = SourceRef(conversation_id=test_conv, message_uid=msg_uid)
    opened = memory_open(ref_obj, engine_root=engine_root)
    assert opened.get("ok") is True, f"memory_open failed: {opened}"
    assert "Deadlock detected" in opened["messages"][0]["text"]
    print("  Good: search_raw is bounded and memory_open returns exact transcript.")
    
    # -------------------------------------------------------------
    # 4. Tool error lexical recheck (recheck_memory)
    # -------------------------------------------------------------
    print("\n  Testing recheck_memory for tool failure hook...")
    recheck_res = recheck_memory("FileNotFoundError config/atlas.toml", library=lib, limit=3)
    print(f"  recheck_memory query: {recheck_res.get('query')}")
    print(f"  recheck_memory hits: {len(recheck_res.get('hits', []))}")
    assert len(recheck_res.get("hits", [])) > 0, "recheck_memory should hit related files or error episodes"
    print("  Good: recheck_memory returns relevant context for tool error.")
    
    # -------------------------------------------------------------
    # 5. Index rebuild durability
    # -------------------------------------------------------------
    print("\n  Testing index wipe and rebuild from Markdown...")
    lib.index.rebuild()
    hits_after = lib.search("杭州", limit=3)
    assert len(hits_after) > 0, "Search should work seamlessly after index rebuild"
    print("  Good: Rebuilt index successfully from authoritative Markdown.")
    
    print("\nALL M5 REAL-WORLD ACCEPTANCE TESTS PASSED!")
    return True

if __name__ == "__main__":
    test_m5_real()
