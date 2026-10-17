import asyncio
from types import SimpleNamespace

from atlas.api import conversations_router
from atlas.api.app_services import AppServices
from atlas.api.conversations_router import HandoffRequest
from atlas.api.handoff_metadata import (
    delete_handoff_metadata,
    load_handoff_metadata,
    save_handoff_metadata,
)


def test_handoff_metadata_round_trips_and_deletes(tmp_path):
    path = tmp_path / "engine" / "handoff_metadata.sqlite3"
    save_handoff_metadata(path, "child-1", "parent-1", "Finish the implementation")
    assert load_handoff_metadata(path, ["child-1", "other"]) == {
        "child-1": {"handoff_from": "parent-1", "handoff_goal": "Finish the implementation"},
    }
    save_handoff_metadata(path, "child-1", "parent-2", "Verify the change")
    assert load_handoff_metadata(path, ["child-1"]) == {
        "child-1": {"handoff_from": "parent-2", "handoff_goal": "Verify the change"},
    }
    delete_handoff_metadata(path, "child-1")
    assert load_handoff_metadata(path, ["child-1"]) == {}


def test_handoff_endpoint_creates_linked_draft_without_sending(monkeypatch, tmp_path):
    class Memory:
        async def get_conversation(self, conversation_id):
            return {"id": conversation_id, "title": "Parent work"}

        async def fork_conversation_metadata(self, conversation_id, *, title):
            assert conversation_id == "parent-1"
            assert title == "接力：Finish verification"
            return {"id": "child-1", "title": title, "parent_conversation_id": conversation_id}

    class ModelRouter:
        async def resolve(self, model, purpose):
            assert model == "model-a"
            assert purpose == "handoff_summary"
            return "route"

        async def complete(self, route, **kwargs):
            assert "user: retain the API contract" in kwargs["messages"][1]["content"]
            return SimpleNamespace(text="Context: API contract\nTask: Finish verification")

    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    monkeypatch.setattr(
        "atlas.engine.session_sync.read_session_all_messages",
        lambda root, conversation_id: [{"role": "user", "content": "retain the API contract"}],
    )
    services = AppServices(
        memory=Memory(),
        model_mgr=SimpleNamespace(current_model="model-a", model_router=ModelRouter()),
    )

    result = asyncio.run(conversations_router.handoff_conversation(
        services, "parent-1", HandoffRequest(goal="Finish verification"),
    ))

    assert result["parent_title"] == "Parent work"
    assert result["conversation"]["parent_conversation_id"] == "parent-1"
    assert result["conversation"]["handoff_from"] == "parent-1"
    assert result["conversation"]["handoff_goal"] == "Finish verification"
    assert result["prompt_draft"].startswith("Context:")
    assert load_handoff_metadata(tmp_path / "engine" / "handoff_metadata.sqlite3", ["child-1"])
