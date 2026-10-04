"""Atlas tools layer — MCP server management."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas.tools.mcp_client import MCPClient, ToolInfo

# O2 (H8): PEP 562 lazy re-export. Importing any ``atlas.tools.*`` submodule
# executes this package __init__, so keeping ``mcp_client`` (and the heavy mcp
# chain it drags in) out of the eager path removes that cost from every
# importer of light submodules (e.g. atlas.agent.results -> output_limits).
_LAZY_EXPORTS = {
    "MCPClient": "atlas.tools.mcp_client",
    "ToolInfo": "atlas.tools.mcp_client",
}

__all__ = ["MCPClient", "ToolInfo"]


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value  # cache: subsequent lookups skip the hook
    return value


def __dir__() -> list[str]:
    return sorted(globals().keys() | _LAZY_EXPORTS.keys())
