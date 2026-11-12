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
from atlas.engine import AtlasRuntime
from atlas.runtime.hooks import HookStore, _json_decision
from atlas.tools.local_execution import LocalExecutionRuntime

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


def _approved_store(tmp_path: Path, event: str | None = None) -> HookStore:
    """A store whose project hooks have been reviewed.

    Project hooks are fail-closed: an unreviewed one is blocked before it runs,
    because a settings file in a checkout is not consent. Tests that are about
    what the hook *does* have to approve the current revision first, otherwise
    every one of them would assert the trust gate instead.
    """
    store = _store(tmp_path)
    for listed in store.list_all(str(tmp_path)):
        if event is not None and listed.get("event") != event:
            continue
        status = store.trust_status(listed)
        store.set_hook_trust(
            listed["id"], True, fingerprint=status["trust_fingerprint"], cwd=str(tmp_path),
        )
    return store


def _tool_runtime(tmp_path: Path, callback: Any, approval: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        cancel_event=None, pause_event=None, approval_callback=approval,
        event_queue=asyncio.Queue(), workspace=str(tmp_path),
        permission_mode="full_access", allowed_paths=[], run_id="run-1",
        conversation_id="conv-1", user_hook_callback=callback,
        tool_allow=None, tool_deny=[], read_only=False, mode="act",
        maintenance_context={},
        # Resolved per-run env overrides; the tool path reads it unconditionally,
        # so a stub without it fails the call instead of testing the hook.
        session_env={},
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
    outcome = await _approved_store(tmp_path).execute("tool.before", {
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
    outcome = await _approved_store(tmp_path).execute("tool.before", {
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
    outcome = await _approved_store(tmp_path).execute("tool.after", {
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
    outcome = await _approved_store(tmp_path).execute("UserPromptSubmit", {
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
    outcome = await _approved_store(tmp_path).execute("UserPromptSubmit", {
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
async def test_agent_userpromptsubmit_deny_returns_assistant_message(
    tmp_path, monkeypatch,
) -> None:
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import delete_session, read_session_all_messages
    from atlas.memory import MemoryStore

    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    agent = AgentOrchestrator(_run_model_mgr(), store)
    conversation_id = f"c4-deny-{tmp_path.name}"
    session_home = DATA_ROOT / "engine"

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert event == "UserPromptSubmit"
        assert payload["prompt"] == "hello"
        return {"blocked": True, "reason": "this prompt is not allowed"}

    try:
        events = [
            event async for event in agent.run(
                "hello", conversation_id, user_hook_callback=hook,
            )
        ]
        assert [event["type"] for event in events] == ["chunk", "done"]
        assert events[0]["content"] == "this prompt is not allowed"
        persisted = read_session_all_messages(session_home, conversation_id)
        assert len(persisted) == 1
        assert persisted[0]["role"] == "assistant"
        assert persisted[0]["content"] == events[0]["content"]
        assert events[1]["message_id"] == persisted[0]["id"]
        assert store._db is not None
        rows = await (await store._db.execute(
            "SELECT id FROM messages WHERE conversation_id = ?", (conversation_id,),
        )).fetchall()
        assert rows == []
    finally:
        await store.close()
        delete_session(session_home, conversation_id)


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
    runtime = AtlasRuntime(data_dir=tmp_path / "data", model_manager=MagicMock())
    result = await runtime.compact_session(
        conversation_id="conv-1", workspace=str(tmp_path),
        hook_store=_approved_store(tmp_path, "PreCompact"),
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
    assert events[1] == "SubagentStop"
    assert seen[0][1]["agent_type"] == "explore"
    assert seen[0][1]["subtask_id"] == "st-1"
    assert seen[1][1]["status"] == "completed"
    assert seen[1][1]["stop_hook_active"] is False
    # Child teardown now raises SessionEnd too, carrying the child's outcome.
    assert events[-1] == "SessionEnd"
    assert seen[-1][1]["conversation_id"] == "child-conv"
    assert seen[-1][1]["reason"] == "completed"


@pytest.mark.asyncio
async def test_subagentstop_hook_continue_keeps_same_child_session() -> None:
    memory = AsyncMock()
    memory.create_conversation.return_value = "child-conv"
    agent = AgentOrchestrator(MagicMock(), memory)
    stops: list[dict[str, Any]] = []

    async def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "SubagentStop":
            stops.append(dict(payload))
            if len(stops) == 1:
                return {"blocked": True, "reason": "还差一步没做完"}
        return {}

    runs: list[tuple[str, str]] = []

    async def fake_run(*args: Any, **kwargs: Any):
        runs.append((str(args[0]), str(kwargs["conversation_id"])))
        yield {"type": "chunk", "content": "child finished"}

    agent.run = fake_run  # type: ignore[method-assign]
    result = await agent._run_atlas_subtask(
        goal="collect facts", context=None, cwd=None, subtask_id="st-1",
        atlas_options={"user_hook_callback": hook, "agent_type": "explore"},
        on_progress=lambda text: None,
    )
    assert result["status"] == "completed"
    # The same child session ran twice: same conversation, no second runtime.
    assert [conversation for _, conversation in runs] == ["child-conv", "child-conv"]
    assert "还差一步没做完" in runs[1][0]
    assert [stop["stop_hook_active"] for stop in stops] == [False, True]
    # The child conversation is kept, not deleted. Teardown emits SessionEnd and
    # nothing else: a subtask's transcript is the evidence for what it did, and
    # deleting it on success left `subtask.*` views pointing at nothing.
    memory.delete_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_subagentstop_hook_gives_up_after_cap() -> None:
    from atlas.agent import _MAX_SUBAGENT_STOP_CONTINUATIONS

    memory = AsyncMock()
    memory.create_conversation.return_value = "child-conv"
    agent = AgentOrchestrator(MagicMock(), memory)

    async def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "SubagentStop":
            return {"blocked": True, "reason": "never good enough"}
        return {}

    run_calls = 0

    async def fake_run(*args: Any, **kwargs: Any):
        nonlocal run_calls
        run_calls += 1
        yield {"type": "chunk", "content": "child finished"}

    agent.run = fake_run  # type: ignore[method-assign]
    result = await agent._run_atlas_subtask(
        goal="collect facts", context=None, cwd=None, subtask_id="st-1",
        atlas_options={"user_hook_callback": hook, "agent_type": "explore"},
        on_progress=lambda text: None,
    )
    assert result["status"] == "completed"
    assert run_calls == 1 + _MAX_SUBAGENT_STOP_CONTINUATIONS


# ---------------------------------------------------------------------------
# Permission hooks: PermissionRequest deny / ask / allow
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
    outcome = await _approved_store(tmp_path, "PermissionRequest").execute("PermissionRequest", {
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
async def test_permissionrequest_hook_ask_continues_into_approval_card(
    tmp_path: Path,
) -> None:
    approval = AsyncMock(return_value="deny")

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "PermissionRequest":
            return {"ask_user": True}
        return {}

    agent = _orchestrator()
    result = await agent._execute_tools_node(_tool_state(
        "execute_command", {"command": "dir"},
        _tool_runtime(tmp_path, hook, approval=approval),
    ))
    # ask hands the decision to the normal approval flow instead of refusing.
    approval.assert_awaited_once()
    assert approval.await_args.args[0] == "approval:tc-1"
    assert approval.await_args.args[1] == "execute_command"
    approval_events = [
        event for event in result["pending_events"]
        if event["type"] == "approval_required"
    ]
    assert approval_events and approval_events[0]["event_id"] == "approval:tc-1"
    assert "denied by user" in result["messages"][0].content
    assert "Hook 要求人工确认" not in result["messages"][0].content


@pytest.mark.asyncio
async def test_permissionrequest_hook_allow_bypasses_approval_sensitive_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _hook_script(tmp_path, "permission_allow", (
        "import json,sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PermissionRequest',"
        " 'decision': {'behavior': 'allow',"
        " 'updatedInput': {'content': 'hook rewrote this'}}}}))\n"
    ))
    _write_project_hooks(tmp_path, "PermissionRequest", sys.executable, [str(script)],
                         matcher="local_file")
    outcome = await _approved_store(tmp_path).execute("PermissionRequest", {
        "tool_name": "local_file",
        "tool_input": {"path": "hooked.txt", "content": "original"},
    }, cwd=str(tmp_path))
    assert outcome["blocked"] is False
    decision = _json_decision("PermissionRequest", json.loads(outcome["logs"][0]["output"]))
    assert decision["allowed"] is True
    assert decision["updated_input"] == {"content": "hook rewrote this"}

    approval = AsyncMock(return_value="deny")

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "PermissionRequest":
            return {"allowed": True, "updated_input": {"content": "hook rewrote this"}}
        return {}

    agent = _orchestrator()
    agent._local_execution = LocalExecutionRuntime()
    agent._local_execution.permission_mode = "full_access"
    # local_file itself is not approval-gated; promote it into the sensitive set
    # so this test exercises the real PermissionRequest gate below.
    monkeypatch.setattr(
        type(agent), "APPROVAL_REQUIRED_TOOLS",
        AgentOrchestrator.APPROVAL_REQUIRED_TOOLS | {"local_file"},
    )
    try:
        result = await agent._execute_tools_node(_tool_state(
            "local_file",
            {"action": "write", "path": "hooked.txt", "content": "original"},
            _tool_runtime(tmp_path, hook, approval=approval),
        ))
    finally:
        await agent._local_execution.shutdown()
    approval.assert_not_awaited()
    assert all(
        event["type"] != "approval_required" for event in result["pending_events"]
    )
    assert result["pending_events"][-1]["is_error"] is False
    # The hook's updatedInput reached the tool: the rewritten content landed.
    assert (tmp_path / "hooked.txt").read_text(encoding="utf-8") == "hook rewrote this"


@pytest.mark.asyncio
async def test_permissionrequest_hook_ask_writes_ask_uses_approval_card(
    tmp_path: Path,
) -> None:
    approval = AsyncMock(return_value="deny")

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "PermissionRequest":
            return {"ask_user": True}
        return {}

    runtime = _tool_runtime(tmp_path, hook, approval=approval)
    runtime.permission_mode = "ask_writes"
    agent = _orchestrator()
    result = await agent._execute_tools_node(_tool_state(
        "local_file",
        {"action": "write", "path": "asked.txt", "content": "hook asked"},
        runtime,
    ))
    approval.assert_awaited_once()
    assert approval.await_args.args[0] == "approval:tc-1"
    assert approval.await_args.args[1] == "local_file"
    assert "操作未获允许" in result["messages"][0].content
    assert "Hook 要求人工确认" not in result["messages"][0].content
    assert not (tmp_path / "asked.txt").exists()


@pytest.mark.asyncio
async def test_permissionrequest_hook_ask_writes_allow_skips_approval(
    tmp_path: Path,
) -> None:
    approval = AsyncMock(return_value="deny")

    def hook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event == "PermissionRequest":
            return {"allowed": True, "updated_input": {"content": "hook rewrote this"}}
        return {}

    runtime = _tool_runtime(tmp_path, hook, approval=approval)
    runtime.permission_mode = "ask_writes"
    agent = _orchestrator()
    agent._local_execution = LocalExecutionRuntime()
    agent._local_execution.permission_mode = "full_access"
    try:
        result = await agent._execute_tools_node(_tool_state(
            "local_file",
            {"action": "write", "path": "allowed.txt", "content": "original"},
            runtime,
        ))
    finally:
        await agent._local_execution.shutdown()
    approval.assert_not_awaited()
    assert result["pending_events"][-1]["is_error"] is False
    assert (tmp_path / "allowed.txt").read_text(encoding="utf-8") == "hook rewrote this"
