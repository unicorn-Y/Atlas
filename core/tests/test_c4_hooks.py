"""C4 E3 hooks: Claude-format command hooks wired into the Atlas agent loop.

Covers hook categories rather than every event: tool hooks (block / rewrite input /
append context), prompt hooks (UserPromptSubmit block + context injection),
lifecycle hooks (PreCompact, SubagentStart/Stop), and permission hooks
(PermissionRequest deny/ask). Hook commands run as real subprocesses fed via
stdin, but never touch real user directories or the network.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from atlas.agent import AgentOrchestrator
from atlas.engine import HermesRuntime
from atlas.runtime.hooks import HookStore, _json_decision


# ---------------------------------------------------------------------------
# Fixtures: Claude-format settings.json plus real hook executables
# ---------------------------------------------------------------------------

def _hook_script(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / f"{name}_hook.py"
    script.write_text(body, encoding="utf-8")
    return script


def _write_project_hooks(
    tmp_path: Path, event: str, command: str, args: list[str],
    *, matcher: str | None = None, local: bool = False,
) -> Path:
    group: dict[str, Any] = {"hooks": [
        {"type": "command", "command": command, "args": args},
    ]}
    if matcher is not None:
        group["matcher"] = matcher
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    path = claude / ("settings.local.json" if local else "settings.json")
    path.write_text(json.dumps({"hooks": {event: [group]}}), encoding="utf-8")
    return path


def _store(tmp_path: Path) -> HookStore:
    return HookStore(tmp_path / "hooks.toml")


def _tool_runtime(tmp_path: Path, callback: Any, approval: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        cancel_event=None, pause_event=None, approval_callback=approval,
        event_queue=asyncio.Queue(), workspace=str(tmp_path),
        permission_mode="full_access", allowed_paths=[], run_id="run-1",
        conversation_id="conv-1", user_hook_callback=callback,
        tool_allow=None, tool_deny=[], read_only=False, mode="act",
        maintenance_context={},
    )


def _tool_state(name: str, args: dict[str, Any], runtime: Any, call_id: str = "tc-1"):
    return {
        "messages": [AIMessage(content="", tool_calls=[
            {"name": name, "args": args, "id": call_id},
        ])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    }


def _orchestrator(memory: Any = None) -> AgentOrchestrator:
    return AgentOrchestrator(MagicMock(), memory or MagicMock())


@pytest.fixture
def spreadsheet(tmp_path: Path) -> Path:
    from atlas.office import create_spreadsheet

    created = create_spreadsheet(str(tmp_path), {
        "path": "hooked.xlsx",
        "sheets": [{"name": "Hooked", "rows": [["value"], [41]]}],
    })
    return tmp_path / created["path"]


# ---------------------------------------------------------------------------
# Tool hooks: block / rewrite input / append context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pretooluse_hook_blocks_tool_call(tmp_path: Path) -> None:
    script = _hook_script(tmp_path, "deny", (
        "import json,sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',"
        " 'permissionDecision': 'deny', 'permissionDecisionReason': 'no tool calls today'}}))\n"
    ))
    _write_project_hooks(tmp_path, "PreToolUse", sys.executable, [str(script)],
                         matcher="local_file")
    outcome = await _store(tmp_path).execute("tool.before", {
        "conversation_id": "conv", "tool_name": "local_file",
        "parameters": {"path": "x.txt", "action": "read"},
    }, cwd=str(tmp_path))
    assert outcome["blocked"] is True
    assert "no tool calls today" in outcome["reason"]


@pytest.mark.asyncio
async def test_pretooluse_hook_rewrites_tool_input(tmp_path: Path) -> None:
    script = _hook_script(tmp_path, "rewrite", (
        "import json,sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',"
        " 'permissionDecision': 'allow', 'updatedInput': {'path': 'hooked.xlsx'}}}))\n"
    ))
    _write_project_hooks(tmp_path, "PreToolUse", sys.executable, [str(script)],
                         matcher="read_office")
    outcome = await _store(tmp_path).execute("tool.before", {
        "conversation_id": "conv", "tool_name": "read_office",
        "parameters": {"path": "missing.xlsx"},
    }, cwd=str(tmp_path))
    assert outcome["blocked"] is False
    assert outcome["updated_input"] == {"path": "hooked.xlsx"}


@pytest.mark.asyncio
async def test_posttooluse_hook_appends_context(tmp_path: Path) -> None:
    script = _hook_script(tmp_path, "context", (
        "import json,sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse',"
        " 'additionalContext': 'hook says check the numbers'}}))\n"
    ))
    _write_project_hooks(tmp_path, "PostToolUse", sys.executable, [str(script)])
    outcome = await _store(tmp_path).execute("tool.after", {
        "conversation_id": "conv", "tool_name": "read_office",
        "parameters": {"path": "hooked.xlsx"}, "result": {"content": []},
    }, cwd=str(tmp_path))
    assert outcome["additional_context"] == "hook says check the numbers"


@pytest.mark.asyncio
async def test_agent_applies_pretooluse_updated_input(
    tmp_path: Path, spreadsheet: Path,
) -> None:
    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "tool.before":
            assert payload["tool_name"] == "read_office"
            assert payload["parameters"]["path"] == "missing.xlsx"
            return {"updated_input": {"path": spreadsheet.name}}
        return {}

    agent = _orchestrator()
    result = await agent._execute_tools_node(_tool_state(
        "read_office", {"path": "missing.xlsx"}, _tool_runtime(tmp_path, hook),
    ))
    # The rewritten input reaches the tool call itself, so the hook-referenced
    # workbook is the one actually read.
    assert "Hooked" in result["messages"][0].content
    assert result["messages"][0].tool_call_id == "tc-1"


@pytest.mark.asyncio
async def test_agent_appends_hook_context_to_tool_result(
    tmp_path: Path, spreadsheet: Path,
) -> None:
    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "tool.before":
            return {"additional_context": "pre context note"}
        assert event == "tool.after"
        return {"additional_context": "post context note"}

    agent = _orchestrator()
    result = await agent._execute_tools_node(_tool_state(
        "read_office", {"path": spreadsheet.name}, _tool_runtime(tmp_path, hook),
    ))
    content = result["messages"][0].content
    assert "Hooked" in content
    assert content.endswith("post context note")
    assert "pre context note" in content


@pytest.mark.asyncio
async def test_agent_tool_hook_block_prevents_execution(tmp_path: Path) -> None:
    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"blocked": True, "reason": "hook says no"}

    agent = _orchestrator()
    result = await agent._execute_tools_node(_tool_state(
        "read_office", {"path": "missing.xlsx"}, _tool_runtime(tmp_path, hook),
    ))
    assert "hook says no" in result["messages"][0].content
    assert result["pending_events"][0]["is_error"] is True


@pytest.mark.asyncio
async def test_posttooluse_failure_hook_fires_on_tool_error(tmp_path: Path) -> None:
    failures: list[tuple[str, dict[str, Any]]] = []

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "PostToolUseFailure":
            failures.append((event, dict(payload)))
        return {}

    agent = _orchestrator()
    await agent._execute_tools_node(_tool_state(
        "read_office", {"path": "missing.xlsx"}, _tool_runtime(tmp_path, hook),
    ))
    assert len(failures) == 1
    assert failures[0][1]["tool_name"] == "read_office"
    assert failures[0][1]["error"]


# ---------------------------------------------------------------------------
# Prompt hooks: UserPromptSubmit block + context injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_userpromptsubmit_hook_block_and_plain_stdout_context(
    tmp_path: Path,
) -> None:
    block_script = _hook_script(tmp_path, "prompt_block", (
        "import sys\n"
        "sys.stdin.read()\n"
        "sys.stderr.write('prompt rejected by policy')\n"
        "sys.exit(2)\n"
    ))
    _write_project_hooks(tmp_path, "UserPromptSubmit", sys.executable, [str(block_script)])
    outcome = await _store(tmp_path).execute("UserPromptSubmit", {
        "prompt": "hello", "conversation_id": "conv",
    }, cwd=str(tmp_path))
    assert outcome["blocked"] is True
    assert "prompt rejected by policy" in outcome["reason"]

    context_script = _hook_script(tmp_path, "prompt_context", (
        "import sys\n"
        "sys.stdin.read()\n"
        "print('extra background for this turn')\n"
    ))
    _write_project_hooks(tmp_path, "UserPromptSubmit", sys.executable, [str(context_script)])
    outcome = await _store(tmp_path).execute("UserPromptSubmit", {
        "prompt": "hello", "conversation_id": "conv",
    }, cwd=str(tmp_path))
    assert outcome["blocked"] is False
    assert outcome["additional_context"] == "extra background for this turn"


def _run_model_mgr() -> MagicMock:
    manager = MagicMock()
    manager.current_model = "test-model"
    manager.list_models.return_value = [
        {"id": "test-model", "litellm_model": "test-model", "fallback": []},
    ]
    return manager


@pytest.mark.asyncio
async def test_agent_userpromptsubmit_deny_returns_assistant_message() -> None:
    memory = AsyncMock()
    memory.save_message.return_value = "msg-1"
    agent = AgentOrchestrator(_run_model_mgr(), memory)

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert event == "UserPromptSubmit"
        assert payload["prompt"] == "hello"
        return {"blocked": True, "reason": "this prompt is not allowed"}

    events = [
        event async for event in agent.run(
            "hello", "conv-deny", user_hook_callback=hook,
        )
    ]
    assert [event["type"] for event in events] == ["chunk", "done"]
    assert events[0]["content"] == "this prompt is not allowed"
    assert events[1]["message_id"] == "msg-1"
    saved = memory.save_message.await_args
    assert saved.kwargs["role"] == "assistant"
    assert "this prompt is not allowed" in saved.kwargs["content"]
    # The blocked round never reached the model layer: no planning memories ran.
    memory.extract_memories.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_userpromptsubmit_context_enriches_the_round() -> None:
    memory = AsyncMock()
    memory.retrieve_approved_goal_knowledge.return_value = []
    memory.get_conversation_messages.side_effect = RuntimeError("stop test run")
    agent = AgentOrchestrator(_run_model_mgr(), memory)

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"additional_context": "injected facts"}

    events = [
        event async for event in agent.run(
            "hello", "conv-ctx", user_hook_callback=hook,
        )
    ]
    assert events[-1]["type"] == "error"
    enriched = memory.retrieve_approved_goal_knowledge.await_args.args[0]
    assert enriched == "hello\n\ninjected facts"


# ---------------------------------------------------------------------------
# Lifecycle hooks: PreCompact, SubagentStart / SubagentStop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_precompact_hook_blocks_manual_compaction(tmp_path: Path) -> None:
    script = _hook_script(tmp_path, "compact", (
        "import sys\nfrom pathlib import Path\n"
        "sys.stdin.read()\n"
        "Path(__file__).with_name('compact-marker').write_text('ran', encoding='utf-8')\n"
        "sys.stderr.write('compaction denied by policy')\n"
        "sys.exit(2)\n"
    ))
    _write_project_hooks(tmp_path, "PreCompact", sys.executable, [str(script)])
    runtime = HermesRuntime(data_dir=tmp_path / "data", model_manager=MagicMock())
    result = await runtime.compact_session(
        conversation_id="conv-1", workspace=str(tmp_path),
    )
    assert result["compressed"] is False
    assert result["reason"] == "blocked_by_hook"
    assert "compaction denied by policy" in result["detail"]
    assert (tmp_path / "compact-marker").exists()


@pytest.mark.asyncio
async def test_subagent_start_and_stop_hooks_fire() -> None:
    memory = AsyncMock()
    memory.create_conversation.return_value = "child-conv"
    agent = AgentOrchestrator(MagicMock(), memory)
    seen: list[tuple[str, dict[str, Any]]] = []

    async def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        seen.append((event, dict(payload)))

    async def fake_run(*args: Any, **kwargs: Any):
        yield {"type": "chunk", "content": "child finished"}

    agent.run = fake_run  # type: ignore[method-assign]
    result = await agent._run_atlas_subtask(
        goal="collect facts", context=None, cwd=None, subtask_id="st-1",
        atlas_options={"user_hook_callback": hook, "agent_type": "explore"},
        on_progress=lambda text: None,
    )
    assert result["status"] == "completed"
    events = [name for name, _ in seen]
    assert events[0] == "SubagentStart"
    assert events[-1] == "SubagentStop"
    assert seen[0][1]["agent_type"] == "explore"
    assert seen[0][1]["subtask_id"] == "st-1"
    assert seen[-1][1]["status"] == "completed"


# ---------------------------------------------------------------------------
# Permission hooks: PermissionRequest deny / ask
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_permissionrequest_hook_deny_skips_user_approval(tmp_path: Path) -> None:
    assert _json_decision("PermissionRequest", {
        "hookSpecificOutput": {"decision": {"behavior": "deny",
                                            "message": "not on my machine"}},
    })["blocked"] is True
    assert _json_decision("PermissionRequest", {
        "hookSpecificOutput": {"decision": {"behavior": "ask"}},
    })["ask_user"] is True

    script = _hook_script(tmp_path, "permission", (
        "import json,sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PermissionRequest',"
        " 'decision': {'behavior': 'deny', 'message': 'not on my machine'}}}))\n"
    ))
    _write_project_hooks(tmp_path, "PermissionRequest", sys.executable, [str(script)],
                         matcher="execute_command")
    outcome = await _store(tmp_path).execute("PermissionRequest", {
        "tool_name": "execute_command", "tool_input": {"command": "rm -rf /"},
    }, cwd=str(tmp_path))
    assert outcome["blocked"] is True
    assert "not on my machine" in outcome["reason"]

    approval = AsyncMock(return_value="deny")

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "PermissionRequest":
            return {"blocked": True, "reason": "not on my machine"}
        return {}

    agent = _orchestrator()
    result = await agent._execute_tools_node(_tool_state(
        "execute_command", {"command": "dir"},
        _tool_runtime(tmp_path, hook, approval=approval),
    ))
    approval.assert_not_awaited()
    assert all(
        event["type"] != "approval_required" for event in result["pending_events"]
    )
    assert "not on my machine" in result["messages"][0].content


@pytest.mark.asyncio
async def test_permissionrequest_hook_ask_blocks_as_manual_confirmation(
    tmp_path: Path,
) -> None:
    approval = AsyncMock(return_value="allow")

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "PermissionRequest":
            return {"ask_user": True}
        return {}

    agent = _orchestrator()
    result = await agent._execute_tools_node(_tool_state(
        "execute_command", {"command": "dir"},
        _tool_runtime(tmp_path, hook, approval=approval),
    ))
    approval.assert_not_awaited()
    assert "Hook 要求人工确认" in result["messages"][0].content
