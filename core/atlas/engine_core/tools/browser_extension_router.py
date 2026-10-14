# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd (MIT).
"""Browser-extension controller routing is unavailable in the standalone Atlas engine."""

from __future__ import annotations

from typing import Any, Callable, Optional


def extension_controller_available(action: str) -> bool:
    return False


def current_tool_call_id() -> str:
    return ""


def route_browser_tool(
    action: str, args: dict[str, Any], *, fallback: Callable[[], Any], broker: Any = None,
    enabled: bool = False, session_id: Optional[str] = None, task_id: Optional[str] = None,
    principal_id: Optional[str] = None, transport_family: Optional[str] = None,
    tool_call_id: Optional[str] = "",
) -> Any:
    return fallback()


def routed_browser_handler(
    action: str, args: dict[str, Any], *, fallback: Callable[[], Any], task_id: Optional[str] = None,
    session_id: Optional[str] = None, principal_id: Optional[str] = None,
    transport_family: Optional[str] = None, tool_call_id: Optional[str] = None,
) -> Any:
    return fallback()
