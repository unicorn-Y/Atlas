from __future__ import annotations

import json
from datetime import datetime

import pytest

from atlas.memory.library.consolidation import text_hash, validate_plan
from atlas.memory.library.dream import _apply_project_plan
from atlas.memory.library.store import SRC_DREAM, Entry


def test_validate_plan_requires_known_sources_and_exact_schema():
    plan = [{
        "action": "add", "target_id": "", "old_text_hash": "",
        "source_refs": ["episode-1"],
        "fields": {"section": "现在状态", "text": "接口已完成"},
        "reason": "经历提到多次验证",
    }]
    assert validate_plan(json.dumps({"actions": plan}, ensure_ascii=False), {"episode-1"}) == plan
    plan[0]["source_refs"] = ["invented"]
    with pytest.raises(ValueError, match="unknown source reference"):
        validate_plan(json.dumps({"actions": plan}, ensure_ascii=False), {"episode-1"})


def test_project_plan_skips_stale_edit_and_keeps_current_markdown():
    original = Entry(id="claim-1", text="旧摘要文本", src=SRC_DREAM).line()
    episodes = [Entry(id="episode-1", text="完成项目", src="经历")]
    actions = [
        {"action": "update", "target_id": "claim-1", "old_text_hash": text_hash("旧文本"),
         "source_refs": ["episode-1"],
         "fields": {"section": "现在状态", "text": "模型改写"}, "reason": "摘要"},
    ]
    rendered, report = _apply_project_plan("Atlas", actions, f"# Atlas\n\n## 现在状态\n{original}\n",
                                           episodes, datetime.now().astimezone())
    assert "旧摘要文本" in rendered
    assert "模型改写" not in rendered
    assert report["applied"] == []


def test_project_plan_rejects_changes_to_user_owned_summary_entries():
    original = Entry(id="user-1", text="保留用户原文", src="你改的").line()
    action = {"action": "update", "target_id": "user-1", "old_text_hash": text_hash("保留用户原文"),
              "source_refs": ["episode-1"],
              "fields": {"section": "现在状态", "text": "模型替换"}, "reason": "摘要"}
    with pytest.raises(ValueError, match="user-owned"):
        _apply_project_plan("Atlas", [action], f"# Atlas\n\n## 现在状态\n{original}\n",
                            [Entry(id="episode-1", text="经历")], datetime.now().astimezone())
