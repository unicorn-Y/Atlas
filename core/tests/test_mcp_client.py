"""Tests for MCP client — unit tests with mock servers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from atlas.tools.mcp_client import (
    MCPClient,
    MCPServerConfig,
    ToolInfo,
    _parse_server_configs,
)

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
