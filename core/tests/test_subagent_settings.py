from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from atlas import server
from atlas.agent import AgentOrchestrator
from atlas.agent.enrichment import DelegationService, HookBus


class _ModelManager:
    gateway_base_url = "https://gateway.example/v1"
    api_key_configured = True
    current_model = "parent-model"

    def __init__(self) -> None:
        self.models = [{"id": "parent-model"}, {"id": "child-model"}]

    def list_models(self) -> list[dict[str, str]]:
        return self.models

    def update_provider(self, _base_url: str, _api_key: str | None) -> None:
        pass


@pytest.mark.asyncio
async def test_subagent_settings_apply_to_new_children_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas-data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    settings: dict[str, object] = {"unrelated": "preserved"}
    manager = _ModelManager()
    orchestrator = object.__new__(AgentOrchestrator)
    orchestrator._model_mgr = manager
    orchestrator.hooks = HookBus()
    orchestrator._mcp = None
    orchestrator._local_execution = None
    orchestrator._computer_use = None
    orchestrator.trajectory_reviewer = SimpleNamespace(reviewer=None)
    orchestrator._model_facing_tools = lambda: []
    delegation = DelegationService(host=None, hooks=orchestrator.hooks)
    child_models: list[str | None] = []
    child_started = {"child-model": asyncio.Event(), "parent-model": asyncio.Event()}
    finish_child = {"child-model": asyncio.Event(), "parent-model": asyncio.Event()}

    async def fake_child_runner(**kwargs):
        model = kwargs["atlas_options"].get("model")
        child_models.append(model)
        child_started[model].set()
        await finish_child[model].wait()
        return {"status": "completed", "result": "child finished", "evidence": []}

    delegation.atlas_runner = fake_child_runner
    orchestrator._delegation = delegation

    monkeypatch.setattr(server, "model_mgr", manager)
    monkeypatch.setattr(server, "load_user_settings", lambda: dict(settings))
    monkeypatch.setattr(
        server, "save_user_settings", lambda updated: settings.update(updated),
    )
    monkeypatch.setattr(
        "atlas.agent.load_user_settings", lambda: dict(settings),
    )
    monkeypatch.setattr(
        "atlas.agent.definitions.list_agent_types",
        lambda *_args: [{
            "name": "general", "warnings": [], "trusted": True,
            "model": "inherit", "tools": None, "permission_mode": None, "role": "leaf",
        }],
    )

    async def execute_child(call_id: str, *, background: bool = False):
        context = SimpleNamespace(
            model="parent-model", workspace=None, allowed_paths=[],
            permission_mode="full_access", user_hook_callback=None,
            ssh_tool_callback=None, ssh_checkpoint_callback=None,
            cancel_event=asyncio.Event(), pause_event=None, workspace_trusted=False,
            agent_role="general", agent_type="general", agent_depth=0,
            subtask_started=None, subtask_progress=None, subtask_completed=None,
            subtask_group_completed=None, event_queue=asyncio.Queue(),
            read_only=False, tool_allow=None, tool_deny=[], conversation_id="parent",
            approval_callback=None, sandbox_tool_callback=None, sandbox_enabled=False,
        )
        return await orchestrator._execute_tools_node({
            "messages": [AIMessage(content="", tool_calls=[{
                "name": "delegate_task",
                "args": {"goal": "inspect", "background": background}, "id": call_id,
            }])],
            "pending_events": [], "runtime": context,
        })

    saved = await server.update_configuration(server.ProviderSettingsRequest(
        subagents_enabled=True,
        subagent_default_model="child-model",
    ))
    assert saved["subagents_enabled"] is True
    assert saved["subagent_default_model"] == "child-model"
    await execute_child("first", background=True)
    await child_started["child-model"].wait()
    assert child_models == ["child-model"]
    assert settings["unrelated"] == "preserved"

    await server.update_configuration(server.ProviderSettingsRequest(
        subagent_default_model="parent-model",
    ))
    await execute_child("second", background=True)
    await child_started["parent-model"].wait()
    assert child_models == ["child-model", "parent-model"]

    await server.update_configuration(server.ProviderSettingsRequest(
        subagents_enabled=False,
    ))
    disabled_result = await execute_child("third")
    assert child_models == ["child-model", "parent-model"]
    rejected = next(event for event in disabled_result["pending_events"]
                    if event.get("type") == "tool_result")
    assert rejected["is_error"] is True
    assert "子 Agent 已禁用" in rejected["content"][0]["text"]

    finish_child["child-model"].set()
    finish_child["parent-model"].set()
    await asyncio.gather(*delegation._background_tasks.values())

