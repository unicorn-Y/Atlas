"""MCP Client — manage MCP server processes and call their tools.

Designed for Atlas to connect to multiple MCP servers simultaneously,
each providing a set of tools the agent can call.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

from atlas.config import get_config

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ToolInfo:
    """Flattened representation of an MCP tool for the LLM."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str  # which server owns this tool

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible tool definition for LiteLLM."""
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": self.description or "",
                "parameters": self.input_schema,
            },
        }

    @property
    def qualified_name(self) -> str:
        """Globally unique name: server__toolname."""
        return f"{self.server_name}__{self.name}"


@dataclass
class MCPServerHandle:
    """Runtime state for one connected MCP server."""

    name: str
    transport: str  # "stdio" | "sse"
    session: ClientSession | None = None
    tools: list[ToolInfo] = field(default_factory=list)
    _cleanup: Any = None  # async context manager exit


# ---------------------------------------------------------------------------
# Server config from TOML
# ---------------------------------------------------------------------------

@dataclass
class MCPServerConfig:
    """Parsed config for one MCP server."""

    name: str
    transport: str = "stdio"        # "stdio" | "sse"
    command: str = ""               # for stdio
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str = ""                   # for sse
    enabled: bool = True


def _parse_server_configs() -> list[MCPServerConfig]:
    """Read [tools.servers.*] from atlas.toml.

    Expected TOML format::

        [tools.servers.filesystem]
        transport = "stdio"          # default
        command = "npx"
        args = ["-y", "@modelcontextprotocol/server-filesystem", "D:/Atlas"]

        [tools.servers.brave-search]
        transport = "stdio"
        command = "npx"
        args = ["-y", "@modelcontextprotocol/server-brave-search"]
        env = { BRAVE_API_KEY = "..." }

        [tools.servers.remote-example]
        transport = "sse"
        url = "http://localhost:3001/sse"
    """
    cfg = get_config()
    servers_raw: dict[str, Any] = cfg.get("tools.servers", {}) or {}
    auto_start: list[str] = cfg.get("tools.auto_start", []) or []

    configs: list[MCPServerConfig] = []
    for name, data in servers_raw.items():
        if not isinstance(data, dict):
            continue
        sc = MCPServerConfig(
            name=name,
            transport=data.get("transport", "stdio"),
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            cwd=data.get("cwd"),
            url=data.get("url", ""),
            enabled=data.get("enabled", True),
        )
        # Only include servers that are both configured *and* in auto_start
        # (unless auto_start is empty, meaning "start all configured")
        if auto_start and name not in auto_start:
            sc.enabled = False
        configs.append(sc)
    return configs


# ---------------------------------------------------------------------------
# MCPClient
# ---------------------------------------------------------------------------

class MCPClient:
    """Manages multiple MCP server connections.

    Lifecycle::

        client = MCPClient()
        await client.start()       # connects all configured servers
        tools = client.list_tools() # get all available tools
        result = await client.call_tool("server__tool", {"arg": "val"})
        await client.stop()        # shuts down all servers
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerHandle] = {}
        self._tool_index: dict[str, ToolInfo] = {}  # qualified_name → ToolInfo
        self._server_configs: dict[str, MCPServerConfig] = {}  # name → config

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Connect to all configured & enabled MCP servers."""
        configs = _parse_server_configs()
        enabled = [c for c in configs if c.enabled]
        if not enabled:
            log.info("mcp.no_servers_configured")
            return

        log.info("mcp.starting", count=len(enabled),
                 names=[c.name for c in enabled])

        results = await asyncio.gather(
            *[self._connect_server(c) for c in enabled],
            return_exceptions=True,
        )
        for cfg, result in zip(enabled, results):
            if isinstance(result, Exception):
                log.error("mcp.server_failed", server=cfg.name,
                          error=str(result))

    async def stop(self) -> None:
        """Disconnect all MCP servers."""
        for name, handle in list(self._servers.items()):
            try:
                if handle._cleanup:
                    await handle._cleanup.__aexit__(None, None, None)
                log.info("mcp.server_stopped", server=name)
            except Exception as e:
                log.warning("mcp.stop_error", server=name, error=str(e))
        self._servers.clear()
        self._tool_index.clear()

    # -- connecting ----------------------------------------------------------

    async def _connect_server(self, cfg: MCPServerConfig) -> None:
        """Connect to a single MCP server."""
        handle = MCPServerHandle(name=cfg.name, transport=cfg.transport)

        if cfg.transport == "stdio":
            await self._connect_stdio(cfg, handle)
        elif cfg.transport == "sse":
            await self._connect_sse(cfg, handle)
        else:
            raise ValueError(f"Unknown transport: {cfg.transport}")

        # Initialize the session
        assert handle.session is not None
        init_result = await handle.session.initialize()
        log.info("mcp.server_initialized",
                 server=cfg.name,
                 protocol=init_result.protocol_version,
                 server_info=str(init_result.server_info))

        # Discover tools
        tools_result = await handle.session.list_tools()
        for tool in tools_result.tools:
            info = ToolInfo(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema,
                server_name=cfg.name,
            )
            handle.tools.append(info)
            self._tool_index[info.qualified_name] = info

        self._servers[cfg.name] = handle
        self._server_configs[cfg.name] = cfg
        log.info("mcp.server_ready", server=cfg.name,
                 tools=[t.name for t in handle.tools])

    async def _connect_stdio(self, cfg: MCPServerConfig,
                             handle: MCPServerHandle) -> None:
        """Set up stdio transport."""
        # Merge env: inherit current env + overrides from config
        env = {**os.environ, **cfg.env} if cfg.env else None

        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=env,
            cwd=cfg.cwd,
        )

        # stdio_client is an async context manager that yields (read, write)
        transport_cm = stdio_client(params)
        read_stream, write_stream = await transport_cm.__aenter__()

        # ClientSession wraps the streams
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()

        handle.session = session
        handle._cleanup = _StackedCleanup(session, transport_cm)

    async def _connect_sse(self, cfg: MCPServerConfig,
                           handle: MCPServerHandle) -> None:
        """Set up SSE transport."""
        transport_cm = sse_client(cfg.url)
        read_stream, write_stream = await transport_cm.__aenter__()

        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()

        handle.session = session
        handle._cleanup = _StackedCleanup(session, transport_cm)

    # -- tool operations -----------------------------------------------------

    def list_tools(self) -> list[ToolInfo]:
        """Return all discovered tools across all servers."""
        return list(self._tool_index.values())

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI function-calling format."""
        return [t.to_openai_tool() for t in self._tool_index.values()]

    def get_tool(self, qualified_name: str) -> ToolInfo | None:
        """Look up a tool by its qualified name (server__tool)."""
        return self._tool_index.get(qualified_name)

    async def call_tool(
        self,
        qualified_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Call an MCP tool by qualified name.

        Returns a dict with:
            content: list of content blocks (text, image, etc.)
            is_error: bool
        """
        tool = self._tool_index.get(qualified_name)
        if tool is None:
            return {"content": [{"type": "text",
                                 "text": f"Unknown tool: {qualified_name}"}],
                    "is_error": True}

        handle = self._servers.get(tool.server_name)
        if handle is None or handle.session is None:
            return {"content": [{"type": "text",
                                 "text": f"Server not connected: {tool.server_name}"}],
                    "is_error": True}

        log.info("mcp.call_tool", tool=qualified_name,
                 args=arguments)

        try:
            result = await asyncio.wait_for(
                handle.session.call_tool(tool.name, arguments),
                timeout=timeout,
            )

            # Normalize content to dicts
            content_blocks = []
            for block in result.content:
                if hasattr(block, "text"):
                    content_blocks.append({"type": "text", "text": block.text})
                elif hasattr(block, "data"):
                    content_blocks.append({
                        "type": "image",
                        "data": block.data,
                        "mimeType": getattr(block, "mimeType", "image/png"),
                    })
                else:
                    content_blocks.append({"type": "text",
                                           "text": str(block)})

            return {
                "content": content_blocks,
                "is_error": bool(result.is_error),
            }

        except asyncio.TimeoutError:
            log.warning("mcp.call_tool.timeout", tool=qualified_name,
                        timeout=timeout)
            return {"content": [{"type": "text",
                                 "text": f"Tool call timed out after {timeout}s"}],
                    "is_error": True}
        except Exception as e:
            log.error("mcp.call_tool.error", tool=qualified_name,
                      error=str(e))
            return {"content": [{"type": "text",
                                 "text": f"Tool call failed: {e}"}],
                    "is_error": True}

    # -- helpers -------------------------------------------------------------

    def get_server_names(self) -> list[str]:
        """Return names of all connected servers."""
        return list(self._servers.keys())

    def get_server_tools(self, server_name: str) -> list[ToolInfo]:
        """Return tools for a specific server."""
        handle = self._servers.get(server_name)
        return handle.tools if handle else []

    def get_server_config(self, server_name: str) -> MCPServerConfig | None:
        """Return the stored config for a connected server, if any."""
        return self._server_configs.get(server_name)

    async def disconnect_server(self, server_name: str) -> None:
        """Disconnect and remove a single MCP server."""
        handle = self._servers.pop(server_name, None)
        if handle is None:
            return
        # Remove tools from index
        for tool in handle.tools:
            self._tool_index.pop(tool.qualified_name, None)
        # Clean up transport
        try:
            if handle._cleanup:
                await handle._cleanup.__aexit__(None, None, None)
            log.info("mcp.server_stopped", server=server_name)
        except Exception as e:
            log.warning("mcp.stop_error", server=server_name, error=str(e))
        self._server_configs.pop(server_name, None)

    async def restart_server(self, server_name: str) -> None:
        """Disconnect then reconnect a server using its stored config."""
        cfg = self._server_configs.get(server_name)
        if cfg is None:
            raise ValueError(f"No stored config for server: {server_name}")
        await self.disconnect_server(server_name)
        await self._connect_server(cfg)

    @property
    def connected(self) -> bool:
        """True if at least one server is connected."""
        return len(self._servers) > 0

    @property
    def tool_count(self) -> int:
        return len(self._tool_index)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _StackedCleanup:
    """Holds two async context managers so we can exit them in reverse order."""

    def __init__(self, session_cm: Any, transport_cm: Any) -> None:
        self._session = session_cm
        self._transport = transport_cm

    async def __aexit__(self, *args: Any) -> None:
        try:
            await self._session.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            await self._transport.__aexit__(None, None, None)
        except Exception:
            pass
