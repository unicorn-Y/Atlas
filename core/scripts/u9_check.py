"""Focused U9 regression checks for the implemented backend flows.

Run with ``ATLAS_ROOT`` pointing at an isolated Atlas data root.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from atlas.api.workspace_router import _pr_shape
from atlas.engine_core.agent.vault_store import VaultStore
from atlas.memory import MemoryStore
from atlas.projects import ProjectStore
from atlas.tools.x2.recording import Recorder, RecordingStore, to_skill_bundle


async def main() -> None:
    # PR result shaping preserves GitHub auto-merge state for the panel.
    assert _pr_shape({"number": 9, "autoMergeRequest": {"enabledAt": "now"}})["auto_merge"] is True

    with tempfile.TemporaryDirectory(prefix="atlas-u9-") as temp:
        root = Path(temp)
        # Browser credentials rotate in place; metadata stays visible and secret values do not.
        vault = VaultStore(root / "vault")
        item = vault.add_item("login", "QA login", {
            "identifier_type": "username", "identifier": "qa-user", "password": "old-value",
        }, origin="https://example.test")
        assert vault.rotate_login_password(item.id, "new-value")
        assert vault.resolve_secret(item.id)["password"] == "new-value"
        assert vault.get_meta(item.id).label == "QA login"

        # Project-only setting persists and source retrieval returns attributed project notes.
        projects = ProjectStore(root / "projects.db")
        await projects.init()
        project = await projects.create_project("U9 fixture")
        project = await projects.update_project(project.project_id, memory_scope="project-only")
        assert project and project.memory_scope == "project-only"
        await projects.add_source(project.project_id, "note", title="Fixture source", text="Deployment uses a local test gateway.")
        hits = await projects.search_sources(project.project_id, "test gateway")
        assert hits and hits[0]["title"] == "Fixture source"

        # Conversation memory preferences persist in metadata consumed by the run pipeline.
        memory = MemoryStore(root / "conversations.db")
        await memory.init()
        conversation_id = await memory.create_conversation("U9 memory fixture")
        assert await memory.update_conversation(conversation_id, metadata={"use_memories": False, "generate_memories": True})
        conversation = await memory.get_conversation(conversation_id)
        assert json.loads(conversation["metadata"]) == {"use_memories": False, "generate_memories": True}
        await memory.close()
        await projects.close()

        # Recorder output accepts a desktop action vocabulary and emits a reviewable skill bundle.
        store = RecordingStore(root / "recordings")
        doc = store.create("desktop://fixture")
        recorder = Recorder(doc, store)
        recorder.record("computer_click", {"x": 12, "y": 34, "window": "Fixture"})
        doc["status"] = "complete"
        store.save(doc)
        bundle = to_skill_bundle(doc, name="u9 desktop fixture")
        assert "computer_click" in bundle["skill_md"] and bundle["steps"]

    print("U9 backend scenarios passed (PR state, vault rotation, project-only policy, shared sources, conversation memory options, recorder export).")
    print("Note: desktop teaching UI remains outside this check; release hash verification is covered by u9c_check.py.")


if __name__ == "__main__":
    asyncio.run(main())
    print("U9 CHECK PASS")
