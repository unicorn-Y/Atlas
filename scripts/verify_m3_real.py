"""Real-world verification script for M3 session experience, review, and fact extraction.
Uses real Gemini 3.8 Flash model via ModelManager.
Environment: ATLAS_DATA_DIR=D:\\atlas-memory-8901-data
"""
from __future__ import annotations

import os
import sys
import json
import uuid
import asyncio
from pathlib import Path
from datetime import datetime, UTC

INTEGRATE_ROOT = Path("D:/atlas-mem-integrate")
sys.path.insert(0, str(INTEGRATE_ROOT / "core"))
os.environ["ATLAS_DATA_DIR"] = "D:\\atlas-memory-8901-data"

import atlas.memory.library.embed as emb
emb.embed_texts = lambda texts: None

from atlas.config import DATA_ROOT
from atlas.models import ModelManager
from atlas.engine.session_sync import append_session_message, read_session_all_messages
from atlas.memory.library import MemoryLibrary
from atlas.memory.library.store import Page
from atlas.memory.library.source_ref import SourceRef
from atlas.memory.library.sources import memory_open

async def test_m3_real():
    print("[M3-TEST] Initializing MemoryLibrary and ModelManager...")
    model_mgr = ModelManager()
    lib = MemoryLibrary(root=DATA_ROOT / "memory")
    lib.ready()
    engine_root = DATA_ROOT / "engine"
    engine_root.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------
    # Scenario 1: Rich work experience with tool errors, commands,
    # files, decisions, numbers, corrections, and unfinished items.
    # -------------------------------------------------------------
    conv_id = f"test-conv-m3-{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(UTC).isoformat()
    
    uids = []
    # User message 1: goal and context
    u1 = append_session_message(
        engine_root, conv_id, "user",
        "我想要重构核心调度模块。我目前居住在杭州，主要用 Python 开发后端服务。请检查 config/atlas.toml 和 core/atlas/kernel/loop.py。"
    )
    uids.append(u1)
    
    # Tool message: command and error
    u2 = append_session_message(
        engine_root, conv_id, "tool",
        "FileNotFoundError: [Errno 2] No such file or directory: 'config/atlas.toml'",
        metadata={"tool_name": "local_shell", "tool_call_id": "call_101", "is_error": True}
    )
    uids.append(u2)
    
    # User correction and decision
    u3 = append_session_message(
        engine_root, conv_id, "user",
        "刚才路径写错了，是 config/atlas.toml.example。我们决定增加环境变量降级支持，理由是避免配置缺失导致启动崩溃。"
        "同时把重试次数设为 3 次。还有剩余一个未完成项：待完善单元测试覆盖率。"
    )
    uids.append(u3)
    
    # Assistant response
    u4 = append_session_message(
        engine_root, conv_id, "assistant",
        "好的，已按决策增加环境变量降级，重试次数设为 3 次。未完成项已记录：单元测试覆盖率待补充。"
    )
    uids.append(u4)
    
    print(f"  Constructed rich conversation {conv_id} with {len(uids)} messages in SessionDB.")
    
    # Test 1A: Turn-end light extraction
    print("  Testing turn-end light extraction (diary & facts)...")
    row_turn = {
        "conversation_id": conv_id,
        "message_uids": [u1, u2],
        "event_kind": "turn_end",
        "occurred_at": now_iso,
        "scope": "turn"
    }
    res_turn = await lib.observe_turn(row_turn, model_mgr, datetime.now(UTC))
    print(f"  turn_end result: added={res_turn.added}, changed={res_turn.changed}, episode_written={res_turn.episode_written}")
    assert len(res_turn.added) > 0, "Facts should be added from user assertion"
    
    # Test 1B: Session-end / session_idle full episode extraction
    print("  Testing session_idle full episode extraction...")
    row_idle = {
        "conversation_id": conv_id,
        "message_uids": uids,
        "event_kind": "session_idle",
        "occurred_at": now_iso,
        "scope": "session"
    }
    res_idle = await lib.observe_turn(row_idle, model_mgr, datetime.now(UTC))
    print(f"  session_idle result: added={res_idle.added}, changed={res_idle.changed}, episode_written={res_idle.episode_written}")
    assert res_idle.episode_written, "Episode should have been written for session_idle"
    
    # Inspect written episode in MemoryStore (经历/{day}.md)
    day = datetime.now(UTC).date().isoformat()
    ep_page = lib.store.read(f"经历/{day}.md")
    ep_text = ep_page.render()
    print(f"  Episode page rendered size: {len(ep_text)} chars.")
    assert "重构" in ep_text or "调度" in ep_text or "Python" in ep_text
    
    # Verify entries in ep_page have source_refs and structured fields
    matched_entry = next((e for e in ep_page.current if e.session == conv_id), None)
    assert matched_entry is not None, f"Episode entry for {conv_id} must exist"
    print(f"  Episode entry text: {matched_entry.text[:100]}...")
    print(f"  Captured decisions: {matched_entry.decisions}")
    print(f"  Captured files: {matched_entry.files}")
    print(f"  Captured commands: {matched_entry.commands}")
    print(f"  Captured source_ref: {matched_entry.source_ref}")
    assert matched_entry.source_ref is not None, "Episode should have source_ref"
    
    # Check that source_refs can open SessionDB original
    opened = memory_open(SourceRef(conversation_id=conv_id, message_uid=u1), engine_root=engine_root)
    assert opened.get("ok") is True
    assert "杭州" in opened["messages"][0]["text"]
    print("  Good: Episode details preserved and source_ref opens exact SessionDB original.")
    
    # -------------------------------------------------------------
    # Scenario 2: Idempotence - Re-run with same source UIDs
    # -------------------------------------------------------------
    print("\n  Testing extraction idempotence...")
    len_before = len(lib.store.read(f"经历/{day}.md").render())
    res2 = await lib.observe_turn(row_idle, model_mgr, datetime.now(UTC))
    len_after = len(lib.store.read(f"经历/{day}.md").render())
    assert len_after == len_before, "Second run with identical source UIDs should not duplicate episode"
    print("  Good: Idempotent re-run did not append duplicate episode.")
    
    # -------------------------------------------------------------
    # Scenario 3: Casual chatter no-output
    # -------------------------------------------------------------
    print("\n  Testing casual greeting chatter no-output...")
    conv_chatter = f"test-conv-m3-chatter-{uuid.uuid4().hex[:8]}"
    c1 = append_session_message(engine_root, conv_chatter, "user", "你好啊！")
    c2 = append_session_message(engine_root, conv_chatter, "assistant", "你好！很高兴见到你，请问有什么我可以帮你的吗？")
    row_chatter = {
        "conversation_id": conv_chatter,
        "message_uids": [c1, c2],
        "event_kind": "session_idle",
        "occurred_at": datetime.now(UTC).isoformat(),
        "scope": "session"
    }
    res_chatter = await lib.observe_turn(row_chatter, model_mgr, datetime.now(UTC))
    print(f"  Chatter result: added={res_chatter.added}, episode_written={res_chatter.episode_written}")
    assert not res_chatter.episode_written or len(res_chatter.added) == 0
    print("  Good: Casual chatter handled properly (no spurious facts generated).")
    
    # -------------------------------------------------------------
    # Scenario 4: User manual edit preservation
    # -------------------------------------------------------------
    print("\n  Testing preservation of user manual edits...")
    manual_page_name = "test-manual-edit.md"
    page = Page.parse(
        manual_page_name,
        "# 手工编辑测试\n\n## 现在\n- 用户偏好：必须始终使用黑色主题 <!-- {\"src\":\"你改的\",\"id\":\"man-001\"} -->\n"
    )
    lib.store.write(page)
    lib.index.rebuild()
    read_back = lib.store.read(manual_page_name)
    assert "必须始终使用黑色主题" in read_back.render()
    entries = read_back.current
    assert any(e.id == "man-001" and "黑色主题" in e.text for e in entries)
    print("  Good: User manual edits preserved with src=你改的 after index rebuild.")
    
    print("\nALL M3 REAL-WORLD ACCEPTANCE TESTS PASSED!")
    return True

if __name__ == "__main__":
    asyncio.run(test_m3_real())
