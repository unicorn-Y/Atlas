from __future__ import annotations

import hashlib

import pytest

from atlas.engine.kernel.context import ContextManager


@pytest.mark.unit
def test_tool_result_pruning_uses_threshold_head_tail_mask_and_replays(tmp_path):
    content = "H" * 4096 + "M" * 5000 + "T" * 1024
    history = [
        {"role": "assistant", "tool_calls": [{"id": "call-1", "name": "Read"}]},
        {"role": "tool", "tool_call_id": "call-1", "name": "Read", "content": content},
        {"role": "assistant", "tool_calls": [{"id": "call-2", "name": "Read"}]},
        {"role": "tool", "tool_call_id": "call-2", "name": "Read", "content": "recent"},
    ]
    manager = ContextManager({"microcompact": {"enabled": True, "keep_recent_tool_results": 0,
                                                "min_token_savings": 1}}, output_dir=tmp_path)

    compacted = manager.microcompact(history, budget_tokens=0)
    result = compacted[1]

    assert result["microcompacted"] is True
    assert result["masked_content"] is True
    assert result["content"].startswith("H" * 4096)
    assert result["content"].endswith("T" * 1024)
    assert "Old tool output masked" in result["content"]
    assert result["output_ref"] == str((tmp_path / f"{hashlib.sha256(content.encode()).hexdigest()}.txt").resolve())
    assert (tmp_path / f"{hashlib.sha256(content.encode()).hexdigest()}.txt").read_text() == content
    assert history[1]["content"] == content  # caller's transcript is untouched

    replayed = manager.microcompact(compacted, budget_tokens=0)
    assert replayed == compacted


@pytest.mark.unit
def test_tool_result_pruning_waits_until_8192_character_threshold(tmp_path):
    manager = ContextManager({"microcompact": {"enabled": True, "keep_recent_tool_results": 0,
                                                "min_token_savings": 1}}, output_dir=tmp_path)

    def history(length):
        return [
            {"role": "assistant", "tool_calls": [{"id": "call-1", "name": "Read"}]},
            {"role": "tool", "tool_call_id": "call-1", "name": "Read", "content": "x" * length},
            {"role": "assistant", "tool_calls": [{"id": "call-2", "name": "Read"}]},
            {"role": "tool", "tool_call_id": "call-2", "name": "Read", "content": "recent"},
        ]

    assert manager.microcompact(history(8192), budget_tokens=0)[1]["content"] == "x" * 8192
    assert manager.microcompact(history(8193), budget_tokens=0)[1]["microcompacted"] is True
