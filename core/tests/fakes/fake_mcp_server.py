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


def _allowed_path(path: str) -> Path:
    root_value = os.environ.get("ATLAS_FAKE_MCP_ROOT")
    if not root_value:
        raise ValueError("ATLAS_FAKE_MCP_ROOT is not configured")
    root = Path(root_value).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("path is outside the isolated MCP root")
    return resolved


@server.tool()
def read_file(path: str) -> str:
    """Read a file only from the isolated test root."""
    return _allowed_path(path).read_text(encoding="utf-8")


@server.tool()
def write_file(path: str, content: str) -> str:
    """Write a file only under the isolated test root."""
    target = _allowed_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {target.name}"


if __name__ == "__main__":
    server.run(transport="stdio")
