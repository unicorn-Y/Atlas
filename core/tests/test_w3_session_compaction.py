from __future__ import annotations

import os
import time

import pytest

from atlas.engine.kernel.context import ContextManager
from atlas.engine.session_sync import (
    append_session_message,
    begin_session_compaction,
    compact_session_messages,
    read_session_model_messages,
)
from atlas.engine.state.atlas_state import SessionDB
from atlas.engine.state.atlas_state_pidns import holder_namespace_token


pytestmark = pytest.mark.unit


def test_live_process_retains_expired_lease_and_release_admits_successor(tmp_path):
    owner = f"pid={os.getpid()}{holder_namespace_token()}:turn=owner"
    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.ensure_session("s", "api_server")
        assert db.try_acquire_session_turn_lease("s", owner)
        db._write_sql("UPDATE session_turn_leases SET expires_at = ?", (time.time() - 100_000,))
        assert not db.try_acquire_session_turn_lease("s", "contender")
        db.release_session_turn_lease("s", owner)
        assert db.try_acquire_session_turn_lease("s", "contender")


def test_model_projection_cache_survives_reopen_and_invalidates_on_update(tmp_path):
    append_session_message(tmp_path, "s", "user", "first")
    first = read_session_model_messages(tmp_path, "s")
    with SessionDB(db_path=tmp_path / "state.db") as db:
        assert db.read_projection_cache("s", "model_history", 1) == first
        revision = db.projection_revision("s")
        db._write_sql("UPDATE messages SET content = ? WHERE session_id = ?", ("updated", "s"))
        assert db.read_projection_cache("s", "model_history", 1) is None
        assert not db.write_projection_cache("s", "model_history", 1, revision, first)
    assert read_session_model_messages(tmp_path, "s")[0]["content"] == "updated"


def test_masked_tool_result_restores_metadata_after_reopen(tmp_path):
    manager = ContextManager(output_dir=tmp_path / "outputs")
    raw = "HEAD" + "x" * 12_000 + "TAIL"
    clip = manager.mask_persisted_tool_result(raw)
    append_session_message(tmp_path, "s", "assistant", "", {
        "tool_calls": [{"id": "c", "type": "function", "function": {"name": "local_file", "arguments": "{}"}}],
    })
    append_session_message(tmp_path, "s", "tool", clip.content, {
        "tool_call_id": "c", "tool_name": "local_file", "output_ref": clip.output_ref,
        "masked_content": True, "microcompacted": True,
    })
    result = read_session_model_messages(tmp_path, "s")[-1]
    assert result["content"] == clip.content
    assert result["microcompacted"] is True
    assert result["masked_content"] is True
    assert result["output_ref"] == clip.output_ref
    assert raw not in result["content"]


def test_compaction_bracket_and_rebuildable_summary_are_durable(tmp_path):
    append_session_message(tmp_path, "s", "user", "old request")
    held = read_session_model_messages(tmp_path, "s")
    holder = "test-compaction"
    watermark = begin_session_compaction(tmp_path, "s", holder)
    replacement = [{"role": "user", "content": "summary text", "_compressed_summary": True}]
    compact_session_messages(tmp_path, "s", holder, watermark, held, replacement,
                             snapshot_state={
                                 "plan": None, "todo": None, "open_tool_call_ids": [],
                                 "turn_context_projection": [], "turn_context_ref_index": [],
                             })
    with SessionDB(db_path=tmp_path / "state.db") as db:
        events = db.list_session_events("s")
    # Every message append now also lands in the log (E1/S1), so this asserts the
    # compaction bracket's own ordering rather than the log's total contents.
    compaction = [e for e in events if e["event_type"].startswith("compaction/")]
    assert [event["event_type"] for event in compaction] == [
        "compaction/start", "compaction/summary", "compaction/end",
    ]
    summary = compaction[1]["payload"]
    assert summary["shadowed_message_ids"]
    # shadowed_seqs covers every event the summary supersedes, which now includes
    # the message/append rows in addition to the compaction/start bracket itself.
    assert compaction[0]["seq"] in summary["shadowed_seqs"]
    assert summary["shadowed_seqs"] == sorted(summary["shadowed_seqs"])
    assert summary["messages"][0]["content"] == "summary text"
    assert summary["snapshot"]["state"] == {
        "plan": None, "todo": None, "open_tool_call_ids": [],
        "turn_context_projection": [], "turn_context_ref_index": [],
    }


def test_provider_model_compaction_policy_override():
    manager = ContextManager({"context_compaction": {"overrides": {
        "provider": {"threshold_ratio": 0.7},
        "provider/model": {"retain_ratio": 0.2},
    }}}, provider="provider", model="model")
    assert manager.compaction_policy == {"threshold_ratio": 0.7, "retain_ratio": 0.2}
    assert manager.thresholds(100_000).auto_compact == int(79_000 * 0.7)
    manager.configure_model(provider="other", model="other")
    assert manager.compaction_policy == {"threshold_ratio": 0.8, "retain_ratio": 0.16}


@pytest.mark.asyncio
async def test_retention_ratio_keeps_pairs_and_tail(tmp_path):
    manager = ContextManager({"context_compaction": {"retain_ratio": 0.16},
                              "max_output_tokens": 100, "context_buffer_tokens": 100}, output_dir=tmp_path)
    messages = [{"role": "user", "content": "old" * 200} for _ in range(12)]
    messages.append({"role": "user", "content": "latest"})

    async def summarize(history, prompt):
        return "Summary"

    result = await manager.prepare(messages, model_window=10_000, summarize=summarize, force=True)
    assert result.error is None
    assert result.messages[-1]["content"] == "latest"
    assert result.method == "summary"
