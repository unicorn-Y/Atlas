from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from atlas.api import tools_router


def _set_isolated_atlas_config(tmp_path, monkeypatch):
    from atlas import config as config_module

    config_path = tmp_path / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("[tools]\nauto_start=[]\n[tools.servers]\n", encoding="utf-8")
    config = config_module.load_config(config_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_module, "_config", config)
    return config_module, config_path, config


@pytest.mark.asyncio
async def test_api_added_mcp_server_is_saved_to_the_atlas_config(tmp_path, monkeypatch):
    from atlas import server
    from atlas.tools.mcp_client import MCPClient

    config_module, config_path, config = _set_isolated_atlas_config(tmp_path, monkeypatch)

    fake_server = Path(__file__).parent / "fakes" / "fake_mcp_server.py"
    marker = tmp_path / "fake-mcp-marker.txt"
    client = MCPClient()
    monkeypatch.setattr(server, "mcp_client", client)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test"
        ) as api:
            response = await api.post("/api/mcp/servers", json={
                "name": "hermes-sync-fake",
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(fake_server)],
                "env": {"ATLAS_FAKE_MCP_MARKER": str(marker)},
            })

        assert response.status_code == 200, response.text
        saved = config_module.load_config(config_path)
        saved_server = saved.get("tools.servers.hermes-sync-fake")
        assert saved_server == {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(fake_server)],
            "url": "",
            "env": {"ATLAS_FAKE_MCP_MARKER": str(marker)},
            "enabled": True,
        }
        assert saved.get("tools.auto_start", []) == []
    finally:
        await client.disconnect_server("hermes-sync-fake")


@pytest.mark.asyncio
async def test_api_added_mcp_is_searchable_callable_and_removed_from_atlas(
    tmp_path, monkeypatch,
):
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers

    from atlas import server
    from atlas.agent import AgentOrchestrator, AgentRunContext
    from atlas.engine.atlas_runtime import AtlasRuntime
    from atlas.tools.local_execution import LocalExecutionRuntime
    from atlas.tools.mcp_client import MCPClient
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_atlas_home

    config_module, config_path, _ = _set_isolated_atlas_config(tmp_path, monkeypatch)
    fake_server = Path(__file__).parent / "fakes" / "fake_mcp_server.py"
    source_file = tmp_path / "source.txt"
    target_file = tmp_path / "roundtrip.txt"
    source_text = "MCP_SOURCE_ROUNDTRIP_MARKER"
    written_text = f"{source_text}:written-by-fake-provider"
    source_file.write_text(source_text, encoding="utf-8")
    name = "hermes-sync-fake"
    client = MCPClient()
    monkeypatch.setattr(server, "mcp_client", client)

    async def approve(_event_id, _tool, _args):
        return "allow"

    context = AgentRunContext(
        cancel_event=asyncio.Event(), run_id="mcp-config-run",
        conversation_id="mcp-config-session", workspace=str(tmp_path),
        permission_mode="ask_writes",
        approval_callback=approve,
    )

    response_number = 0
    search_results = []
    provider_read_results = []
    discovered_read_name = None
    discovered_write_name = None

    def respond(record):
        nonlocal response_number, discovered_read_name, discovered_write_name
        current = response_number
        response_number += 1
        if current in {0, 5}:
            return ToolCall("tool_search", {"queries": [f"{name} read_file", f"{name} write_file"]})
        if current == 1:
            search_message = next(
                message["content"] for message in reversed(record["body"]["messages"])
                if message.get("role") == "tool"
            )
            search = json.loads(search_message)
            search_results.append(search)
            matches = set(search.get("tools", {}))
            discovered_read_name = next(
                (item for item in matches if item.endswith("__read_file")), None,
            )
            discovered_write_name = next(
                (item for item in matches if item.endswith("__write_file")), None,
            )
            if not discovered_read_name or not discovered_write_name:
                return Text("FILESYSTEM_TOOLS_NOT_FOUND_IN_SEARCH_RESULTS")
            return ToolCall("tool_call", {"calls": [{
                "name": discovered_read_name, "arguments": {"path": str(source_file)},
            }]})
        if current == 2:
            read_result = next(
                str(message.get("content", ""))
                for message in reversed(record["body"]["messages"])
                if message.get("role") == "tool"
            )
            provider_read_results.append(read_result)
            if source_text not in read_result:
                return Text("SOURCE_CONTENT_NOT_RETURNED_BY_MCP")
            return ToolCall("tool_call", {"calls": [{
                "name": discovered_write_name,
                "arguments": {"path": str(target_file), "content": written_text},
            }]})
        if current == 3:
            return ToolCall("tool_call", {"calls": [{
                "name": discovered_read_name, "arguments": {"path": str(target_file)},
            }]})
        if current == 4:
            readback = next(
                str(message.get("content", ""))
                for message in reversed(record["body"]["messages"])
                if message.get("role") == "tool"
            )
            provider_read_results.append(readback)
            return Text("Filesystem round-trip verified" if written_text in readback
                        else "TARGET_READBACK_MISMATCH")
        if current == 6:
            removed_search_message = next(
                str(message.get("content", ""))
                for message in reversed(record["body"]["messages"])
                if message.get("role") == "tool"
            )
            search_results.append(json.loads(removed_search_message))
            return Text("MCP server has been removed")
        return Text("unexpected fake-provider request")

    with FakeLLMServer(respond) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        agent = AgentOrchestrator(
            models, object(), mcp_client=client, local_execution=LocalExecutionRuntime(),
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app), base_url="http://test"
            ) as api:
                added = await api.post("/api/mcp/servers", json={
                    "name": name,
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [str(fake_server)],
                    "cwd": str(tmp_path),
                    "env": {
                        "ATLAS_FAKE_MCP_ROOT": str(tmp_path),
                    },
                })
                assert added.status_code == 200, added.text

            persisted = config_module.load_config(config_path)
            assert name in persisted.get("tools.servers", {})
            added_turn = [event async for event in runtime.run_turn(
                message="Search for and use the local fixture filesystem tools.",
                conversation_id="mcp-config-session", workspace=str(tmp_path), history=[],
                atlas_agent=agent, atlas_context=context,
            )]
            assert added_turn[-1]["result"]["final_response"] == "Filesystem round-trip verified", (
                search_results
            )
            assert target_file.read_text(encoding="utf-8") == written_text
            assert len(provider_read_results) == 2
            assert source_text in provider_read_results[0]
            assert written_text in provider_read_results[1]
            assert discovered_read_name in search_results[0]["tools"]
            assert discovered_write_name in search_results[0]["tools"]

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app), base_url="http://test"
            ) as api:
                removed = await api.delete(f"/api/mcp/servers/{name}")
                assert removed.status_code == 200, removed.text

            reloaded = config_module.load_config(config_path)
            assert name not in reloaded.get("tools.servers", {})
            assert name not in reloaded.get("tools.auto_start", [])
            from tools.mcp_tool_common import _core
            from tools.registry import registry

            with _core._lock:
                live_keys = [key for key in _core._servers
                             if (key[1] if isinstance(key, tuple) else key) == name]
            remaining_tools = registry.get_tool_names_for_toolset(f"mcp-{name}")
            assert not live_keys and not remaining_tools, (live_keys, remaining_tools)
            assert registry.get_entry(f"{name}__read_file") is None
            assert registry.get_entry(f"{name}__write_file") is None
            remaining_client_tools = [tool["function"]["name"]
                                      for tool in agent._model_facing_tools()
                                      if name in tool["function"]["name"]]
            assert name not in client.get_server_names() and not remaining_client_tools, (
                client.get_server_names(), remaining_client_tools,
            )
            removed_context = AgentRunContext(
                cancel_event=asyncio.Event(), run_id="mcp-config-removed-run",
                conversation_id="mcp-config-removed-session", workspace=str(tmp_path),
                permission_mode="ask_writes", approval_callback=approve,
            )
            removed_turn = [event async for event in runtime.run_turn(
                message="Search for the removed fixture filesystem tools.",
                conversation_id="mcp-config-removed-session", workspace=str(tmp_path), history=[],
                atlas_agent=agent, atlas_context=removed_context,
            )]
            assert removed_turn[-1]["result"]["final_response"] == "MCP server has been removed"
            assert all(discovered_read_name not in result.get("tools", {})
                       and discovered_write_name not in result.get("tools", {})
                       for result in search_results[1:])
        finally:
            await client.disconnect_server(name)
            shutdown_mcp_servers(names={name})


@pytest.mark.asyncio
async def test_failed_api_mcp_add_does_not_change_atlas_config(tmp_path, monkeypatch):
    from atlas import server
    from atlas.tools.mcp_client import MCPClient

    config_module, config_path, config = _set_isolated_atlas_config(tmp_path, monkeypatch)
    failed_server = tmp_path / "failed-mcp.py"
    failed_server.write_text("raise SystemExit(1)\n", encoding="utf-8")
    client = MCPClient()
    monkeypatch.setattr(server, "mcp_client", client)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as api:
        response = await api.post("/api/mcp/servers", json={
            "name": "failed-mcp",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(failed_server)],
        })

    assert response.status_code == 500
    reloaded = config_module.load_config(config_path)
    assert reloaded.get("tools.servers", {}) == {}
    assert reloaded.get("tools.auto_start", []) == []
    assert config.get("tools.servers", {}) == {}


def test_mcp_config_mutation_preserves_empty_auto_start_means_all_enabled(tmp_path, monkeypatch):
    from atlas import server

    config_module, config_path, config = _set_isolated_atlas_config(tmp_path, monkeypatch)
    config.raw["tools"]["servers"] = {
        "existing": {"enabled": True, "transport": "stdio"},
    }
    config.raw["tools"]["auto_start"] = []

    tools_router._persist_mcp_server_config("new", {"enabled": True, "transport": "stdio"})
    added = config_module.load_config(config_path)
    assert added.get("tools.auto_start", []) == []
    assert added.get("tools.servers.existing.enabled") is True
    assert added.get("tools.servers.new.enabled") is True

    tools_router._persist_mcp_server_config("new", None)
    removed = config_module.load_config(config_path)
    assert removed.get("tools.auto_start", []) == []
    assert removed.get("tools.servers.existing.enabled") is True


def test_removing_last_selected_server_keeps_excluded_servers_disabled(tmp_path, monkeypatch):
    from atlas import server

    config_module, config_path, config = _set_isolated_atlas_config(tmp_path, monkeypatch)
    config.raw["tools"]["servers"] = {
        "selected": {"enabled": True, "transport": "stdio"},
        "excluded": {"enabled": True, "transport": "stdio"},
    }
    config.raw["tools"]["auto_start"] = ["selected"]

    tools_router._persist_mcp_server_config("selected", None)
    removed = config_module.load_config(config_path)
    assert removed.get("tools.auto_start", []) == []
    assert removed.get("tools.servers.excluded.enabled") is False


@pytest.mark.asyncio
async def test_runtime_only_mcp_remove_write_failure_reconnects_from_client_config(
    tmp_path, monkeypatch,
):
    from atlas import server
    from atlas.tools.mcp_client import MCPClient, MCPServerConfig

    config_module, config_path, _ = _set_isolated_atlas_config(tmp_path, monkeypatch)
    fixture = Path(__file__).parent / "fakes" / "fake_mcp_server.py"
    marker = tmp_path / "runtime-only-marker.txt"
    name = "runtime-only"
    client = MCPClient()
    await client._connect_server(MCPServerConfig(
        name=name,
        command=sys.executable,
        args=[str(fixture)],
        cwd=str(tmp_path),
        env={"ATLAS_FAKE_MCP_MARKER": str(marker), "ATLAS_FAKE_MCP_ROOT": str(tmp_path)},
    ))
    monkeypatch.setattr(server, "mcp_client", client)

    def fail_persist(_name, _value):
        raise OSError("isolated simulated config write failure")

    monkeypatch.setattr(tools_router, "_persist_mcp_server_config", fail_persist)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test"
        ) as api:
            response = await api.delete(f"/api/mcp/servers/{name}")

        assert response.status_code == 500
        assert client.get_server_names() == [name]
        ping = await client.call_tool(f"{name}__ping", {})
        assert not ping["is_error"]
        assert "pong from local fake MCP" in ping["content"][0]["text"]
        assert marker.read_text(encoding="utf-8") == "ping"
        assert config_module.load_config(config_path).get("tools.servers", {}) == {}
    finally:
        await client.disconnect_server(name)


def test_plan_binding_does_not_prune_active_atlas_mcp_copy(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from tools.registry import registry
    from toolsets import TOOLSETS

    from atlas.engine.tool_registry import bind_atlas_tools, unregister_atlas_mcp_tools

    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    name = "plan-scope-mcp__read_file"
    schema = {"type": "function", "function": {
        "name": name,
        "description": "Read a file from the test fixture.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    }}
    mcp = SimpleNamespace(get_tools_for_llm=lambda: [schema])
    agent = SimpleNamespace(_mcp=mcp, _model_facing_tools=lambda: [schema])
    loop = asyncio.new_event_loop()
    scope = registry.current_scope_key()
    try:
        bind_atlas_tools(agent, SimpleNamespace(mode="act"), loop)
        assert registry.get_entry(name, scope=scope).toolset == "atlas"

        bind_atlas_tools(agent, SimpleNamespace(mode="plan"), loop)
        assert registry.get_entry(name, scope=scope).toolset == "atlas"
        assert name not in TOOLSETS["atlas-plan"]["tools"]
    finally:
        unregister_atlas_mcp_tools({name}, {scope})
        loop.close()
