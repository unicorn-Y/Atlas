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
    read_session_model_messages,
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


if __name__ == "__main__":
    main()
