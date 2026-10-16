"""Real-world verification script for M4 sleep consolidation and overview generation.
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
from atlas.memory.library import MemoryLibrary
from atlas.memory.library.store import Entry, Page, THINGS, ME, NOW, SRC_SAID, SRC_EDITED, new_id
from atlas.memory.library.dream import run_dream

async def test_m4_real():
    print("[M4-TEST] Initializing MemoryLibrary and ModelManager...")
    model_mgr = ModelManager()
    lib = MemoryLibrary(root=DATA_ROOT / "memory")
    lib.ready()
    
    # -------------------------------------------------------------
    # Scenario 1: Cross-session episode consolidation for a project
    # -------------------------------------------------------------
    print("  Setting up multi-session project episodes for 'atlas-core'...")
    today = datetime.now(UTC).date().isoformat()
    ep_page = lib.store.read(f"经历/{today}.md")
    
    # Episode 1: Decisions and initial state
    ep1_id = new_id()
    ep1 = Entry(
        text="重构核心调度：完成接口定义并确认使用异步队列，确定重试次数为 3 次。",
        id=ep1_id,
        src="经历",
        session="session-m4-ep1",
        decisions=["使用异步队列", "重试次数设为 3 次"],
        files=["core/atlas/kernel/loop.py"],
        open_items=["在 2026-12-31 前补充核心调度压测"],
        extra_metadata={"extractor_version": "m3-1", "source_refs": [{"conversation_id": "session-m4-ep1", "message_uid": "msg-001"}]}
    )
    
    # Episode 2: Progress and updates
    ep2_id = new_id()
    ep2 = Entry(
        text="核心调度模块测试：已完成基础冒烟测试，发现超时边界情况需要进一步优化。",
        id=ep2_id,
        src="经历",
        session="session-m4-ep2",
        decisions=["超时限制设为 30 秒"],
        files=["core/atlas/kernel/timeout.py"],
        open_items=["在 2026-11-30 前修复超时处理边界"],
        extra_metadata={"extractor_version": "m3-1", "source_refs": [{"conversation_id": "session-m4-ep2", "message_uid": "msg-002"}]}
    )
    ep_page.current.extend([ep1, ep2])
    lib.store.write(ep_page)
    lib.store.commit("Add test episodes for M4")
    
    # Pre-seed a project file with user manual notes
    project_path = f"{THINGS}/atlas-core.md"
    lib.store.write(Page(
        path=project_path,
        title="atlas-core",
        notes=["- 用户手工记录：此模块是核心系统，不能引入外部重型依赖 <!-- src:你改的 | id:user-note-01 -->"]
    ))
    
    # -------------------------------------------------------------
    # Scenario 2: Candidate facts integration & claim resolution
    # -------------------------------------------------------------
    print("  Setting up M3 candidate facts in 我.md history...")
    me_page = lib.store.read(ME)
    # Existing claim in current
    existing_claim = Entry(
        text="居住在上海",
        id=new_id(),
        key="city",
        value="上海",
        src=SRC_SAID,
        source_level="user_assertion",
        recorded_at="2026-01-01T00:00:00Z"
    )
    # M3 candidate in history (newer user assertion claiming 杭州)
    candidate_claim = Entry(
        text="居住在杭州",
        id=new_id(),
        key="city",
        value="杭州",
        src="M3候选",
        why="待 M4 整合",
        source_level="user_assertion",
        recorded_at="2026-10-16T10:00:00Z",
        source_ref={"conversation_id": "session-m4-ep1", "message_uid": "msg-001"}
    )
    me_page.current = [existing_claim]
    me_page.history = [candidate_claim]
    lib.store.write(me_page)
    
    # -------------------------------------------------------------
    # Scenario 3: Overview user block protection
    # -------------------------------------------------------------
    print("  Pre-seeding 总览.md with protected user section...")
    overview_text = (
        "# 记忆总览\n\n"
        "<!-- user:start -->\n"
        "## 我的重要须知\n"
        "- 保持谨慎，绝不执行未经确认的 rm 操作。\n"
        "<!-- user:end -->\n\n"
        "## 关于你\n"
        "- 默认内容\n"
    )
    (lib.store.root / "总览.md").write_text(overview_text, encoding="utf-8")
    
    # -------------------------------------------------------------
    # Execution: Run real dream consolidation
    # -------------------------------------------------------------
    print("  Running run_dream with real model consolidation...")
    res = await run_dream(lib, model_mgr)
    print(f"  run_dream returned: ok={res['ok']}, projects={res['projects']}, error={res['error']}")
    assert res["ok"] is True, f"run_dream failed: {res['error']}"
    
    # -------------------------------------------------------------
    # Verifications
    # -------------------------------------------------------------
    # 1. Check candidate facts resolved via M7
    me_after = lib.store.read(ME)
    current_values = [e.value for e in me_after.current]
    print(f"  Current claims in 我.md: {current_values}")
    assert "杭州" in current_values, "Newer user assertion (杭州) should win and move to current"
    
    # 2. Check user section preservation in 总览.md
    overview_after = (lib.store.root / "总览.md").read_text(encoding="utf-8")
    print(f"  总览.md size: {len(overview_after)} chars")
    assert "保持谨慎，绝不执行未经确认的 rm 操作" in overview_after, "User block in 总览.md must be preserved"
    assert "<!-- user:start -->" in overview_after and "<!-- user:end -->" in overview_after
    
    # 3. Check user notes in project page preserved
    proj_after = lib.store.read(project_path)
    rendered_proj = proj_after.render()
    assert "此模块是核心系统，不能引入外部重型依赖" in rendered_proj, "User notes in project page must be preserved"
    
    # 4. Check git commit was generated
    assert res["log"].get("commit") not in ("git_unavailable", "no_changes"), "Real git commit should be produced"
    print(f"  Consolidation git commit: {res['log'].get('commit')}")
    
    # 5. Check index rebuild status
    assert res["log"].get("index_rebuild") == "ok", "Index rebuild should be ok"
    
    print("\nALL M4 REAL-WORLD ACCEPTANCE TESTS PASSED!")
    return True

if __name__ == "__main__":
    asyncio.run(test_m4_real())
