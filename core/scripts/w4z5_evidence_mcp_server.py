"""W4-Z5 parity evidence MCP server (stdio).

Publishes a distinctive `instructions` block plus one trivial tool so a live
Atlas run can prove two things at once:

1. X21: the instructions travel as a separate prompt section, not inline in
   tool descriptions (the tool description is a short pointer; the marker text
   only exists in the section).
2. X2/X3: the server belongs to a plugin, so enable/disable toggles connect
   and disconnect it through the plugin runtime's reverse-order disposers.

Run: python w4z5_evidence_mcp_server.py
"""
import asyncio

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

INSTRUCTIONS = (
    "ANCHOR_W4Z5: this guidance block is published by the w4z5-evidence MCP server. "
    "If a user asks what this server is for, reply with the token ANCHOR_W4Z5. "
    "The evidence_ping tool returns PONG_W4Z5."
)


async def _list_tools(context, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(
            name="evidence_ping",
            description="W4Z5 evidence probe; returns PONG_W4Z5.",
            input_schema={"type": "object", "properties": {}},
        )
    ])


async def _call_tool(context, params) -> types.CallToolResult:
    if params.name != "evidence_ping":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"unknown tool: {params.name}")],
            is_error=True,
        )
    return types.CallToolResult(content=[types.TextContent(type="text", text="PONG_W4Z5")])


server = Server(
    "w4z5-evidence", instructions=INSTRUCTIONS,
    on_list_tools=_list_tools, on_call_tool=_call_tool,
)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
