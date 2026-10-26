from atlas.api.automation_router import _delete_impact
from atlas.automation import inbox


def test_delete_impact_lists_run_keys_and_configured_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "_PATH", tmp_path / "automation-inbox.sqlite3")
    record = {
        "id": "automation-a", "name": "Research digest",
        "payload": {"kind": "agent_turn", "conversation_id": "configured-chat"},
    }
    for run_key, conversation_id in (("run-1", "chat-1"), ("run-2", "chat-1"), ("run-3", "chat-2")):
        inbox.record_run(record, {
            "run_id": run_key, "status": "ok", "conversation_id": conversation_id,
            "started_at": "2026-10-25T12:00:00Z", "finished_at": "2026-10-25T12:01:00Z",
        })

    impact = _delete_impact("automation-a", record)
    by_id = {item["id"]: item for item in impact["conversations"]}
    assert impact["run_count"] == 3
    assert impact["automation_name"] == "Research digest"
    assert by_id["chat-1"]["run_count"] == 2
    assert set(by_id["chat-1"]["runs"]) == {"run-1", "run-2"}
    assert by_id["chat-2"]["runs"] == ["run-3"]
    assert by_id["configured-chat"]["configured"] is True
