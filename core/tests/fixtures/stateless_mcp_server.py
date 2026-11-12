"""Stateless Streamable HTTP MCP app used by handshake integration tests."""

from mcp.server import MCPServer

server = MCPServer("atlas-stateless-fixture", version="1.0")


@server.tool()
def ping() -> str:
    """Return a deterministic response for the transport acceptance test."""
    return "pong"


app = server.streamable_http_app(
    streamable_http_path="/mcp", json_response=True, stateless_http=True,
)


# A pre-2026-07-28 server: it answers the legacy `initialize` handshake but has
# no `server/discover` method, so the client must fall back instead of failing.
legacy = MCPServer("atlas-legacy-fixture", version="1.0")


@legacy.tool()
def ping() -> str:  # noqa: F811 - separate server instance
    """Return a deterministic response for the transport acceptance test."""
    return "pong"


async def _no_discover(ctx, params):
    from mcp.shared.exceptions import MCPError
    from mcp.types import METHOD_NOT_FOUND

    raise MCPError(code=METHOD_NOT_FOUND, message="Method not found")


from mcp.types import RequestParams  # noqa: E402 - fixture-local import

legacy._lowlevel_server.add_request_handler(
    "server/discover", RequestParams, _no_discover,
)

legacy_app = legacy.streamable_http_app(
    streamable_http_path="/mcp", json_response=True, stateless_http=False,
)
