"""Focused persistence and snapshot recovery probe for W1-6/W1-7.

Run from the repository root with:
    uv run --project core python core/scripts/w1_session_probe.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from atlas.engine.session_sync import (
    append_session_messages,
    append_user_message_before_model,
    begin_session_compaction,
    compact_session_messages,
    read_session_model_messages,
    restore_session_snapshot,
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-w1-session-") as temp:
        home = Path(temp)
        session_id = "w1-session-probe"
        user_id = append_user_message_before_model(
            home, session_id, "Remember the recovery marker: blue-otter-47",
            {"kernel_run_id": "probe-turn-1"},
        )
        assert user_id
        event_ids = append_session_messages(home, session_id, [
            {
                "role": "assistant", "content": "",
                "tool_calls": [{"id": "call-probe-1", "type": "function",
                                "function": {"name": "probe", "arguments": "{}"}}],
                "finish_reason": "tool_calls",
            },
            {"role": "tool", "content": "tool result persisted", "tool_call_id": "call-probe-1",
             "tool_name": "probe"},
            {"role": "assistant", "content": "The marker is blue-otter-47."},
        ])
        assert len(event_ids) == 3 and all(event_ids)

        restored = read_session_model_messages(home, session_id)
        assert [item["role"] for item in restored] == ["user", "assistant", "tool", "assistant"]
        assert "blue-otter-47" in restored[0]["content"]
        assert restored[1]["tool_calls"][0]["id"] == "call-probe-1"
        assert restored[2]["tool_call_id"] == "call-probe-1"
        assert restored[2]["content"] == "tool result persisted"
        print("W1-6 ordered transcript: PASS (user, tool call, result, assistant restored)")

        compact_session_id = "w1-snapshot-probe"
        append_session_messages(home, compact_session_id, [
            {"role": "user", "content": "Earlier task: calculate the release checksum."},
            {"role": "assistant", "content": "I will preserve the task and its result."},
            {"role": "user", "content": "Continue with the release note."},
            {"role": "assistant", "content": "The release checksum is 7f3a."},
        ])
        held = read_session_model_messages(home, compact_session_id)
        holder = "w1-probe-compaction"
        watermark = begin_session_compaction(home, compact_session_id, holder)
        summary = {
            "role": "user",
            "content": "[Conversation continuation summary]\nPreserve checksum 7f3a and write the release note.",
            "_compressed_summary": True,
        }
        compact_session_messages(
            home, compact_session_id, holder, watermark, held, [summary],
            snapshot_state={"plan": {"step": "release note"}, "pending_tool_call_ids": []},
        )
        recovered = restore_session_snapshot(home, compact_session_id)
        assert recovered is not None and not recovered["legacy"]
        assert recovered["snapshot"]["boundary_watermark"] == watermark
        assert recovered["snapshot"]["state"]["plan"]["step"] == "release note"
        assert len(recovered["messages"]) == 1
        assert "7f3a" in recovered["messages"][0]["content"]
        print("W1-7 summary snapshot: PASS (boundary, state, and resumable summary restored)")


if __name__ == "__main__":
    main()
