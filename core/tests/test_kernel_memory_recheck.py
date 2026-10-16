from __future__ import annotations

from atlas.engine.session_sync import append_session_message, read_session_all_messages
from atlas.kernel.loop import _tool_result_context_messages


def test_memory_recheck_is_separate_from_canonical_tool_output(tmp_path):
    conversation_id = "memory-recheck-source-role"
    raw_error = "tool failed: file not found"
    memory_block = "Relevant memory: the file is generated under build/output.txt."

    model_messages = _tool_result_context_messages(
        "call-1", "local_shell", raw_error, memory_block,
    )
    assert model_messages[0] == {
        "role": "tool", "tool_call_id": "call-1", "name": "local_shell",
        "content": raw_error,
    }
    assert len(model_messages) == 2
    assert model_messages[1]["role"] == "system"
    assert "source=memory_library" in model_messages[1]["content"]
    assert "this is not tool output" in model_messages[1]["content"]
    assert memory_block in model_messages[1]["content"]

    uid = append_session_message(tmp_path / "engine", conversation_id, "tool", raw_error, {
        "tool_call_id": "call-1", "tool_name": "local_shell",
    })
    [persisted] = [row for row in read_session_all_messages(
        tmp_path / "engine", conversation_id,
    ) if row["id"] == uid]
    assert persisted["role"] == "tool"
    assert persisted["content"] == raw_error
    assert memory_block not in persisted["content"]
