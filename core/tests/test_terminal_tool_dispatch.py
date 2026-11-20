from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.api.app_services import AppServices
from atlas.api.tools_router import (
    get_agent_process_output,
    kill_agent_process,
    list_agent_processes,
    write_agent_process_stdin,
)
from atlas.engine.atlas_runtime import AtlasRuntime
from atlas.tools.local_execution import LocalExecutionRuntime
from fastapi import HTTPException
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_atlas_home


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _pty_supported() -> bool:
    return os.name == "nt" and importlib.util.find_spec("winpty") is not None


def _make_agent(
    fake: FakeLLMServer, local: LocalExecutionRuntime, data_dir: Path,
) -> tuple[AgentOrchestrator, AtlasRuntime]:
    models = SimpleNamespace(
        current_model="fake-model",
        current_litellm_model="fake-model",
        gateway_base_url=fake.base_url,
        _api_key="sk-fake-terminal-test",
        _find_model=lambda _model_id: {"max_output_tokens": 256},
        provider_config=lambda _provider_id: {},
        resolve_api_key=lambda _provider_id: None,
        credential_pool=lambda _provider_id: None,
        get_api_mode_override=lambda _provider_id: None,
        output_tokens_for_model=lambda _model, _fallback, configured=None: configured or 256,
        list_models=lambda: [{
            "id": "fake-model", "litellm_model": "openai/fake-model",
            "atlas_provider": "openai", "base_url": fake.base_url,
            "custom": True, "api_mode": "openai",
            "max_output_tokens": 256,
        }],
    )
    mcp = MagicMock()
    mcp.get_tools_for_llm.return_value = []
    mcp.list_tools.return_value = []
    mcp.tool_count = 0
    agent = AgentOrchestrator(models, MagicMock(), mcp_client=mcp, local_execution=local)
    runtime = AtlasRuntime(data_dir=data_dir, model_manager=models)
    return agent, runtime


async def _run_turn(
    runtime: AtlasRuntime,
    agent: AgentOrchestrator,
    workspace: Path,
    conversation_id: str,
    message: str,
) -> list[dict]:
    context = AgentRunContext(
        cancel_event=asyncio.Event(),
        run_id=f"run-{conversation_id}-{uuid.uuid4().hex}",
        conversation_id=conversation_id,
        workspace=str(workspace),
        working_directory=str(workspace),
        permission_mode="full_access",
    )
    async def collect() -> list[dict]:
        events = []
        async for event in runtime.run_turn(
            message=message,
            conversation_id=conversation_id,
            workspace=str(workspace),
            history=[],
            atlas_agent=agent,
            atlas_context=context,
        ):
            events.append(event)
        return events
    return await asyncio.wait_for(collect(), timeout=20)


async def _open_terminal(
    fake: FakeLLMServer,
    runtime: AtlasRuntime,
    agent: AgentOrchestrator,
    workspace: Path,
    conversation_id: str,
) -> list[dict]:
    fake.push(
        ToolCall("terminal_open", {"type": "powershell", "cwd": str(workspace), "name": "acceptance"}),
        Text("terminal opened"),
    )
    return await _run_turn(runtime, agent, workspace, conversation_id, "open an interactive terminal")


@pytest.mark.skipif(not _pty_supported(), reason="owner-scoped local PTY tools require Windows pywinpty")
async def test_kernel_dispatches_owner_scoped_terminal_tools_and_hides_them_from_process_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "engine"
    marker = "ATLAS_TERMINAL_DISPATCH_" + os.urandom(6).hex()
    marker_file = workspace / "terminal-result.txt"
    local = LocalExecutionRuntime()
    with FakeLLMServer([]) as fake:
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        agent, runtime = _make_agent(fake, local, tmp_path / "runtime")
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        try:
            model_tool_names = {
                item["function"]["name"] for item in agent._model_facing_tools()
            }
            assert "terminal_open" in model_tool_names, sorted(model_tool_names)
            fake.push(
                ToolCall("tool_search", {"query": "terminal open interactive"}),
                ToolCall("terminal_open", {
                    "type": "powershell", "cwd": str(workspace), "name": "acceptance",
                }),
                Text("terminal opened"),
            )
            opened = await _run_turn(
                runtime, agent, workspace, "terminal-owner-a", "open an interactive terminal",
            )
            assert "terminal_open" in str(opened)
            assert any(
                any(
                    item.get("function", {}).get("name") == "terminal_open"
                    for item in request.get("tools", [])
                )
                for request in fake.main_requests()
            ), "terminal_open was not offered after the real tool_search dispatch"
            record = next(item for item in local._processes.values() if item.terminal_owner_id)
            session_id = record.terminal_session_id
            assert session_id
            assert not any("terminal_owner_id" in str(event) for event in opened)

            fake.push(
                ToolCall("terminal_send", {
                    "sessionId": session_id,
                    "text": f"Set-Content -LiteralPath '{marker_file}' -Value '{marker}'",
                    "submit": True,
                    "timeout": 4,
                }),
                Text("terminal command sent"),
            )
            await _run_turn(runtime, agent, workspace, "terminal-owner-a", "send the marker")

            fake.push(
                ToolCall("terminal_read", {"sessionId": session_id, "offset": 0, "count": 65536}),
                Text("terminal output read"),
            )
            read = await _run_turn(runtime, agent, workspace, "terminal-owner-a", "read terminal output")
            assert marker in str(read)
            assert marker_file.read_text(encoding="utf-8").strip() == marker

            fake.push(
                ToolCall("terminal_read", {"sessionId": session_id, "offset": 0, "count": 65536}),
                Text("foreign access denied"),
            )
            foreign_request_index = len(fake.main_requests())
            denied = await _run_turn(runtime, agent, workspace, "terminal-owner-b", "read another agent terminal")
            assert "different agent" in str(denied).lower()
            foreign_requests = fake.main_requests()[foreign_request_index:]
            assert foreign_requests
            assert "terminal_open" not in {
                item.get("function", {}).get("name") for item in foreign_requests[0].get("tools", [])
            }, "a tool loaded in another conversation leaked into this provider request"

            services = AppServices(local_execution=local)
            process_id = record.execution_id
            assert all(item["id"] != process_id for item in await list_agent_processes(services))
            with pytest.raises(HTTPException) as output_error:
                await get_agent_process_output(services, process_id)
            assert output_error.value.status_code == 404
            with pytest.raises(HTTPException) as kill_error:
                await kill_agent_process(services, process_id)
            assert kill_error.value.status_code == 404
            with pytest.raises(HTTPException) as stdin_error:
                await write_agent_process_stdin(services, process_id, {"data": "unexpected"})
            assert stdin_error.value.status_code == 404

            fake.push(ToolCall("terminal_close", {"sessionId": session_id}), Text("terminal closed"))
            closed = await _run_turn(runtime, agent, workspace, "terminal-owner-a", "close terminal")
            assert "closed" in str(closed).lower()
            await asyncio.wait_for(record.wait_task, timeout=5)
            assert record.state != "running"
        finally:
            await runtime.aclose()
            await local.shutdown()


@pytest.mark.skipif(not _pty_supported(), reason="owner-scoped local PTY tools require Windows pywinpty")
async def test_local_execution_shutdown_reaps_unclosed_terminal_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "engine"
    local = LocalExecutionRuntime()
    with FakeLLMServer([]) as fake:
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        agent, runtime = _make_agent(fake, local, tmp_path / "runtime")
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        try:
            await _open_terminal(fake, runtime, agent, workspace, "terminal-shutdown-owner")
            record = next(item for item in local._processes.values() if item.terminal_owner_id)
            assert record.state == "running"
            await local.shutdown()
            await asyncio.wait_for(record.wait_task, timeout=5)
            assert record.state != "running"
        finally:
            await runtime.aclose()
            await local.shutdown()
