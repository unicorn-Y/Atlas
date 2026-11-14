"""WAVE4 Z1 batch: engine tool-surface parity rows E4 / E22 / E24 / E26.

Covers, per row:
- E26  registry-scoped ``restrict_scope`` layers (DSH tools.restrict semantics:
  empty filter / unknown names fail at binding, restrictions intersect, disposer
  lifts, overlay entries stay visible) plus delegation admission fail-fast via
  ``validate_toolset_binding``.
- E22  Agent Teams model surface: run roster (``subtask_list``), team-wide
  bounded wait (``team_wait``), and the kanban task DAG per-mutation revision
  CAS (``expected_revision``).
- E24  the ralph loop: round cap resolution, report validation, bounded handoff,
  and terminal envelopes driven through the real tool dispatch with a stubbed
  delegation seam.
- E4   per-tool output contracts on the remaining registry tools.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.engine.tools.registry import ToolRegistry
from atlas.kanban import KanbanStore

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# E26 — registration-scoped restriction layer
# ---------------------------------------------------------------------------


def _registry_with_probe(name: str = "z1_probe") -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(name, "z1", {"parameters": {"type": "object"}},
                      lambda _args: "ok")
    return registry


def test_restrict_scope_fails_on_empty_filter_unknown_names_and_empty_sets():
    registry = _registry_with_probe()
    with pytest.raises(ValueError, match="no-op"):
        registry.restrict_scope()
    with pytest.raises(ValueError, match="unknown tool"):
        registry.restrict_scope(allow=["z1_missing"])
    with pytest.raises(ValueError, match="must not be empty"):
        registry.restrict_scope(allow=[])
    with pytest.raises(ValueError, match="must not be empty"):
        registry.restrict_scope(deny=[])
    with pytest.raises(ValueError, match="must be collections"):
        registry.restrict_scope(allow="z1_probe")


def test_restrict_scope_masks_offer_and_dispatch_until_disposed():
    registry = _registry_with_probe("z1_masked_probe")
    registry.register("z1_open_probe", "z1", {"parameters": {"type": "object"}},
                      lambda _args: "open")
    dispose = registry.restrict_scope(allow=["z1_masked_probe"])

    assert registry.get_entry("z1_open_probe") is None
    assert registry.get_entry("z1_masked_probe") is not None
    assert [item["function"]["name"]
            for item in registry.get_definitions({"z1_masked_probe", "z1_open_probe"})] == [
        "z1_masked_probe",
    ]
    assert "Unknown tool" in registry.dispatch("z1_open_probe", {})
    assert registry.dispatch("z1_masked_probe", {}) == "ok"

    dispose()
    assert registry.get_entry("z1_open_probe") is not None
    assert registry.dispatch("z1_open_probe", {}) == "open"


def test_restrict_scope_layers_intersect_and_deny_union():
    registry = _registry_with_probe("z1_shared_probe")
    registry.register("z1_extra_probe", "z1", {"parameters": {"type": "object"}},
                      lambda _args: "extra")
    dispose_one = registry.restrict_scope(allow=["z1_shared_probe", "z1_extra_probe"])
    dispose_two = registry.restrict_scope(allow=["z1_shared_probe"])
    dispose_three = registry.restrict_scope(deny=["z1_shared_probe"])

    # allow-layers intersect; a deny on any layer removes the tool outright.
    assert registry.get_entry("z1_extra_probe") is None
    assert registry.get_entry("z1_shared_probe") is None

    dispose_three()
    assert registry.get_entry("z1_shared_probe") is not None
    assert registry.get_entry("z1_extra_probe") is None

    dispose_two()
    assert registry.get_entry("z1_extra_probe") is not None

    dispose_one()
    assert registry.get_entry("z1_extra_probe") is not None
    assert registry._restrictions == {}


def test_validate_toolset_binding_fails_on_unknown_names_and_empty_resolution():
    from atlas.engine.tool_permissions import validate_toolset_binding

    available = ["web_search", "local_file", "read_file"]
    assert validate_toolset_binding(None, available) is None
    assert validate_toolset_binding(["local_file", "web_search"], available) == [
        "local_file", "web_search",
    ]
    # Globs are optional capabilities: a glob that matches nothing is tolerated
    # when the binding also resolves something concrete, but a binding whose
    # whole toolset resolves to nothing fails (empty-set registration rule).
    assert validate_toolset_binding(["local_file", "mcp__git__*"], available) == [
        "local_file",
    ]
    with pytest.raises(ValueError, match="empty tool set"):
        validate_toolset_binding(["mcp__git__*"], available)
    with pytest.raises(ValueError, match="unknown tool"):
        validate_toolset_binding(["terminal_typo"], available)
    with pytest.raises(ValueError, match="unknown tool"):
        validate_toolset_binding(["local_file", "nope_xyz"], available)
    with pytest.raises(ValueError, match="empty tool set"):
        validate_toolset_binding([], available)


def test_delegate_task_admission_fails_fast_on_unknown_definition_toolset(tmp_path):
    """The delegated child registration fails loudly instead of silently narrowing."""
    from unittest.mock import MagicMock

    agent = AgentOrchestrator(MagicMock(), MagicMock())
    from atlas.agent.definitions import _normalize
    from pathlib import Path as _Path

    definition = _normalize(
        "z1-broken", {"name": "z1-broken", "description": "broken toolset",
                      "tools": ["local_file", "totally_unknown_tool"]},
        "test", None, True)
    available = [item["function"]["name"] for item in agent._model_facing_tools()] + ["local_file"]
    from atlas.engine.tool_permissions import validate_toolset_binding

    with pytest.raises(ValueError, match="totally_unknown_tool"):
        validate_toolset_binding(definition.get("tools"), available)


# ---------------------------------------------------------------------------
# E22 — Agent Teams roster / team wait / kanban revision CAS
# ---------------------------------------------------------------------------


def test_delegation_service_roster_and_status_signature():
    from atlas.agent.enrichment import DelegationService

    service = DelegationService(SimpleNamespace(backends={}), MagicMock())
    service._subtasks.update({
        "t1": {"subtask_id": "t1", "goal": "alpha", "status": "running",
               "steer_queue": "SECRET", "cancel_event": "SECRET"},
        "t2": {"subtask_id": "t2", "goal": "beta", "status": "completed"},
    })
    roster = service.list_subtasks()
    assert [member["subtask_id"] for member in roster] == ["t1", "t2"]
    assert all("steer_queue" not in member and "cancel_event" not in member
               for member in roster)
    assert service.roster_status_signature() == {"t1": "running", "t2": "completed"}


def _dispatch(agent: AgentOrchestrator, runtime: AgentRunContext,
              name: str, args: dict[str, Any]) -> dict[str, Any]:
    from atlas.agent.tool_node import execute_tools_node

    state = {
        "messages": [AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"{name}-1"}])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    }
    return asyncio.run(execute_tools_node(agent, state))


def test_subtask_list_dispatch_hides_control_objects():
    from unittest.mock import MagicMock

    agent = AgentOrchestrator(MagicMock(), MagicMock(), agent_backend_host=SimpleNamespace(backends={}))
    assert agent._delegation is not None
    agent._delegation._subtasks.update({
        "m1": {"subtask_id": "m1", "goal": "alpha", "status": "completed",
               "steer_queue": "SECRET", "cancel_event": "SECRET"},
    })
    runtime = AgentRunContext(run_id="team-run", conversation_id="team-conv")

    output = _dispatch(agent, runtime, "subtask_list", {})
    result = output["messages"][-1].content
    assert isinstance(result, str) and "m1" in result and "alpha" in result
    assert "SECRET" not in result

    # nobody running → DSH noProgress fast path
    output = _dispatch(agent, runtime, "team_wait", {"timeout_seconds": 2})
    payload = json.loads(output["messages"][-1].content)
    assert payload["changed"] is False and payload["reason"] == "noProgress"


def test_team_wait_observes_mid_wait_status_change():
    from unittest.mock import MagicMock

    agent = AgentOrchestrator(MagicMock(), MagicMock(), agent_backend_host=SimpleNamespace(backends={}))
    delegation = agent._delegation
    delegation._subtasks["m1"] = {
        "subtask_id": "m1", "goal": "alpha", "status": "running"}

    async def flip_later():
        await asyncio.sleep(0.15)
        delegation._subtasks["m1"]["status"] = "completed"

    async def scenario():
        flipper = asyncio.create_task(flip_later())
        from atlas.agent.tool_node import execute_tools_node

        runtime = AgentRunContext(run_id="team-run-2", conversation_id="team-conv-2")
        state = {
            "messages": [AIMessage(content="", tool_calls=[{
                "name": "team_wait", "args": {"timeout_seconds": 3}, "id": "team-wait-1",
            }])],
            "pending_events": [], "tool_rounds": 0, "runtime": runtime,
        }
        output = await execute_tools_node(agent, state)
        await flipper
        payload = json.loads(output["messages"][-1].content)
        assert payload["changed"] is True and payload["reason"] == "changed"
        assert payload["statuses"] == {"m1": "completed"}

    asyncio.run(scenario())


def test_kanban_revision_cas_rejects_stale_and_bumps_on_success(tmp_path):
    store = KanbanStore(tmp_path / "kanban-cas.db")
    board = store.create_board("z1-cas")
    store.create_task(board["id"], {"title": "A"})
    store.create_task(board["id"], {"title": "B", "dependencies": ["x-missing"] if False else []})
    task = store.tasks(board["id"])[0]
    assert task["revision"] == 1

    with pytest.raises(ValueError, match="revision conflict"):
        store.update_task(board["id"], task["id"], {"status": "running"},
                          expected_revision=99)

    updated = store.update_task(board["id"], task["id"], {"status": "running"},
                                expected_revision=1)
    assert updated["revision"] == 2

    # omitting expected_revision keeps the legacy last-write-wins behavior
    legacy = store.update_task(board["id"], task["id"], {"status": "review"})
    assert legacy["revision"] == 3

    # dispatch_ready claims are mutations too: the revision moves
    claimed = store.dispatch_ready(board["id"], concurrency=1)
    assert claimed and claimed[0]["revision"] == 2


def test_kanban_task_tool_passes_expected_revision(tmp_path):
    from unittest.mock import MagicMock

    agent = AgentOrchestrator(MagicMock(), MagicMock(), agent_backend_host=SimpleNamespace(backends={}))
    runtime = AgentRunContext(run_id="kanban-run", conversation_id="kanban-conv")

    output = _dispatch(agent, runtime, "kanban_create_board", {"name": "z1-tool"})
    board_id = json.loads(output["messages"][-1].content)["id"]
    output = _dispatch(agent, runtime, "kanban_create_task",
                          {"board_id": board_id, "title": "task one"})
    created = json.loads(output["messages"][-1].content)
    assert created["revision"] == 1

    output = _dispatch(agent, runtime, "kanban_update_task", {
        "board_id": board_id, "task_id": created["id"],
        "status": "running", "expected_revision": 7,
    })
    assert "revision conflict" in output["messages"][-1].content

    output = _dispatch(agent, runtime, "kanban_update_task", {
        "board_id": board_id, "task_id": created["id"],
        "status": "running", "expected_revision": 1,
    })
    updated = json.loads(output["messages"][-1].content)
    assert updated["revision"] == 2 and updated["status"] == "running"


# ---------------------------------------------------------------------------
# E24 — ralph loop
# ---------------------------------------------------------------------------


def test_ralph_round_cap_resolution_and_report_validation():
    from atlas.agent.ralph_loop import MAX_HANDOFF_CHARS, resolve_max_rounds, validate_report

    assert resolve_max_rounds(None) == 256
    assert resolve_max_rounds(3) == 3
    with pytest.raises(ValueError, match="ceiling"):
        resolve_max_rounds(257)
    with pytest.raises(ValueError, match="positive"):
        resolve_max_rounds(0)

    base = {"status": "continue", "summary": "s", "evidence": ["e"],
            "nextSteps": ["n"], "blocker": ""}
    assert validate_report(dict(base))["status"] == "continue"
    with pytest.raises(ValueError, match="needs nextSteps"):
        validate_report({**base, "nextSteps": []})
    with pytest.raises(ValueError, match="needs evidence"):
        validate_report({**base, "status": "complete", "evidence": []})
    with pytest.raises(ValueError, match="concrete blocker"):
        validate_report({**base, "status": "blocked", "blocker": ""})
    with pytest.raises(ValueError, match="maxHandoffChars"):
        validate_report({**base, "summary": "x" * (MAX_HANDOFF_CHARS + 1)})
    with pytest.raises(ValueError, match="malformed"):
        validate_report({"status": "continue"})


def test_ralph_loop_terminal_envelopes_over_stubbed_delegation():
    from atlas.agent.ralph_loop import run_ralph_loop

    class _FakeDelegation:
        def __init__(self, reports):
            self.reports = list(reports)
            self.prompts: list[str] = []

        async def delegate_task(self, goal, context, tool_profile, **kwargs):
            self.prompts.append(goal)
            report = self.reports.pop(0)
            if report is None:
                return {"result": "child crashed", "schema_valid": False}
            return {"result": json.dumps(report, ensure_ascii=False), "schema_valid": True}

    continue_report = {"status": "continue", "summary": "s", "evidence": ["e"],
                       "nextSteps": ["n"], "blocker": ""}
    complete_report = {"status": "complete", "summary": "done", "evidence": ["f"],
                       "nextSteps": [], "blocker": ""}
    blocked_report = {"status": "blocked", "summary": "stuck", "evidence": ["e"],
                      "nextSteps": [], "blocker": "needs human"}

    async def scenario():
        delegation = _FakeDelegation([continue_report, complete_report])
        envelope = await run_ralph_loop(
            delegation, objective="ship it", max_rounds=5, child_options={})
        assert envelope["status"] == "complete" and envelope["roundsStarted"] == 2
        assert envelope["report"]["summary"] == "done"
        # round 1 carries no handoff; round 2 carries the bounded previous report
        assert "none" in delegation.prompts[0]
        assert '"status": "continue"' in delegation.prompts[1]

        delegation = _FakeDelegation([blocked_report])
        envelope = await run_ralph_loop(
            delegation, objective="ship it", max_rounds=4, child_options={})
        assert envelope["status"] == "blocked" and envelope["roundsStarted"] == 1

        delegation = _FakeDelegation([continue_report, None])
        envelope = await run_ralph_loop(
            delegation, objective="ship it", max_rounds=4, child_options={})
        assert envelope["status"] == "round-failed" and envelope["roundsStarted"] == 2
        assert envelope["lastReport"] == continue_report

        delegation = _FakeDelegation([continue_report] * 3)
        envelope = await run_ralph_loop(
            delegation, objective="ship it", max_rounds=3, child_options={})
        assert envelope["status"] == "budget-limited" and envelope["roundsStarted"] == 3

    asyncio.run(scenario())


def test_ralph_tool_dispatch_ends_with_terminal_envelope():
    from unittest.mock import MagicMock

    from atlas.agent.ralph_loop import MAX_RESULT_CHARS, bound_result

    agent = AgentOrchestrator(MagicMock(), MagicMock(), agent_backend_host=SimpleNamespace(backends={}))
    complete_report = {"status": "complete", "summary": "done", "evidence": ["f"],
                       "nextSteps": [], "blocker": ""}

    async def fake_delegate(goal, context, tool_profile, **kwargs):
        assert kwargs.get("output_schema") is not None
        assert kwargs.get("background") is False
        return {"result": json.dumps(complete_report, ensure_ascii=False),
                "schema_valid": True, "status": "completed"}

    agent._delegation.delegate_task = fake_delegate  # type: ignore[method-assign]

    async def scenario():
        from atlas.agent.tool_node import execute_tools_node

        runtime = AgentRunContext(run_id="ralph-run", conversation_id="ralph-conv")
        state = {
            "messages": [AIMessage(content="", tool_calls=[{
                "name": "ralph", "args": {"objective": "  ship it  ", "max_rounds": 2},
                "id": "ralph-1",
            }])],
            "pending_events": [], "tool_rounds": 0, "runtime": runtime,
        }
        output = await execute_tools_node(agent, state)
        text = output["messages"][-1].content
        assert "completion after 1 round" in text
        assert '"summary": "done"' in text
        assert output["pending_events"][0]["is_error"] is False

    asyncio.run(scenario())

    # the parent-facing text is bounded
    assert bound_result("x" * (MAX_RESULT_CHARS + 5)) == (
        "x" * (MAX_RESULT_CHARS - len("\n… [truncated]")) + "\n… [truncated]")


def test_ralph_schema_is_model_visible_only_with_delegation():
    from unittest.mock import MagicMock

    host = SimpleNamespace(backends={})
    agent = AgentOrchestrator(MagicMock(), MagicMock(), agent_backend_host=host)
    names = {item["function"]["name"] for item in agent._model_facing_tools()}
    assert {"ralph", "subtask_list", "team_wait"} <= names

    bare = AgentOrchestrator(MagicMock(), MagicMock())
    bare_names = {item["function"]["name"] for item in bare._model_facing_tools()}
    assert "ralph" not in bare_names and "subtask_list" not in bare_names


# ---------------------------------------------------------------------------
# E4 — remaining registry tools carry semantic output contracts
# ---------------------------------------------------------------------------


def test_registry_tools_expose_semantic_output_contracts():
    import atlas.engine.tools.browser_use_cli  # noqa: F401 - registers browser_exec
    import atlas.engine.tools.todo_tool  # noqa: F401 - registers todo_list
    from atlas.engine.tools.registry import registry
    from atlas.review.engine import register_review_tools

    register_review_tools()
    import atlas.engine.tool_registry  # noqa: F401 - binds new_context_window

    # The 12 alias registrations (read_file/terminal/...) are covered by
    # test_backend_parity_wave3_x7_e4_contracts.py via _alias_output_schema.
    for name in ("todo_list", "browser_exec", "review_command", "submit_findings"):
        contract = registry.get_output_contract(name)
        assert contract is not None, f"{name} has no output contract"
        schema = contract.schema
        assert schema.get("title") == f"{name} output"
        assert schema.get("description")
        assert schema.get("type") == "string" or "oneOf" in schema


def test_alias_output_contracts_flow_through_kernel_contract_lookup():
    """E4: the kernel contract lookup serves alias semantic schemas when the
    registry is unbound (the server process never imports engine/tools)."""
    from atlas.agent.tool_catalog import output_contracts_for_tools

    tools = [{"function": {"name": "read_file"}}, {"function": {"name": "execute_code"}},
             {"function": {"name": "some_host_tool"}}]
    contracts = output_contracts_for_tools(tools)
    read_schema = contracts["read_file"]["schema"]
    assert read_schema["title"] == "read_file output"
    assert read_schema.get("description")
    assert "oneOf" in read_schema  # the multimodal envelope shape, not the anyOf fallback
    assert contracts["execute_code"]["schema"]["type"] == "string"
    assert contracts["execute_code"]["schema"].get("description")
    fallback = contracts["some_host_tool"]["schema"]
    assert "anyOf" in fallback and not fallback.get("description")


def test_alias_output_schema_resolves_native_kernel_names():
    """E4: kernel-facing native names (local_file/local_shell/ask_user) resolve
    to the same semantic alias contracts, retitled for the model-facing name."""
    from atlas.engine.tool_registry import alias_output_schema

    local_file = alias_output_schema("local_file")
    assert local_file["title"] == "local_file output"
    assert "oneOf" in local_file
    assert "multimodal envelope" in local_file["description"]
    assert alias_output_schema("local_shell")["description"].startswith("Text output")
    assert alias_output_schema("ask_user")["title"] == "ask_user output"
    assert alias_output_schema("completely_unknown") is None
    # alias registration names keep working too
    assert alias_output_schema("read_file")["title"] == "read_file output"


def test_kernel_envelope_string_content_is_the_validation_target():
    """The kernel catalog envelope {"content": "<text>", ...} validates its text
    against oneOf/string alias contracts instead of failing as a bare dict."""
    from atlas.engine.kernel.loop import _presentation_schema_violation

    one_of = alias_one_of = {
        "title": "local_file output",
        "oneOf": [
            {"type": "string"},
            {"type": "object", "properties": {"_multimodal": {"const": True},
                                              "content": {"type": "array"}},
             "required": ["_multimodal", "content"]},
        ],
    }
    envelope = {"content": "=== README ===\n1\t# Atlas", "data": {}, "is_error": False}
    assert _presentation_schema_violation(envelope, one_of) is None
    assert _presentation_schema_violation(
        {"content": ["block", {"x": 1}], "data": {}}, one_of) is not None
    assert _presentation_schema_violation("raw text", one_of) is None


@pytest.mark.asyncio
async def test_restricted_scheduler_still_allows_concludeturn_but_honors_deny():
    """E26: a closed tool_allow list must not lock a run out of ending its turn;
    an explicit deny on concludeTurn still applies."""
    from atlas.engine.kernel.tools import ToolScheduler

    async def dispatch(_call_id, _name, _args):
        return {"content": "ok", "outcome": "completed"}

    scheduler = ToolScheduler(dispatch, allow=["local_file"])
    result = await scheduler.execute({"id": "c1", "function": {"name": "concludeTurn", "arguments": {}}})
    assert result.receipt.state == "completed"

    denied_scheduler = ToolScheduler(dispatch, allow=None, deny=["concludeTurn"])
    result = await denied_scheduler.execute(
        {"id": "c2", "function": {"name": "concludeTurn", "arguments": {}}})
    assert result.receipt.state == "failed"
    assert "not allowed" in str(result.output.get("error", ""))


def test_kernel_editor_schemas_honor_tool_allow():
    """E26: kernel editor schemas are appended after the allow/deny sweep, so
    they must be gated by the same predicate. A restricted child that is not
    granted edit/write/apply_patch must never be offered them."""
    from pathlib import Path

    from atlas.engine.kernel.edit import EDIT_TOOL_NAMES
    from atlas.engine.kernel.edit import EditManager
    from atlas.engine.tool_permissions import tool_allowed

    manager = EditManager(Path.cwd())
    offered = [str(item["function"]["name"]) for item in manager.get_tools_for_llm()]
    assert set(offered) == set(EDIT_TOOL_NAMES)

    allow = ["local_file", "search_files"]
    gated = [
        name for name in offered if tool_allowed(name, allow, ())
    ]
    assert gated == [], f"restricted run still offered {gated}"

    unrestricted = [name for name in offered if tool_allowed(name, None, ())]
    assert set(unrestricted) == set(EDIT_TOOL_NAMES)
