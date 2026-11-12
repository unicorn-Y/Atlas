"""Acceptance coverage for stateless Streamable HTTP MCP servers."""

import asyncio
import contextlib
import socket

import pytest
import uvicorn

from atlas.tools.mcp_client import MCPClient, MCPServerConfig
from tests.fixtures.stateless_mcp_server import app, legacy_app


@contextlib.asynccontextmanager
async def _serve(asgi_app):
    """Run one fixture app on an ephemeral port for the duration of a test."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(
        asgi_app, host="127.0.0.1", port=port, log_level="error",
    ))
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.02)
        assert server.started
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=5)


@pytest.mark.asyncio
async def test_stateless_streamable_http_discovers_and_calls_tool():
    async with _serve(app) as url:
        client = MCPClient()
        await client._connect_server(MCPServerConfig(
            name="stateless", transport="streamable_http", url=url,
        ))
        assert [tool.qualified_name for tool in client.list_tools()] == ["stateless__ping"]
        result = await client.call_tool("stateless__ping", {})
        assert result["is_error"] is False
        assert result["content"][0]["text"] == "pong"
        assert client._server_status["stateless"]["connected"] is True
        assert client._server_status["stateless"]["state"] == "connected_stateless"
        await client.stop()


@pytest.mark.asyncio
async def test_legacy_server_falls_back_to_initialize_handshake():
    """A server without `server/discover` must degrade, not fail."""
    async with _serve(legacy_app) as url:
        client = MCPClient()
        await client._connect_server(MCPServerConfig(
            name="legacy", transport="streamable_http", url=url,
        ))
        assert [tool.qualified_name for tool in client.list_tools()] == ["legacy__ping"]
        result = await client.call_tool("legacy__ping", {})
        assert result["is_error"] is False
        assert result["content"][0]["text"] == "pong"
        assert client._server_status["legacy"]["connected"] is True
        assert client._server_status["legacy"]["state"] == "connected"
        await client.stop()
