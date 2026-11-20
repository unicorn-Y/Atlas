"""ProjectStore coverage for the long-lived personal agent wave."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.projects import ProjectStore
from tests.fakes.session_store import save_memory_fixture_message


@pytest.fixture
async def store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects.db")
    await store.init()
    yield store
    await store.close()


async def test_create_get_and_duplicate_name(store: ProjectStore) -> None:
    project = await store.create_project(
        "Atlas", workspace_path="D:/Atlas", current_goal="become a real agent",
    )
    assert project.name == "Atlas"
    assert project.status == "active"
    assert project.current_goal == "become a real agent"

    fetched = await store.get(project.project_id)
    assert fetched is not None and fetched.name == "Atlas"
    assert await store.get_by_name("atlas") is not None

    with pytest.raises(ValueError, match="already exists"):
        await store.create_project("Atlas")


async def test_update_goal_state_and_status_transitions(store: ProjectStore) -> None:
    project = await store.create_project("Voice")
    updated = await store.update_project(
        project.project_id,
        current_goal="ship realtime voice",
        current_state="pipeline designed; pipecat pending",
    )
    assert updated is not None
    assert updated.current_goal == "ship realtime voice"
    assert "pipecat" in updated.current_state

    with pytest.raises(ValueError, match="invalid project status"):
        await store.update_project(project.project_id, status="bogus")

    archived = await store.archive(project.project_id)
    assert archived is not None and archived.status == "archived"
    active = await store.list_projects(status="active")
    assert all(p.project_id != project.project_id for p in active)


async def test_conversation_association_and_detach(store: ProjectStore) -> None:
    project = await store.create_project("Atlas")
    await store.attach_conversation(project.project_id, "conv-1")
    await store.attach_conversation(project.project_id, "conv-2")
    await store.attach_conversation(project.project_id, "conv-1")  # idempotent

    assert await store.list_conversations(project.project_id) == ["conv-1", "conv-2"]

    with pytest.raises(ValueError, match="unknown project"):
        await store.attach_conversation("missing", "conv-1")

    assert await store.detach_conversation(project.project_id, "conv-1") is True
    assert await store.detach_conversation(project.project_id, "conv-1") is False
    assert await store.list_conversations(project.project_id) == ["conv-2"]


async def test_delete_project_removes_associations(store: ProjectStore) -> None:
    project = await store.create_project("Temp")
    await store.attach_conversation(project.project_id, "conv-9")
    assert await store.delete_project(project.project_id) is True
    assert await store.get(project.project_id) is None
    assert await store.list_conversations(project.project_id) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_local_file_dispatch_refreshes_project_instruction_scope(
    tmp_path: Path, monkeypatch,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from langchain_core.messages import AIMessage, ToolMessage

    from atlas.agent import AgentOrchestrator, AgentRunContext
    from atlas.agent.project_instructions import (
        load_project_instructions, project_instruction_root, snapshot_project_instructions,
    )
    from atlas.tools.local_execution import LocalExecutionRuntime

    class FixtureConfig(dict):
        def __init__(self, db_path: Path):
            super().__init__({"agent.verify_before_stop": False})
            self.db_path = db_path
            self.local_execution_permission_mode = "full_access"
            self.trajectory_reviewer_enabled = False
            self.trajectory_reviewer_backend = ""
            self.trajectory_reviewer_model = ""

    workspace = tmp_path / "repo"
    nested = workspace / "src"
    nested.mkdir(parents=True)
    (workspace / ".git").mkdir()
    (workspace / "AGENTS.md").write_text("ROOT_RULE", encoding="utf-8")
    rule_path = nested / "AGENTS.md"
    rule_path.write_text("SUBDIR_RULE_V1", encoding="utf-8")
    target = nested / "readme.txt"
    target.write_text("read fixture", encoding="utf-8")
    config = FixtureConfig(tmp_path / "atlas.db")
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    monkeypatch.setattr("atlas.tools.local_execution.get_config", lambda: config)

    local = LocalExecutionRuntime()
    agent = AgentOrchestrator(
        SimpleNamespace(current_model="fixture", current_litellm_model="fixture"),
        MagicMock(), local_execution=local,
        trajectory_reviewer=SimpleNamespace(reviewer=None),
    )
    project_root = project_instruction_root(workspace)
    context = AgentRunContext(
        run_id="project-instructions-run", conversation_id="project-instructions-conv",
        workspace=str(workspace), workspace_trusted=True, permission_mode="full_access",
        allowed_paths=[str(workspace)], tool_allow=["local_file"],
        project_instruction_root=str(project_root),
        project_instruction_snapshot=snapshot_project_instructions(
            load_project_instructions(workspace, trusted=True),
        ),
    )

    async def read_target(path: Path = target):
        return await agent._execute_tools_node({
            "messages": [AIMessage(content="", tool_calls=[{
                "name": "local_file", "args": {"action": "read", "path": str(path)},
                "id": "project-rule-read", "type": "tool_call",
            }])],
            "pending_events": [], "tool_rounds": 0, "cancelled": False,
            "runtime": context,
        })

    try:
        before_failed_read = dict(context.project_instruction_snapshot)
        failed_read = await read_target(nested / "missing.txt")
        failed_event = next(event for event in failed_read["pending_events"]
                            if event["type"] == "tool_result")
        assert failed_event["is_error"] is True
        assert "project_instruction_updates" not in (failed_event.get("data") or {})
        assert context.project_instruction_snapshot == before_failed_read

        added = await read_target()
        assert isinstance(added["messages"][0], ToolMessage)
        assert "SUBDIR_RULE_V1" in added["messages"][0].content
        added_event = next(event for event in added["pending_events"]
                           if event["type"] == "tool_result")
        first_update = added_event["data"]["project_instruction_updates"][0]
        assert first_update["state"] == "added"
        assert first_update["path"] == str(rule_path)
        first_change_id = first_update["change_id"]

        rule_path.write_text("SUBDIR_RULE_V2", encoding="utf-8")
        changed = await read_target()
        assert "SUBDIR_RULE_V2" in changed["messages"][0].content
        changed_event = next(event for event in changed["pending_events"]
                             if event["type"] == "tool_result")
        second_update = changed_event["data"]["project_instruction_updates"][0]
        assert second_update["state"] == "changed"
        assert second_update["revision"] != first_update["revision"]
        assert second_update["change_id"] != first_change_id

        rule_path.unlink()
        removed = await read_target()
        assert "state=removed" in removed["messages"][0].content
        removed_event = next(event for event in removed["pending_events"]
                             if event["type"] == "tool_result")
        assert removed_event["data"]["project_instruction_updates"][0]["state"] == "removed"
        assert str(rule_path.resolve()).casefold() not in context.project_instruction_snapshot
    finally:
        await local.shutdown()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_child_directory_instruction_update_reaches_next_kernel_model_request(
    tmp_path: Path, monkeypatch,
) -> None:
    import json
    from unittest.mock import MagicMock

    from atlas.agent import AgentOrchestrator, AgentRunContext
    from atlas.engine.atlas_runtime import AtlasRuntime
    from atlas.tools.local_execution import LocalExecutionRuntime
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_atlas_home
    from tests.test_engine_model_wiring import _ProviderKeyManager

    workspace = tmp_path / "repo"
    nested = workspace / "src"
    nested.mkdir(parents=True)
    (workspace / ".git").mkdir()
    (workspace / "AGENTS.md").write_text("ROOT_RULE_FOR_MODEL", encoding="utf-8")
    (nested / "AGENTS.md").write_text("NESTED_RULE_FOR_NEXT_STEP", encoding="utf-8")
    target = nested / "readme.txt"
    target.write_text("target text", encoding="utf-8")

    with FakeLLMServer([
        ToolCall("local_file", {"action": "read", "path": str(target)}),
        ToolCall("local_file", {"action": "read", "path": str(nested / "AGENTS.md")}),
        ToolCall("local_file", {
            "action": "write", "path": str(nested / "AGENTS.md"),
            "content": "NESTED_RULE_V2_FOR_NEXT_STEP",
        }),
        ToolCall("local_file", {"action": "delete", "path": str(nested / "AGENTS.md")}),
        Text("read and update complete"),
    ]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        manager = _ProviderKeyManager(fake.base_url, current="main-model")
        manager._find_model = lambda model: next(
            (item for item in manager.list_models() if item["id"] == model), None,
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        memory = MemoryStore(db_path=tmp_path / "kernel-project-instructions.sqlite3")
        await memory.init()
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(manager, memory, mcp_client=mcp, local_execution=local)
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        context = AgentRunContext(
            run_id="kernel-project-rules", conversation_id="kernel-project-rules",
            workspace=str(workspace), workspace_trusted=True,
            permission_mode="full_access", allowed_paths=[str(workspace)],
            tool_allow=["local_file"],
        )
        try:
            events = [event async for event in runtime.run_turn(
                message="Read src/readme.txt and continue with its folder instructions.",
                user_content="Read src/readme.txt and continue with its folder instructions.",
                conversation_id="kernel-project-rules", workspace=str(workspace), history=[],
                atlas_agent=agent, atlas_context=context, ephemeral=True,
            )]
            requests = fake.main_requests()
            assert len(requests) == 5
            first_prompt = json.dumps(requests[0]["messages"], ensure_ascii=False)
            assert "ROOT_RULE_FOR_MODEL" in first_prompt
            assert "NESTED_RULE_FOR_NEXT_STEP" not in first_prompt
            def last_tool_output(index: int) -> str:
                tool_messages = [item for item in requests[index]["messages"]
                                 if isinstance(item, dict) and item.get("role") == "tool"]
                assert tool_messages
                return str(tool_messages[-1].get("content", ""))

            added = last_tool_output(1)
            assert "NESTED_RULE_FOR_NEXT_STEP" in added
            assert str(nested / "AGENTS.md") in added
            assert "state=added" in added and "revision=" in added

            changed = last_tool_output(3)
            assert "NESTED_RULE_V2_FOR_NEXT_STEP" in changed
            assert "state=changed" in changed and "revision=" in changed

            removed = last_tool_output(4)
            assert "state=removed" in removed
            assert "NESTED_RULE_V2_FOR_NEXT_STEP" not in removed
            assert len([event for event in events if event.get("type") == "tool_result"]) == 4
            assert any(event.get("type") == "tool_result" for event in events)
        finally:
            await local.shutdown()
            await memory.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kernel_instruction_bootstrap_requires_matching_trusted_workspace(
    tmp_path: Path, monkeypatch,
) -> None:
    import json
    from unittest.mock import MagicMock

    from atlas.agent import AgentOrchestrator, AgentRunContext
    from atlas.engine.atlas_runtime import AtlasRuntime
    from atlas.tools.local_execution import LocalExecutionRuntime
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_atlas_home
    from tests.test_engine_model_wiring import _ProviderKeyManager

    context_workspace = tmp_path / "trusted-context"
    request_workspace = tmp_path / "different-request"
    context_workspace.mkdir()
    request_workspace.mkdir()
    (context_workspace / ".git").mkdir()
    (context_workspace / "AGENTS.md").write_text("CONTEXT_ONLY_RULE", encoding="utf-8")
    (request_workspace / ".git").mkdir()
    (request_workspace / "AGENTS.md").write_text("MUST_NOT_INJECT_RULE", encoding="utf-8")

    with FakeLLMServer([Text("finished")]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        manager = _ProviderKeyManager(fake.base_url, current="main-model")
        manager._find_model = lambda model: next(
            (item for item in manager.list_models() if item["id"] == model), None,
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        memory = MemoryStore(db_path=tmp_path / "kernel-workspace-mismatch.sqlite3")
        await memory.init()
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(manager, memory, mcp_client=mcp, local_execution=local)
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        context = AgentRunContext(
            run_id="workspace-mismatch", conversation_id="workspace-mismatch",
            workspace=str(context_workspace), workspace_trusted=True,
        )
        try:
            _ = [event async for event in runtime.run_turn(
                message="Continue.", user_content="Continue.",
                conversation_id="workspace-mismatch", workspace=str(request_workspace),
                history=[], atlas_agent=agent, atlas_context=context, ephemeral=True,
            )]
            prompt = json.dumps(fake.main_requests()[0]["messages"], ensure_ascii=False)
            assert "MUST_NOT_INJECT_RULE" not in prompt
        finally:
            await local.shutdown()
            await memory.close()


@pytest.mark.unit
def test_unreadable_project_instruction_is_not_reported_removed(tmp_path: Path, monkeypatch) -> None:
    from atlas.agent.project_instructions import (
        load_project_instructions, project_instruction_root,
        refresh_project_instructions, snapshot_project_instructions,
    )

    workspace = tmp_path / "repo"
    nested = workspace / "src"
    nested.mkdir(parents=True)
    (workspace / ".git").mkdir()
    rule = nested / "AGENTS.md"
    rule.write_text("KEEP_WHILE_TEMPORARILY_UNREADABLE", encoding="utf-8")
    target = nested / "target.txt"
    target.write_text("ok", encoding="utf-8")
    root = project_instruction_root(workspace)
    previous = snapshot_project_instructions(load_project_instructions(nested, trusted=True))
    original_stat = Path.stat

    def deny_rule_stat(path: Path, *args, **kwargs):
        if path == rule:
            raise PermissionError("fixture read denied")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", deny_rule_stat)
    updates, current = refresh_project_instructions(
        workspace, [target], project_root=root, previous=previous,
    )

    assert updates == []
    assert current == previous


async def test_session_search_scopes_to_project_conversations(
    store: ProjectStore, tmp_path: Path,
) -> None:
    memory = MemoryStore(db_path=tmp_path / "memory.db")
    await memory.init()
    try:
        project = await store.create_project("Atlas")
        inside = await memory.create_conversation("Atlas work")
        await save_memory_fixture_message(
            memory, inside, "user", "the hybrid router needs a fallback",
        )
        outside = await memory.create_conversation("Random")
        await save_memory_fixture_message(memory, outside, "user", "hybrid cookies recipe")
        await store.attach_conversation(project.project_id, inside)

        unscoped = await memory.session_search("hybrid")
        assert len(unscoped) == 2

        scoped = await memory.session_search(
            "hybrid", conversation_ids=await store.list_conversations(project.project_id),
        )
        assert len(scoped) == 1
        assert scoped[0]["conversation_title"] == "Atlas work"
    finally:
        await memory.close()


async def test_find_by_conversation_and_orchestrator_context_block(
    store: ProjectStore, tmp_path: Path,
) -> None:
    from unittest.mock import MagicMock

    from atlas.agent import AgentOrchestrator
    from atlas.memory import MemoryStore

    project = await store.create_project(
        "Atlas", workspace_path="D:/Atlas", current_goal="mature agent",
    )
    await store.update_project(project.project_id, current_state="hub shipped")
    conv_id = "conv-ctx-1"
    await store.attach_conversation(project.project_id, conv_id)

    found = await store.find_by_conversation(conv_id)
    assert found is not None and found.project_id == project.project_id
    assert await store.find_by_conversation("unattached") is None

    memory = MemoryStore(db_path=tmp_path / "ctx-memory.db")
    await memory.init()
    try:
        await save_memory_fixture_message(memory, conv_id, "user", "hub 接着干什么")
        orchestrator = AgentOrchestrator(
            model_mgr=MagicMock(), memory=memory, mcp_client=None, projects=store,
        )
        state, knowledge = await orchestrator._project_context_block(conv_id, "hub 接着干什么")
        assert "Active project: Atlas" in state
        assert "mature agent" in state
        assert "hub shipped" in state
        assert "D:/Atlas" in state
        assert "Relevant prior sessions" in knowledge

        # unattached conversations get no project context
        empty = await orchestrator._project_context_block("no-project-conv", "hello")
        assert empty == ("", "")
    finally:
        await memory.close()
