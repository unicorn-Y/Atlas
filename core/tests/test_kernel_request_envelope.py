import pytest

from atlas.engine.kernel.request_envelope import request_envelope, tool_pool_change_message


@pytest.mark.unit
def test_request_envelope_logs_a_stable_digest_without_message_content():
    envelope = request_envelope(
        [{"role": "user", "content": "private prompt"}],
        [{"function": {"name": "read_file", "parameters": {"type": "object"}}}],
    )

    assert envelope["message_count"] == 1
    assert envelope["roles"] == ["user"]
    assert envelope["tool_names"] == ["read_file"]
    assert envelope["request_sha256"]
    assert "private prompt" not in str(envelope)


@pytest.mark.unit
def test_tool_pool_change_message_lists_added_and_removed_tools():
    assert tool_pool_change_message({"read_file", "write_file"}, {"read_file", "search_files"}) == (
        "Tool availability changed. Added: search_files. Removed: write_file."
    )
    assert tool_pool_change_message({"read_file"}, {"read_file"}) is None
