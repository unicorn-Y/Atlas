from __future__ import annotations

import asyncio
import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.fakes.fake_llm_provider import FakeLLMServer, Hang, Text, ToolCall, write_hermes_home
from atlas.engine.hermes_runtime import HermesRuntime
from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.tools.local_execution import LocalExecutionRuntime


def _disable_external_mcp(monkeypatch):
    monkeypatch.setattr("atlas.config.get_config", lambda: {
        "tools.servers": {}, "tools.auto_start": [],
    })


@pytest.mark.asyncio
async def test_real_hermes_agent_uses_fake_service_and_sessiondb_across_turns(
    tmp_path, monkeypatch,
):
    with FakeLLMServer([
        ToolCall("read_file", {"path": str(tmp_path / "fixture.txt")}),
        Text("first answer"),
        Text("second answer"),
    ]) as fake:
        home = tmp_path / "engine"
        (tmp_path / "fixture.txt").write_text("fake file content", encoding="utf-8")
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model",
            current_litellm_model="fake-model",
            gateway_base_url=fake.base_url,
            _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)

        first = [event async for event in runtime.run_turn(
            message="first question", conversation_id="e2e-session", workspace=str(tmp_path),
            history=[], system_message="Atlas system prompt", volatile_context=["Atlas memory: frozen fact"],
            enabled_toolsets=["file"],
        )]
        second = [event async for event in runtime.run_turn(
            message="second question", conversation_id="e2e-session", workspace=str(tmp_path),
            history=[], system_message="Atlas system prompt", volatile_context=["Atlas memory: changed"],
            enabled_toolsets=["file"],
        )]

        requests = fake.main_requests()
        assert first[-1]["result"]["final_response"] == "first answer"
        assert second[-1]["result"]["final_response"] == "second answer"
        assert len(requests) == 3
        system_first = next(item["content"] for item in requests[0]["messages"] if item["role"] == "system")
        system_second = next(item["content"] for item in requests[2]["messages"] if item["role"] == "system")
        assert "Atlas session-start context" in system_first
        assert "You are Atlas, the AI assistant for this workspace." in system_first
        assert "Atlas memory: frozen fact" in system_first
        assert system_second == system_first
        assert "Atlas memory: changed" not in system_second
        assert any(
            item.get("role") == "tool"
            for item in requests[1]["messages"]
        )
        assert any(
            item.get("role") == "assistant" and item.get("content") == "first answer"
            for item in requests[2]["messages"]
        )
        assert any(
            item.get("role") == "user" and item.get("content") == "first question"
            for item in requests[2]["messages"]
        )
        assert any(
            item.get("role") == "tool"
            for item in requests[2]["messages"]
        )
        usage = next(event["usage"] for event in second if event["type"] == "run_usage")
        assert usage["context_limit"] == 128000


@pytest.mark.asyncio
async def test_real_hermes_agent_completes_more_than_ten_tool_rounds(tmp_path, monkeypatch):
    script = []
    for index in range(11):
        script.append(ToolCall("read_file", {"path": str(tmp_path / f"{index}.txt")}))
    script.append(Text("all eleven tools completed"))
    for index in range(11):
        (tmp_path / f"{index}.txt").write_text(f"fixture {index}", encoding="utf-8")

    with FakeLLMServer(script) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        events = [event async for event in runtime.run_turn(
            message="read all fixtures", conversation_id="many-tools", workspace=str(tmp_path),
            history=[], enabled_toolsets=["file"],
        )]

        assert events[-1]["result"]["final_response"] == "all eleven tools completed"
        assert len(fake.main_requests()) == 12
        tool_results = [event for event in events if event["type"] == "tool_result"]
        assert len(tool_results) == 11
        assert all(not event["is_error"] for event in tool_results)


@pytest.mark.asyncio
async def test_real_manual_compression_uses_hermes_and_session_continues(tmp_path, monkeypatch):
    with FakeLLMServer([Text("done")], default_text="continued after compaction") as fake:
        home = tmp_path / "engine"
        write_hermes_home(
            home, fake.base_url,
            extra_config=(
                "auxiliary:\n"
                "  compression:\n"
                "    provider: custom\n"
                "    model: fake-model\n"
                f"    base_url: {fake.base_url}\n"
                "    api_key: sk-fake-e2e\n"
            ),
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-e2e")
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        conversation_id = "manual-compression"
        for index in range(24):
            [event async for event in runtime.run_turn(
                message=f"work item {index}: " + ("retained detail " * 160),
                conversation_id=conversation_id, workspace=str(tmp_path), history=[],
                system_message="Atlas identity and stable rules",
            )]

        compressed = await runtime.compact_session(
            conversation_id=conversation_id, workspace=str(tmp_path), focus_topic="preserve work state",
        )
        assert compressed["compressed"] is True, compressed
        assert fake.aux_requests(), "Hermes ContextCompressor must call the fake summary service"

        continued = [event async for event in runtime.run_turn(
            message="continue", conversation_id=conversation_id, workspace=str(tmp_path),
            history=[], system_message="Atlas identity and stable rules",
        )]
        assert continued[-1]["result"]["final_response"] == "continued after compaction"


@pytest.mark.asyncio
async def test_small_context_auto_compresses_and_keeps_active_todo(tmp_path, monkeypatch):
    target = tmp_path / "compression-write.txt"
    large_tool_content = "retain active requirements " * 900
    with FakeLLMServer(
        [
            ToolCall("todo_list", {"todos": [{
                "id": "todo-e2e", "content": "preserve this active todo through compression",
                "status": "in_progress",
            }]}),
            *[
                ToolCall("write_file", {"path": str(target), "content": large_tool_content})
                for _ in range(12)
            ],
            Text("work continued after automatic compression"),
        ],
        context_length=64000,
        prompt_tokens_fn=lambda body: len(json.dumps(body, ensure_ascii=False)) // 5,
    ) as fake:
        home = tmp_path / "engine"
        write_hermes_home(
            home, fake.base_url,
            extra_config=(
                "auxiliary:\n"
                "  compression:\n"
                "    provider: custom\n"
                "    model: fake-model\n"
                f"    base_url: {fake.base_url}\n"
                "    api_key: sk-fake-e2e\n"
            ),
            context_length=64000,
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        original_factory = runtime._agent_factory

        def agent_factory():
            HermesAgent = original_factory()

            def create_agent(**kwargs):
                instance = HermesAgent(**kwargs)
                instance._todo_store.write([{
                    "id": "todo-e2e", "content": "preserve this active todo through compression",
                    "status": "in_progress",
                }])
                return instance

            return create_agent

        monkeypatch.setattr(runtime, "_agent_factory", agent_factory)
        all_events = [event async for event in runtime.run_turn(
            message="keep the current todo while updating the fixture",
            conversation_id="small-context-compression", workspace=str(tmp_path), history=[],
        )]
        assert fake.aux_requests(), "64K real model context must trigger Hermes' automatic summary client"
        assert any(item.get("type") == "run.compaction.progress" for item in all_events)
        assert any(
            item.get("type") == "run_usage" and item.get("usage", {}).get("context_limit") == 64000
            for item in all_events
        ), "Atlas must surface Hermes' actual model context window"
        captured_requests = fake.main_requests()
        all_requests = json.dumps(captured_requests, ensure_ascii=False)
        request_outline = [
            {
                "request": index,
                "tools": [
                    tool.get("function", {}).get("name")
                    for message in request.get("messages", [])
                    for tool in message.get("tool_calls", [])
                ],
                "messages": [
                    {"role": message.get("role"), "content": str(message.get("content", ""))[:220]}
                    for message in request.get("messages", [])
                    if message.get("role") in {"user", "tool"}
                ],
            }
            for index, request in enumerate(captured_requests)
        ]
        relevant_messages = [
            {"role": message.get("role"), "content": str(message.get("content", ""))[:500]}
            for request in fake.main_requests() for message in request.get("messages", [])
            if "todo" in str(message.get("content", "")).casefold()
            or "active task" in str(message.get("content", "")).casefold()
        ]
        assert "[Your active task list was preserved across context compression]" in all_requests, request_outline
        assert "preserve this active todo through compression" in all_requests, relevant_messages
        assert target.read_text(encoding="utf-8") == large_tool_content
        assert "work continued after automatic compression" in all_events[-1]["result"]["final_response"]


@pytest.mark.asyncio
async def test_real_hermes_file_tools_preserve_lf_and_crlf(tmp_path, monkeypatch):
    lf_path = tmp_path / "lf.txt"
    crlf_path = tmp_path / "crlf.txt"
    lf_path.write_bytes(b"one\ntwo\n")
    crlf_path.write_bytes(b"one\r\ntwo\r\n")
    with FakeLLMServer([
        ToolCall("read_file", {"path": str(lf_path)}),
        ToolCall("patch", {"path": str(lf_path), "old_string": "two", "new_string": "TWO"}),
        Text("lf edited"),
        ToolCall("read_file", {"path": str(crlf_path)}),
        ToolCall("patch", {"path": str(crlf_path), "old_string": "two", "new_string": "TWO"}),
        Text("crlf edited"),
    ]) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        for index, message in enumerate(("edit lf", "edit crlf")):
            events = [event async for event in runtime.run_turn(
                message=message, conversation_id=f"line-endings-{index}",
                workspace=str(tmp_path), history=[], enabled_toolsets=["file"],
            )]
            assert not events[-1].get("error")
        assert lf_path.read_bytes() == b"one\nTWO\n"
        assert crlf_path.read_bytes() == b"one\r\nTWO\r\n"


@pytest.mark.asyncio
async def test_hermes_policy_plugin_enforces_read_only_approval_and_workspace(tmp_path, monkeypatch):
    _disable_external_mcp(monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    targets = [
        workspace / "readonly.txt", workspace / "denied.txt",
        workspace / "allowed.txt", tmp_path / "outside.txt",
    ]
    cases = [
        ("read_only", "deny", targets[0], []),
        ("ask_writes", "deny", targets[1], []),
        ("ask_writes", "allow", targets[2], []),
        ("full_access", "allow", targets[3], [str(workspace)]),
    ]
    script = []
    for index, (_mode, _choice, target, _paths) in enumerate(cases):
        script.extend([
            ToolCall("write_file", {"path": str(target), "content": f"case {index}"}),
            Text(f"finished {index}"),
        ])
    with FakeLLMServer(script) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(
            models, MagicMock(), mcp_client=mcp, local_execution=LocalExecutionRuntime(),
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        approval_calls = []
        hook_calls = []

        async def approve(event_id, name, args, selected):
            approval_calls.append((event_id, name))
            return selected

        for index, (mode, choice, target, allowed_paths) in enumerate(cases):
            ctx = AgentRunContext(
                cancel_event=asyncio.Event(), run_id=f"policy-{index}",
                conversation_id=f"policy-session-{index}", workspace=str(workspace),
                permission_mode=mode, allowed_paths=allowed_paths,
                approval_callback=lambda event_id, name, args, selected=choice: approve(
                    event_id, name, args, selected,
                ),
                user_hook_callback=lambda event, payload: hook_calls.append((event, payload)) or {},
            )
            events = [event async for event in runtime.run_turn(
                message=f"write policy case {index}", conversation_id=ctx.conversation_id,
                workspace=str(workspace), history=[], atlas_agent=agent, atlas_context=ctx,
            )]
            assert events[-1]["result"]["final_response"] == f"finished {index}"
            assert target.exists() is (index == 2)
        assert len(approval_calls) == 2
        assert {item[0] for item in hook_calls} >= {"tool.before", "tool.after"}


@pytest.mark.asyncio
async def test_write_snapshot_and_rewind_restore_file_and_hermes_session(tmp_path, monkeypatch):
    _disable_external_mcp(monkeypatch)
    from atlas.engine.session_sync import rewind_to_atlas_message

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "created-by-run.txt"
    with FakeLLMServer([
        ToolCall("write_file", {"path": str(target), "content": "written by Hermes"}),
        Text("file created"),
    ]) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(
            models, MagicMock(), mcp_client=mcp, local_execution=LocalExecutionRuntime(),
        )
        context = AgentRunContext(
            cancel_event=asyncio.Event(), run_id="rewind-run", conversation_id="rewind-session",
            workspace=str(workspace), permission_mode="full_access",
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        events = [event async for event in runtime.run_turn(
            message="create the fixture", conversation_id="rewind-session",
            workspace=str(workspace), history=[], atlas_agent=agent, atlas_context=context,
        )]
        assert events[-1]["result"]["final_response"] == "file created"
        assert target.read_text(encoding="utf-8") == "written by Hermes"
        checkpoints = agent.checkpoints.list_checkpoints(workspace, run_id="rewind-run")
        assert checkpoints and checkpoints[0]["files"][0]["exists"] is False

        rewind_to_atlas_message(
            runtime.home, "rewind-session", [{"id": "atlas-user-1", "role": "user"}],
            "atlas-user-1",
        )
        agent.checkpoints.restore_checkpoint(checkpoints[0]["id"])
        assert not target.exists()
        from atlas.engine.session_sync import capture_session

        restored = capture_session(runtime.home, "rewind-session")
        assert restored and restored.get("messages")
        from hermes_state import SessionDB

        with SessionDB(db_path=runtime.home / "state.db") as db:
            assert not db.get_messages_as_conversation("rewind-session")


@pytest.mark.asyncio
async def test_hermes_plan_mode_uses_plan_prompt_and_read_only_tools(tmp_path, monkeypatch):
    _disable_external_mcp(monkeypatch)
    target = tmp_path / "must-not-be-created.txt"
    with FakeLLMServer([
        ToolCall("write_file", {"path": str(target), "content": "blocked in plan"}),
        Text("plan finished"),
    ]) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(models, MagicMock(), mcp_client=mcp)
        context = AgentRunContext(
            cancel_event=asyncio.Event(), run_id="plan-run", conversation_id="plan-session",
            workspace=str(tmp_path), mode="plan",
        )
        events = [event async for event in HermesRuntime(
            data_dir=tmp_path, model_manager=models,
        ).run_turn(
            message="plan only", conversation_id="plan-session", workspace=str(tmp_path),
            history=[], atlas_agent=agent, atlas_context=context,
        )]
        assert events[-1]["result"]["final_response"] == "plan finished"
        assert not target.exists()
        request = fake.main_requests()[0]
        tools = {tool["function"]["name"] for tool in request["tools"]}
        assert tools <= {"read_file", "search_files", "terminal", "web_fetch", "web_search", "web_extract"}
        assert "terminal" in tools
        prompt = next(item["content"] for item in request["messages"] if item["role"] == "system")
        assert "[/plan — plan mode]" in prompt




@pytest.mark.asyncio
async def test_real_hermes_turn_delivers_queued_steer_after_tool_batch(tmp_path, monkeypatch):
    fixture = tmp_path / "steer-fixture.txt"
    fixture.write_text("read before the follow-up", encoding="utf-8")
    with FakeLLMServer([
        ToolCall("read_file", {"path": str(fixture)}),
        Text("finished after the queued correction"),
    ]) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        queue.put_nowait({"content": "switch to the saved plan", "event_id": "steer-e2e"})
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        turn = asyncio.create_task(_collect_turn(runtime, tmp_path, queue))
        events = await turn
        assert any(item.get("type") == "run_steered" and item.get("event_id") == "steer-e2e"
                   for item in events)
        assert "switch to the saved plan" in json.dumps(fake.main_requests(), ensure_ascii=False)


async def _collect_turn(runtime, tmp_path, queue):
    return [event async for event in runtime.run_turn(
        message="start", conversation_id="steering", workspace=str(tmp_path), history=[],
        steer_queue=queue,
    )]


@pytest.mark.asyncio
async def test_real_hermes_turn_stops_when_atlas_cancel_is_set(tmp_path, monkeypatch):
    with FakeLLMServer([Hang(seconds=8)]) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        cancel = asyncio.Event()
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        started = asyncio.get_running_loop().time()
        turn = asyncio.create_task(_collect_cancelled_turn(runtime, tmp_path, cancel))
        await asyncio.sleep(0.15)
        cancel.set()
        events = await asyncio.wait_for(turn, timeout=3)
        assert asyncio.get_running_loop().time() - started < 3
        assert events[-1].get("type") == "hermes.result"


async def _collect_cancelled_turn(runtime, tmp_path, cancel):
    return [event async for event in runtime.run_turn(
        message="stop this", conversation_id="cancel", workspace=str(tmp_path), history=[],
        cancel_event=cancel,
    )]


@pytest.mark.asyncio
async def test_hermes_mcp_client_calls_local_stdio_fake_server(tmp_path, monkeypatch):
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers

    server_path = Path(__file__).parent / "fakes" / "fake_mcp_server.py"
    marker_path = tmp_path / "fake-mcp-called.txt"
    monkeypatch.setenv("ATLAS_FAKE_MCP_MARKER", str(marker_path))
    monkeypatch.setattr("atlas.config.get_config", lambda: {
        "tools.servers": {"fake": {
            "transport": "stdio", "command": sys.executable,
            "args": [str(server_path)], "cwd": str(tmp_path), "enabled": True,
            "env": {"ATLAS_FAKE_MCP_MARKER": str(marker_path)},
        }},
        "tools.auto_start": [],
    })
    with FakeLLMServer([
        ToolCall("tool_search", {"queries": ["fake ping"]}),
        ToolCall("tool_call", {"calls": [{"name": "mcp__fake__ping", "arguments": {}}]}),
        Text("MCP replied pong"),
    ]) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(
            models, MagicMock(), mcp_client=mcp, local_execution=LocalExecutionRuntime(),
        )
        approval_calls = []
        hook_calls = []
        ctx = AgentRunContext(
            cancel_event=asyncio.Event(), run_id="mcp-run", conversation_id="mcp-session",
            workspace=str(tmp_path), permission_mode="ask_writes",
            approval_callback=lambda event_id, name, args: (
                approval_calls.append((event_id, name, args)) or "allow"
            ),
            user_hook_callback=lambda event, payload: hook_calls.append((event, payload)) or {},
        )
        try:
            events = [event async for event in HermesRuntime(
                data_dir=tmp_path, model_manager=models,
            ).run_turn(
                message="call the MCP fixture", conversation_id="mcp-session",
                workspace=str(tmp_path), history=[], atlas_agent=agent, atlas_context=ctx,
            )]
        finally:
            shutdown_mcp_servers(names={"fake"})
        assert events[-1]["result"]["final_response"] == "MCP replied pong"
        assert len(approval_calls) == 1 and approval_calls[0][1] == "mcp__fake__ping", {
            "marker_exists": marker_path.exists(),
            "approval_calls": approval_calls,
            "hook_calls": [item[0] for item in hook_calls],
            "messages": [
                (item.get("role"), str(item.get("name") or ""), str(item.get("content", ""))[:100])
                for item in events[-1]["result"].get("messages", [])
            ],
            "events": [(item.get("type"), item.get("name")) for item in events],
        }
        mcp_calls = [item for item in events if item.get("type") == "tool_result"
                     and item.get("name") == "mcp__fake__ping"]
        assert len(mcp_calls) == 1, events
        assert "pong from local fake MCP" in mcp_calls[0]["content"][0]["text"]
        assert marker_path.exists(), "Hermes must execute the local fake MCP server tool"
        assert [item[0] for item in hook_calls] == [
            "tool.before", "tool.after", "tool.before", "tool.after",
        ]
        assert [item[1]["tool_name"] for item in hook_calls] == [
            "tool_search", "tool_search", "mcp__fake__ping", "mcp__fake__ping",
        ]


@pytest.mark.asyncio
async def test_real_hermes_parallel_child_agents_use_fake_model(tmp_path, monkeypatch):
    with FakeLLMServer() as fake:
        def responder(record):
            body = record["body"]
            request_messages = body.get("messages", [])
            messages = json.dumps(request_messages, ensure_ascii=False)
            if "delegate both summaries" in messages and not any(
                item.get("role") == "tool" for item in request_messages
            ):
                return ToolCall("delegate_task", {"tasks": [
                    {"goal": "summarize fixture alpha"},
                    {"goal": "summarize fixture beta"},
                ]})
            if "delegate both summaries" in messages:
                return Text("both child summaries were dispatched")
            if "summarize fixture alpha" in messages:
                return Text("alpha child complete")
            if "summarize fixture beta" in messages:
                return Text("beta child complete")
            return Text("unexpected fake child prompt")

        fake._responder = responder
        home = tmp_path / "engine"
        write_hermes_home(
            home, fake.base_url,
            extra_config="delegation:\n  max_concurrent_children: 2\n  max_spawn_depth: 2\n",
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        events = [event async for event in runtime.run_turn(
            message="delegate both summaries", conversation_id="parallel-children",
            workspace=str(tmp_path), history=[], enabled_toolsets=["delegation"],
        )]
        dispatch = next(
            item for item in events
            if item.get("type") == "tool_result" and item.get("name") == "delegate_task"
        )
        payload = ast.literal_eval(dispatch["content"][0]["text"])
        assert payload["status"] == "dispatched"
        delegation_id = payload["delegation_id"]
        from tools.async_delegation import get_durable_delegation

        deadline = asyncio.get_running_loop().time() + 60
        record = None
        while asyncio.get_running_loop().time() < deadline:
            record = await asyncio.to_thread(get_durable_delegation, delegation_id)
            if record and record.get("state") not in {"running", "finalizing"}:
                break
            await asyncio.sleep(0.1)
        assert record and record.get("state") == "completed", record
        assert record.get("result") and len(record["result"].get("results", [])) == 2, record
        requests = fake.main_requests()
        assert len(requests) >= 3
        child_prompts = json.dumps(requests[1:], ensure_ascii=False)
        assert "summarize fixture alpha" in child_prompts
        assert "summarize fixture beta" in child_prompts
        child_summaries = {
            item.get("summary") for item in record["result"].get("results", [])
        }
        assert child_summaries == {"alpha child complete", "beta child complete"}, record
