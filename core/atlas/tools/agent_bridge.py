"""Shared MCP stdio server exposing Atlas-owned capabilities to external Agents."""

from __future__ import annotations

import asyncio
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

    def local_tool(name: str, description: str) -> Any:
        async def call_local(arguments: dict[str, Any]) -> str:
            result = await local_runtime.call_tool(name, arguments)
            return json.dumps(result, ensure_ascii=False, default=str)

        server.tool(name=name, description=description)(call_local)

    for definition in LOCAL_TOOLS:
        name = definition["function"]["name"]
        description = definition["function"]["description"]
        local_tool(name, description)

    def computer_tool(name: str, description: str) -> Any:
        async def call_computer(arguments: dict[str, Any]) -> str:
            result = await computer_runtime.call_tool(name, arguments)
            return json.dumps(result, ensure_ascii=False, default=str)

        server.tool(name=name, description=description)(call_computer)

    for definition in computer_runtime.get_tools_for_llm():
        name = definition["function"]["name"]
        description = definition["function"]["description"]
        computer_tool(name, description)

    async def structured_search(arguments: dict[str, Any]) -> str:
        result = await asyncio.to_thread(
            ast_grep_run,
            list(arguments.get("arguments", [])),
            cwd=str(arguments.get("cwd", ".")),
        )
        return json.dumps(result, ensure_ascii=False)

    async def repository_map(arguments: dict[str, Any]) -> str:
        result = await asyncio.to_thread(
            repo_map,
            str(arguments["path"]),
            int(arguments.get("budget", 1024)),
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
