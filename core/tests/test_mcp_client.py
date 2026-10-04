"""Tests for MCP client — unit tests with mock servers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas.tools.mcp_client import (
    MCPClient,
    MCPServerConfig,
    ToolInfo,
    _parse_server_configs,
)


def test_bundled_node_resolves_from_installed_application_directory(tmp_path, monkeypatch):
    from atlas.tools.node_runtime import resolve_node_runtime

    runtime_dir = tmp_path / "runtime" / "node"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "node.exe").write_bytes(b"node")
    npm_bin = runtime_dir / "npm" / "bin"
    npm_bin.mkdir(parents=True)
    (npm_bin / "npx-cli.js").write_text("", encoding="utf-8")
    monkeypatch.setenv("ATLAS_ROOT", str(tmp_path))
    monkeypatch.delenv("ATLAS_NODE_RUNTIME_DIR", raising=False)

    runtime = resolve_node_runtime()

    assert runtime.executable == runtime_dir / "node.exe"
    assert runtime.npx_script == npm_bin / "npx-cli.js"


def test_node_release_manifest_pins_official_binary_and_sha256():
    import json

    from atlas.tools.node_runtime import NODE_ARCHIVE_SHA256, NODE_VERSION

    manifest_path = Path(__file__).resolve().parents[2] / "frontend" / "node-runtime.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["version"] == NODE_VERSION.removeprefix("v")
    assert manifest["archive"] == "node-v22.23.3-win-x64.zip"
    assert manifest["source"].startswith("https://nodejs.org/dist/v22.23.3/")
    assert manifest["sha256"] == NODE_ARCHIVE_SHA256


def test_npx_uses_bundled_node_when_system_node_is_unavailable(tmp_path, monkeypatch):
    from atlas.tools.mcp_client import _resolve_stdio_command

    runtime_dir = tmp_path / "node"
    runtime_dir.mkdir()
    node = runtime_dir / "node.exe"
    node.write_bytes(b"node")
    npm_bin = runtime_dir / "npm" / "bin"
    npm_bin.mkdir(parents=True)
    npx_script = npm_bin / "npx-cli.js"
    npx_script.write_text("", encoding="utf-8")
    monkeypatch.setenv("ATLAS_NODE_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setattr("atlas.tools.node_runtime.shutil.which", lambda _name: None)

    command, args = _resolve_stdio_command("npx", ["-y", "example-mcp"])

    assert command == str(node)
    assert args == [str(npx_script), "-y", "example-mcp"]


def test_packaged_runtime_never_falls_back_to_system_node(tmp_path, monkeypatch):
    from atlas.tools.node_runtime import resolve_node_runtime

    monkeypatch.setenv("ATLAS_NODE_RUNTIME_DIR", str(tmp_path / "missing-node"))
    monkeypatch.setenv("ATLAS_NODE_RUNTIME_REQUIRED", "1")
    monkeypatch.setattr("atlas.tools.node_runtime.shutil.which", lambda _name: "C:/node.exe")

    runtime = resolve_node_runtime()

    assert runtime.executable is None
    assert runtime.source == "missing"


async def test_start_records_runtime_config_discovery_and_restart_state():
    client = MCPClient()
    mock_session = AsyncMock()
    mock_session.initialize.return_value = MagicMock(
        protocol_version="2025-03-26", server_info={"name": "filesystem"}
    )
    mock_session.list_tools.return_value = MagicMock(tools=[])

    async def connect_stdio(config, handle):
        handle.session = mock_session

    with patch("atlas.tools.mcp_client._parse_server_configs", return_value=[
        MCPServerConfig(name="filesystem", command="npx", args=["-y", "example"]),
    ]), patch.object(client, "_connect_stdio", side_effect=connect_stdio):
        await client.start()
        state = client.get_runtime_status()
        assert state["servers"][0]["configured"] is True
        assert state["servers"][0]["connected"] is True
        assert state["servers"][0]["tool_discovery"] == "complete"
        await client.restart_server("filesystem")
        await client.stop()

    assert client.get_runtime_status()["servers"][0]["connected"] is False


async def test_failed_configured_server_blocks_mcp_runtime_without_echoing_arguments():
    client = MCPClient()
    secret_argument = "argument-secret-must-not-appear"
    with (
        patch("atlas.tools.mcp_client._parse_server_configs", return_value=[
            MCPServerConfig(name="broken", command="node", args=[secret_argument]),
        ]),
        patch.object(client, "_connect_server", side_effect=RuntimeError(secret_argument)),
        patch("atlas.tools.mcp_client.get_node_runtime_status", return_value={"available": True}),
    ):
        await client.start()

    status = client.get_runtime_status()
    assert status["available"] is False
    assert status["servers"][0]["state"] == "failed"
    assert secret_argument not in status["blocking_reason"]

# ---------------------------------------------------------------------------
# ToolInfo
# ---------------------------------------------------------------------------

class TestToolInfo:
    def test_qualified_name(self) -> None:
        t = ToolInfo(
            name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            server_name="filesystem",
        )
        assert t.qualified_name == "filesystem__read_file"

    def test_to_openai_tool(self) -> None:
        t = ToolInfo(
            name="search",
            description="Search the web",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            server_name="brave",
        )
        result = t.to_openai_tool()
        assert result["type"] == "function"
        assert result["function"]["name"] == "brave__search"
        assert result["function"]["description"] == "Search the web"
        assert "query" in result["function"]["parameters"]["properties"]


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

class TestConfigParsing:
    def test_parse_empty_config(self) -> None:
        """No servers configured → empty list."""
        with patch("atlas.tools.mcp_client.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.get.return_value = {}
            mock_cfg.return_value = cfg
            configs = _parse_server_configs()
            assert configs == []

    def test_parse_stdio_server(self) -> None:
        """Parse a stdio server config."""
        with patch("atlas.tools.mcp_client.get_config") as mock_cfg:
            cfg = MagicMock()
            def side_effect(key, default=None):
                data = {
                    "tools.servers": {
                        "filesystem": {
                            "transport": "stdio",
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                        },
                    },
                    "tools.auto_start": ["filesystem"],
                }
                return data.get(key, default)
            cfg.get.side_effect = side_effect
            mock_cfg.return_value = cfg

            configs = _parse_server_configs()
            assert len(configs) == 1
            assert configs[0].name == "filesystem"
            assert configs[0].transport == "stdio"
            assert configs[0].command == "npx"
            assert configs[0].enabled is True

    def test_auto_start_filters(self) -> None:
        """Servers not in auto_start are disabled."""
        with patch("atlas.tools.mcp_client.get_config") as mock_cfg:
            cfg = MagicMock()
            def side_effect(key, default=None):
                data = {
                    "tools.servers": {
                        "filesystem": {"command": "npx", "args": []},
                        "git": {"command": "npx", "args": []},
                    },
                    "tools.auto_start": ["filesystem"],
                }
                return data.get(key, default)
            cfg.get.side_effect = side_effect
            mock_cfg.return_value = cfg

            configs = _parse_server_configs()
            fs = next(c for c in configs if c.name == "filesystem")
            git = next(c for c in configs if c.name == "git")
            assert fs.enabled is True
            assert git.enabled is False

    def test_expands_home_directory_in_server_arguments(self) -> None:
        with patch("atlas.tools.mcp_client.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.get.side_effect = lambda key, default=None: {
                "tools.servers": {"filesystem": {"command": "npx", "args": ["~/Documents"]}},
                "tools.auto_start": ["filesystem"],
            }.get(key, default)
            mock_cfg.return_value = cfg

            configs = _parse_server_configs()

        assert Path(configs[0].args[0]) == Path.home() / "Documents"


# ---------------------------------------------------------------------------
# MCPClient unit tests (mocked connections)
# ---------------------------------------------------------------------------

class TestMCPClient:
    def test_initial_state(self) -> None:
        """New client has no servers or tools."""
        client = MCPClient()
        assert client.list_tools() == []
        assert client.get_tools_for_llm() == []
        assert client.connected is False
        assert client.tool_count == 0

    def test_get_tool_not_found(self) -> None:
        """Looking up a non-existent tool returns None."""
        client = MCPClient()
        assert client.get_tool("nonexistent__tool") is None

    async def test_call_tool_unknown(self) -> None:
        """Calling unknown tool returns error."""
        client = MCPClient()
        result = await client.call_tool("nonexistent__tool", {})
        assert result["is_error"] is True
        assert "Unknown tool" in result["content"][0]["text"]

    async def test_call_tool_disconnected_server(self) -> None:
        """Calling tool with disconnected server returns error."""
        client = MCPClient()
        # Manually register a tool without a server
        tool = ToolInfo(
            name="test",
            description="test",
            input_schema={},
            server_name="dead_server",
        )
        client._tool_index["dead_server__test"] = tool
        result = await client.call_tool("dead_server__test", {})
        assert result["is_error"] is True
        assert "Server not connected" in result["content"][0]["text"]

    async def test_start_no_servers(self) -> None:
        """Starting with no configured servers is a no-op."""
        with patch("atlas.tools.mcp_client._parse_server_configs", return_value=[]):
            client = MCPClient()
            await client.start()  # should not raise
            assert client.connected is False

    async def test_stop_empty(self) -> None:
        """Stopping with no servers is a no-op."""
        client = MCPClient()
        await client.stop()  # should not raise

    def test_get_server_tools_empty(self) -> None:
        """Getting tools for non-existent server returns empty."""
        client = MCPClient()
        assert client.get_server_tools("nonexistent") == []

    async def test_call_tool_with_mock_session(self) -> None:
        """Simulate a successful tool call via mocked session."""
        from atlas.tools.mcp_client import MCPServerHandle

        client = MCPClient()

        # Create a mock session
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Hello from tool"
        # hasattr check for text
        type(mock_content).text = "Hello from tool"
        mock_result.content = [mock_content]
        mock_result.is_error = False
        mock_session.call_tool.return_value = mock_result

        handle = MCPServerHandle(name="test_srv", transport="stdio")
        handle.session = mock_session

        tool = ToolInfo(
            name="greet",
            description="Say hello",
            input_schema={"type": "object"},
            server_name="test_srv",
        )
        handle.tools.append(tool)
        client._servers["test_srv"] = handle
        client._tool_index["test_srv__greet"] = tool

        result = await client.call_tool("test_srv__greet", {"name": "Atlas"})
        assert result["is_error"] is False
        assert result["content"][0]["text"] == "Hello from tool"
        mock_session.call_tool.assert_called_once_with("greet", {"name": "Atlas"})

    async def test_connect_discovers_tools_for_agent(self) -> None:
        """Tools returned by a connected server are indexed for the Agent."""
        client = MCPClient()
        mock_session = AsyncMock()
        mock_session.initialize.return_value = MagicMock(
            protocol_version="2025-03-26", server_info={"name": "filesystem"}
        )
        mock_tool = MagicMock()
        mock_tool.name = "read_file"
        mock_tool.description = "Read a file"
        mock_tool.input_schema = {
            "type": "object", "properties": {"path": {"type": "string"}}
        }
        mock_session.list_tools.return_value = MagicMock(tools=[mock_tool])

        async def connect_stdio(config, handle):
            handle.session = mock_session

        with patch.object(client, "_connect_stdio", side_effect=connect_stdio):
            await client._connect_server(MCPServerConfig(name="filesystem"))

        assert client.get_server_names() == ["filesystem"]
        assert client.get_tools_for_llm() == [{
            "type": "function",
            "function": {
                "name": "filesystem__read_file",
                "description": "Read a file",
                "parameters": mock_tool.input_schema,
            },
        }]


async def test_restart_route_surfaces_transport_specific_exception_and_logs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from atlas.api import tools_router
    from atlas.api.app_services import AppServices

    class MCPTransportError(Exception):
        pass

    class FailingClient:
        def get_server_names(self) -> list[str]:
            return ["remote"]

        async def restart_server(self, _name: str) -> None:
            raise MCPTransportError("MCP session reset")

    logged: list[str] = []

    class CapturingLog:
        def exception(self, event: str, **_fields: object) -> None:
            logged.append(event)

    monkeypatch.setattr(tools_router, "log", CapturingLog())
    with pytest.raises(HTTPException) as error:
        await tools_router.restart_mcp_server(AppServices(mcp_client=FailingClient()), "remote")

    assert error.value.status_code == 500
    assert error.value.detail == "Restart failed: MCP session reset"
    assert logged == ["mcp.server_restart_failed"]
