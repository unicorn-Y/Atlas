"""Local stdio MCP fixture used by Hermes MCP end-to-end tests."""

import os
from pathlib import Path

from mcp.server import MCPServer

server = MCPServer("atlas-c1-fake")


@server.tool()
def ping() -> str:
    marker = os.environ.get("ATLAS_FAKE_MCP_MARKER")
    if marker:
        Path(marker).write_text("ping", encoding="utf-8")
    return "pong from local fake MCP"


if __name__ == "__main__":
    server.run(transport="stdio")
