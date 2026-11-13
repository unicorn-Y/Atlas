import pytest
import asyncio

from atlas.api.app_services import AppServices
from atlas.api.conversations_router import (
    _explain_message_causality, _record_rewind_causality_event,
    explain_conversation_message,
)


@pytest.mark.unit
def test_explain_links_tool_result_to_turn_step_and_tool_call():
    rows = [
        {"_row_id": 1, "id": "user-1", "role": "user"},
        {"_row_id": 2, "id": "assistant-1", "role": "assistant",
         "tool_calls": [{"id": "call-1", "function": {"name": "read_file"}}],
         "display_metadata": {"kernel_run_id": "run-1"}},
        {"_row_id": 3, "id": "tool-1", "role": "tool", "tool_call_id": "call-1"},
    ]
    result = _explain_message_causality("2", rows, rows, rows, [])

    assert result is not None
    assert result["causality"]["turn"] == {
        "user_message_id": "1", "ordinal": 1, "basis": "ordered transcript",
    }
    assert result["causality"]["step"]["ordinal"] == 1
    assert result["causality"]["step"]["run_id"] == "run-1"
    assert result["causality"]["tool_results"] == [{
        "tool_call_id": "call-1", "tool_name": "read_file", "result_message_id": "3",
    }]


@pytest.mark.unit
def test_explain_distinguishes_compaction_shadowing_and_rewind_event():
    rows = [
        {"_row_id": 1, "id": "old", "role": "user"},
        {"_row_id": 2, "id": "rewound", "role": "assistant"},
        {"_row_id": 3, "id": "compacted", "role": "assistant"},
    ]
    display = [rows[0], rows[2]]
    model = [rows[0]]
    events = [{"seq": 9, "event_type": "session.rewind", "created_at": "now",
               "payload": {"rewind_id": "rewind-9", "message_ids": ["rewound"]}}]

    compacted = _explain_message_causality("3", rows, display, model, events)
    rewound = _explain_message_causality("2", rows, display, model, events)

    assert compacted is not None
    assert compacted["causality"]["compression"]["shadowed"] is True
    assert compacted["causality"]["rewind"]["inactive"] is False
    assert rewound is not None
    assert rewound["causality"]["compression"]["shadowed"] is False
    assert rewound["causality"]["rewind"]["inactive"] is True
    assert rewound["causality"]["rewind"]["event"]["seq"] == 9
    assert rewound["causality"]["rewind"]["specific_rewind"] == "rewind-9"


@pytest.mark.unit
def test_explain_returns_none_for_unknown_message():
    assert _explain_message_causality("missing", [], [], [], []) is None


@pytest.mark.unit
def test_explain_endpoint_reads_sessiondb_without_mutating_messages(tmp_path, monkeypatch):
    from atlas import config
    from atlas.engine.state.atlas_state import SessionDB

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "data")
    db_path = config.DATA_ROOT / "engine" / "state.db"
    with SessionDB(db_path=db_path) as db:
        db.create_session("explain-session", "test")
        db.append_message("explain-session", "user", content="question")
        db.append_message("explain-session", "assistant", content="answer")

    class Memory:
        async def get_conversation(self, conversation_id):
            return {"id": conversation_id}

    result = asyncio.run(explain_conversation_message(
        AppServices(memory=Memory()), "explain-session", message_id="2",
    ))
    asyncio.run(_record_rewind_causality_event(
        config.DATA_ROOT / "engine", "explain-session", rewind_id="rewind-test",
        mode="conversation", message_ids=["message-2"], boundary_message_id="message-1",
    ))

    assert result["message"]["role"] == "assistant"
    assert result["causality"]["turn"]["user_message_id"] == "1"
    assert result["causality"]["compression"]["shadowed"] is False
    with SessionDB(db_path=db_path) as db:
        assert db.message_count("explain-session") == 2
        event = db.list_session_events("explain-session")[0]
        assert event["event_type"] == "session.rewind"
        assert event["payload"]["rewind_id"] == "rewind-test"
