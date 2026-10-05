"""X2: unified Computer Use + Browser runtime for Atlas.

Design (taskbook ATLAS-X2-COMPUTER-BROWSER):

- Hermes (the pinned ``hermes-agent`` dependency) IS the runtime.  This package
  wires Hermes ``tools.computer_use`` / ``tools.browser_tool*`` /
  ``agent.vault_*`` into Atlas seams: config, events, approvals, data dirs, UI.
- One computer runtime (cua-driver background-first, Atlas SendInput/UIA kept as
  the foreground executor + fallback), one browser runtime (Hermes browser
  stack; browser-use stays a separate whole-task capability).
- Legacy Atlas tool names (``computer_observe/mouse/keyboard/window/clipboard``)
  remain as aliases routed onto the new implementation.

Submodules register their tools with :func:`register_bridge`; ``__init__``
aggregates them for the agent loop and the Hermes tool bridge.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from atlas.tools.x2.context import X2Context, current_context, set_context, reset_context

log = logging.getLogger(__name__)

# Submodules that may register tools.  Missing modules are tolerated so the
# package stays importable while waves land incrementally.
_BRIDGE_MODULES = (
    "atlas.tools.x2.computer_bridge",
    "atlas.tools.x2.browser_bridge",
    "atlas.tools.x2.vault_bridge",
    "atlas.tools.x2.recordings",
)

_registered: dict[str, dict[str, Any]] = {}
_schemas: list[dict[str, Any]] = []
_loaded = False


def register_bridge(name: str, schemas: list[dict[str, Any]],
                    handler: Any) -> None:
    """Register a bridge's tool schemas and async handler ``(name, args) -> dict``."""
    _registered[name] = {"schemas": schemas, "handler": handler}
    known = {s.get("function", s).get("name") for s in _schemas}
    for schema in schemas:
        tool_name = schema.get("function", schema).get("name")
        if tool_name not in known:
            _schemas.append(schema)


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for mod_name in _BRIDGE_MODULES:
        try:
            importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("x2.bridge_load_failed", extra={"module": mod_name, "error": str(exc)})


def get_tools_for_llm() -> list[dict[str, Any]]:
    """Schemas for all X2 tools, in stable registration order."""
    _ensure_loaded()
    return list(_schemas)


def tool_names() -> set[str]:
    _ensure_loaded()
    names: set[str] = set()
    for schema in _schemas:
        inner = schema.get("function", schema)
        names.add(str(inner.get("name")))
    return names


async def call_tool(name: str, args: dict[str, Any],
                    ctx: X2Context | None = None) -> dict[str, Any]:
    """Dispatch an X2 tool call with the run context installed."""
    _ensure_loaded()
    token = set_context(ctx) if ctx is not None else None
    try:
        for entry in _registered.values():
            handler = entry["handler"]
            supported = {
                s.get("function", s).get("name") for s in entry["schemas"]
            }
            if name in supported:
                return await handler(name, args)
        raise RuntimeError(f"Unknown X2 tool: {name}")
    finally:
        if token is not None:
            reset_context(token)


def shutdown() -> None:
    """Best-effort shutdown of every loaded bridge."""
    for mod_name in _BRIDGE_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001
            log.debug("atlas.tools.x2: ignored error", exc_info=True)
            continue
        stop = getattr(mod, "shutdown", None)
        if callable(stop):
            try:
                stop()
            except Exception as exc:  # noqa: BLE001
                log.warning("x2.bridge_shutdown_failed",
                            extra={"module": mod_name, "error": str(exc)})


__all__ = [
    "X2Context",
    "call_tool",
    "current_context",
    "get_tools_for_llm",
    "register_bridge",
    "set_context",
    "reset_context",
    "shutdown",
    "tool_names",
]
