"""Shared MCP stdio server exposing Atlas-owned capabilities to external Agents."""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from typing import Any

import structlog
from mcp.server.mcpserver import MCPServer

from atlas.capabilities.coding.ast_grep import run as ast_grep_run
from atlas.capabilities.coding.repo_map import repo_map
from atlas.tools.computer_use import ComputerUseRuntime
from atlas.tools.local_execution import LOCAL_TOOLS, LocalExecutionRuntime


def create_server(
    local: LocalExecutionRuntime | None = None,
    computer: ComputerUseRuntime | None = None,
) -> MCPServer:
    """Build the shared MCP surface without duplicating Atlas tool behavior."""
    local_runtime = local or LocalExecutionRuntime()
    computer_runtime = computer or ComputerUseRuntime()
    server = MCPServer(name="Atlas capabilities", version="0.1.0")

    @server.resource(
        "atlas://capabilities",
        name="Atlas capability catalog",
        title="Atlas MCP capability catalog",
        description="Describes the local tools and execution identity exposed by this Atlas MCP process.",
        mime_type="application/json",
    )
    async def capability_catalog() -> str:
        return json.dumps({
            "server": "Atlas capabilities",
            "version": "0.1.0",
            "transport": "stdio",
            "authentication": "The MCP client launches and owns this local process; operating-system user identity is the authentication boundary.",
            "execution_identity": "The current Atlas user, with the same local execution behavior as Atlas itself.",
            "tools": [definition["function"]["name"] for definition in LOCAL_TOOLS]
                + [definition["function"]["name"] for definition in computer_runtime.get_tools_for_llm()]
                + ["coding_ast_grep", "coding_repo_map"],
            "resources": ["atlas://capabilities"],
        }, ensure_ascii=False)

    def register_runtime_tool(runtime: Any, definition: dict[str, Any]) -> None:
        function = definition["function"]
        name = function["name"]
        description = function["description"]
        schema = function.get("parameters", {"type": "object", "properties": {}})
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        async def call_runtime(**arguments: Any) -> str:
            result = await runtime.call_tool(name, arguments)
            return json.dumps(result, ensure_ascii=False, default=str)

        call_runtime.__name__ = f"call_{name}"
        call_runtime.__signature__ = inspect.Signature([
            inspect.Parameter(key, inspect.Parameter.KEYWORD_ONLY,
                              default=inspect.Parameter.empty if key in required else None,
                              annotation=Any)
            for key in properties
        ])
        server.tool(name=name, description=description)(call_runtime)
        # The MCP SDK infers only shallow schemas from Python signatures. Keep Atlas's
        # complete nested JSON schema (items, enums, bounds and required fields).
        registered = server._tool_manager.get_tool(name)
        if registered is not None:
            registered.parameters = schema

    for definition in LOCAL_TOOLS:
        register_runtime_tool(local_runtime, definition)

    for definition in computer_runtime.get_tools_for_llm():
        register_runtime_tool(computer_runtime, definition)

    async def structured_search(arguments: list[str], cwd: str = ".") -> str:
        result = await asyncio.to_thread(
            ast_grep_run,
            arguments,
            cwd=cwd,
        )
        return json.dumps(result, ensure_ascii=False)

    async def repository_map(path: str, budget: int = 1024) -> str:
        result = await asyncio.to_thread(
            repo_map,
            path,
            budget,
        )
        return json.dumps(result, ensure_ascii=False)

    server.tool(
        name="coding_ast_grep",
        description="Search or rewrite code structurally with Atlas's ast-grep integration.",
    )(structured_search)
    server.tool(
        name="coding_repo_map",
        description="Generate an Aider repository map for the given local path.",
    )(repository_map)
    return server


async def serve() -> None:
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    local = LocalExecutionRuntime()
    computer = ComputerUseRuntime()
    server = create_server(local, computer)
    try:
        await server.run_stdio_async()
    finally:
        await local.shutdown()
        await computer.shutdown()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
