"""Regression coverage for the Wave 1 Agent enrichment adapters."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.agent.checkpoints import ShadowGitCheckpointStore
from atlas.agent.enrichment import (
    AtlasToolBridge,
    CodeActRuntime,
    ContextMaintenance,
    DelegationService,
    HookBus,
    ReminderPolicy,
    SystemReminders,
    TrajectoryReviewer,
)
from atlas.config import AtlasConfig
from atlas.runtime.backends import AgentEvent, AgentSession
from atlas.skills.bundles import PluginBundleDiscovery, parse_plugin_bundle
from atlas.tools.local_execution import LocalExecutionRuntime
from atlas.tools.mcp_client import MCPClient




@pytest.fixture
def model_mgr():
    manager = MagicMock()
    manager.current_model = "test-model"
    manager.current_litellm_model = "openai/test-model"
    return manager


@pytest.fixture
def memory():
    store = AsyncMock()
    store.get_conversation_messages.return_value = []
    store.get_agent_context_with_trace.return_value = {
        "memories": [], "knowledge_trace": {"query_terms": [], "decisions": []},
    }
    store.save_message.return_value = "message-1"
    return store


@pytest.fixture
def mcp_client():
    return MagicMock(spec=MCPClient)


async def test_hook_bus_runs_in_order_and_isolates_failures() -> None:
    bus = HookBus()
    order: list[str] = []

    async def first(**_payload):
        order.append("first")

    def broken(**_payload):
        order.append("broken")
        raise RuntimeError("hook failure")

    def last(**_payload):
        order.append("last")

    bus.register("before_model", first)
    bus.register("before_model", broken)
    bus.register("before_model", last)
    errors = await bus.emit("before_model", model="test")
    assert order == ["first", "broken", "last"]
    assert errors[0]["error"] == "hook failure"
    agent = AgentOrchestrator(MagicMock(), MagicMock(), hooks=bus)
    runtime = AgentRunContext()
    await agent._emit_hook(runtime, "before_model", model="test")
    assert (await runtime.event_queue.get())["type"] == "hook_error"


async def test_context_compaction_preserves_resume_critical_state() -> None:
    bus = HookBus()
    points: list[str] = []
    bus.register("before_compact", lambda **_: points.append("before"))
    bus.register("after_compact", lambda **_: points.append("after"))
    maintenance = ContextMaintenance(bus)
    assert maintenance.should_compact(["x"] * 3, message_limit=3)
    assert not maintenance.should_compact(["x"], message_limit=3, character_limit=2)
    snapshot = await maintenance.compact({
        "goal": "finish task", "project_state": "editing", "unresolved_work": ["verify"],
        "user_constraints": ["preserve files"], "active_process_refs": ["pid:1"],
        "active_tool_refs": ["execution:2"], "memory_refs": ["fact:timezone"],
        "large_transcript": "discarded",
    })
    assert points == ["before", "after"]
    assert snapshot["goal"] == "finish task"
    assert snapshot["unresolved_work"] == ["verify"]
    assert "large_transcript" not in snapshot




def test_system_reminder_fires_at_configured_cadence_once() -> None:
    reminders = SystemReminders(ReminderPolicy(cadence=3, max_reminders=2))
    assert reminders.at_turn(2, goal="goal") is None
    assert reminders.at_turn(3, goal="goal", constraints=["verify"]) == (
        "Task reminder: goal | Constraints: verify"
    )
    assert reminders.at_turn(3, goal="goal") is None
    assert reminders.at_turn(6, goal="goal") == "Task reminder: goal"
    assert reminders.at_turn(9, goal="goal") is None


async def test_trajectory_reviewer_is_optional_and_records_correction() -> None:
    disabled = TrajectoryReviewer()
    assert (await disabled.review_trajectory([], "goal"))["enabled"] is False
    reviewer = TrajectoryReviewer(lambda _events, _goal: "Return to the requested scope.")
    result = await reviewer.review_trajectory([{"type": "tool"}], "inspect source")
    assert result["decision"] == "corrective_guidance"
    assert result["guidance"] == "Return to the requested scope."
    assert reviewer.evidence == [{
        "goal": "inspect source", "event_count": 1,
        "decision": "corrective_guidance", "guidance": "Return to the requested scope.",
        "backend": None, "model": None,
    }]


async def test_trajectory_reviewer_config_defaults_off_and_routes_through_router(
    model_mgr, memory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atlas import agent as agent_module
    from atlas.models.router import CompletionResult

    monkeypatch.setattr(agent_module, "get_config", lambda: AtlasConfig())
    disabled = AgentOrchestrator(model_mgr, memory).trajectory_reviewer
    with patch(
        "atlas.models.router.ModelRouter.complete_for", AsyncMock(),
    ) as complete:
        assert (await disabled.review_trajectory([], "goal"))["enabled"] is False
        complete.assert_not_awaited()

    monkeypatch.setattr(agent_module, "get_config", lambda: AtlasConfig({
        "agent": {"trajectory_reviewer": {
            "enabled": True, "backend": "litellm", "model": "openai/test-reviewer",
        }},
    }))
    orchestrator = AgentOrchestrator(model_mgr, memory)
    configured = orchestrator.trajectory_reviewer
    complete_for = AsyncMock(return_value=CompletionResult(text=json.dumps({
        "decision": "corrective_guidance", "guidance": "Check the output once more.",
    })))
    orchestrator._model_router = SimpleNamespace(complete_for=complete_for)
    result = await configured.review_trajectory([{"type": "tool_result"}], "goal")
    assert result["decision"] == "corrective_guidance"
    assert result["guidance"] == "Check the output once more."
    assert complete_for.call_args.args[0] == "openai/test-reviewer"
    assert complete_for.call_args.args[1] == "reflection"
    assert complete_for.call_args.kwargs["max_tokens"] == 256


async def test_codeact_subprocess_uses_atlas_bridge_for_three_operations(tmp_path: Path) -> None:
    paths = [tmp_path / f"item-{index}.txt" for index in range(3)]
    for index, path in enumerate(paths):
        path.write_text(f"value-{index}", encoding="utf-8")
    runtime = CodeActRuntime(AtlasToolBridge(local=LocalExecutionRuntime()), timeout=10)
    calls = [
        "items.append(atlas.call_tool('local_file', "
        f"{{'action':'stat','path':{str(path)!r}}}))"
        for path in paths
    ]
    code = "\n".join([
        "items=[]", *calls,
        "result={'count':len(items),'sizes':[item['data']['size'] for item in items],",
        "'tool_count':len(atlas.list_tools()),'workspace':atlas.workspace}",
    ])
    events = []

    async def record_event(event: dict) -> None:
        events.append(event)

    result = await runtime.execute(
        code,
        tool_catalog=[{"type": "function", "function": {"name": "local_file"}}],
        event_callback=record_event,
    )
    assert result["exit_code"] == 0
    assert result["result"]["count"] == 3
    assert result["result"]["sizes"] == [7, 7, 7]
    assert result["result"]["tool_count"] == 1
    assert result["workspace_isolated"] is True
    assert not Path(result["result"]["workspace"]).exists()
    assert [step["status"] for step in result["steps"]] == ["completed"] * 3
    assert len(events) == 6
    preview = await runtime.execute(
        "atlas.call_tool('local_file', {'action': 'stat', 'path': 'missing'})",
        dry_run=True,
    )
    assert preview["executed"] is False
    assert preview["preview"] == {
        "tool_calls": ["local_file"], "call_count": 1, "dynamic_names": False,
    }


async def test_local_file_mutation_is_checkpointed_before_write_and_restorable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workspace" / "source.py"
    path.parent.mkdir()
    path.write_text("original", encoding="utf-8")
    checkpoints = ShadowGitCheckpointStore(tmp_path / "shadow")
    local = LocalExecutionRuntime()
    agent = AgentOrchestrator(MagicMock(), MagicMock(), local_execution=local,
                              checkpoint_store=checkpoints)
    runtime = AgentRunContext()
    state = {
        "messages": [AIMessage(content="", tool_calls=[{
            "name": "local_file", "args": {
                "action": "write", "path": str(path), "content": "mutated",
            }, "id": "write-1",
        }])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    }
    try:
        await agent._execute_tools_node(state)
        checkpoint_event = await runtime.event_queue.get()
        assert checkpoint_event["type"] == "checkpoint_created"
        assert path.read_text(encoding="utf-8") == "mutated"
        checkpoints.restore_checkpoint(checkpoint_event["checkpoint"]["id"])
        assert path.read_text(encoding="utf-8") == "original"
    finally:
        await local.shutdown()


async def test_delegation_uses_disposable_backend_and_returns_tool_evidence() -> None:
    hooks = HookBus()
    observed: list[str] = []
    hooks.register("subagent_start", lambda **_: observed.append("start"))
    hooks.register("subagent_end", lambda **_: observed.append("end"))

    class Backend:
        name = "fake"

        async def start_session(self, cwd=None):
            self.session = AgentSession("sub-1", cwd)
            self.events = []
            return self.session

        async def send(self, session, prompt):
            assert "investigate" in prompt.lower()
            tool = await bridge.call_tool("local_file", {"action": "stat", "path": "README.md"})
            self.events = [AgentEvent("tool", {"tool": "local_file", "result": tool}),
                           AgentEvent("message", {"text": "README inspected"}),
                           AgentEvent("done", {})]

        async def stream_events(self, _session):
            for event in self.events:
                yield event

        async def cancel(self, _session):
            return None

        async def resume(self, session_id, cwd=None):
            return AgentSession(session_id, cwd)

        async def close(self, _session):
            return None

    class Local:
        async def call_tool(self, name, arguments):
            return {"data": {"name": name, "path": arguments["path"]}}

    bridge = AtlasToolBridge(local=Local())
    host = MagicMock()
    backend = Backend()
    host.backends = {"fake": backend}
    host.sessions = {}

    async def start(name, cwd=None):
        session = await backend.start_session(cwd)
        host.sessions[session.id] = (name, session)
        return session

    async def send(session_id, prompt):
        name, session = host.sessions[session_id]
        await backend.send(session, prompt)

    async def events(session_id):
        _name, session = host.sessions[session_id]
        async for event in backend.stream_events(session):
            yield event

    async def close(session_id):
        name, session = host.sessions.pop(session_id)
        await host.backends[name].close(session)

    host.start, host.send, host.events, host.close = start, send, events, close
    service = DelegationService(host, hooks, timeout=5)
    result = await service.delegate_task(
        "Investigate", tool_profile=["local_file"], executor="fake",
    )
    assert "README inspected" in result["result"]
    assert result["evidence"][0]["data"]["tool"] == "local_file"
    assert observed == ["start", "end"]
    assert host.sessions == {}


def test_shadow_git_checkpoint_restores_scoped_file_without_repo_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    tracked = workspace / "source.py"
    unrelated = workspace / "notes.txt"
    tracked.write_text("before", encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")
    store = ShadowGitCheckpointStore(tmp_path / "atlas-shadow")
    checkpoint = store.create_checkpoint(workspace, ["source.py"])
    tracked.write_text("after", encoding="utf-8")
    restored = store.restore_checkpoint(checkpoint["id"])
    assert tracked.read_text(encoding="utf-8") == "before"
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert restored["restored"] == ["source.py"]
    shadow_git = tmp_path / "atlas-shadow" / checkpoint["id"] / "git"
    # S3 consolidation: snapshots are plain byte copies; no shadow git repo is built.
    assert not shadow_git.exists()
    assert store.list_checkpoints(workspace)[0]["id"] == checkpoint["id"]


def test_shadow_git_checkpoint_prunes_oldest_to_count_cap(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    note = workspace / "note.txt"
    note.write_text("first", encoding="utf-8")
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    monkeypatch.setattr(store, "MAX_CHECKPOINTS", 2)
    first = store.create_checkpoint(workspace, ["note.txt"])
    note.write_text("second", encoding="utf-8")
    store.create_checkpoint(workspace, ["note.txt"])
    note.write_text("third", encoding="utf-8")
    newest = store.create_checkpoint(workspace, ["note.txt"])
    remaining = store.list_checkpoints(workspace)
    assert len(remaining) == 2
    assert first["id"] not in {item["id"] for item in remaining}
    assert newest["id"] in {item["id"] for item in remaining}


def test_plugin_bundle_manifest_discovery_and_plain_skill_compatibility(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "sample"
    plugin_dir.mkdir(parents=True)
    manifest = plugin_dir / "atlas-plugin.json"
    manifest.write_text(json.dumps({
        "name": "sample-plugin", "version": "1.2.3", "description": "sample",
        "skills": ["skills/review"], "commands": [{"name": "review"}],
        "mcp_servers": [{"name": "search"}], "hooks": ["before_tool"],
        "agents": ["reviewer"], "ui": {"icon": "check"},
    }), encoding="utf-8")
    plain_skill = {"name": "plain-skill", "version": "0.1.0", "description": "legacy"}
    results = PluginBundleDiscovery().discover([tmp_path / "plugins"], [plain_skill])
    plugin = next(item for item in results if item["kind"] == "plugin_bundle")
    assert plugin["skills"] == ["skills/review"]
    assert plugin["commands"] == [{"name": "review"}]
    assert plugin["mcp_servers"] == [{"name": "search"}]
    assert plugin["hooks"] == ["before_tool"]
    assert plugin["agents"] == ["reviewer"]
    assert plugin["ui"] == {"icon": "check"}
    assert any(item["name"] == "plain-skill" for item in results)
    assert parse_plugin_bundle(manifest).name == "sample-plugin"
