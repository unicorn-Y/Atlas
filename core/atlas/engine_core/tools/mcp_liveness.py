"""MCP liveness details are not exposed by the Atlas MCP adapter yet."""

from __future__ import annotations


def unavailable_details(server_name: str) -> dict[str, str]:
    return {
        "state": "unknown",
        "message": f"Atlas does not expose liveness details for MCP server {server_name!r}.",
    }
