"""Route browser actions to the paired Atlas Chrome extension when selected."""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


def _mode() -> str:
    from atlas.config import load_user_settings
    return str((load_user_settings().get("browser") or {}).get("mode") or "standalone").lower()


def extension_controller_available(action: str) -> bool:
    del action
    if _mode() not in {"extension", "auto"}:
        return False
    from atlas.engine.tools.browser_extension_bridge import is_connected
    return is_connected()


def current_tool_call_id() -> str:
    return ""


def route_browser_tool(
    action: str, args: dict[str, Any], *, fallback: Callable[[], Any], broker: Any = None,
    enabled: bool = False, session_id: Optional[str] = None, task_id: Optional[str] = None,
    principal_id: Optional[str] = None, transport_family: Optional[str] = None,
    tool_call_id: Optional[str] = "",
) -> Any:
    del broker, session_id, principal_id, transport_family, tool_call_id
    selected = _mode()
    if not enabled or selected not in {"extension", "auto"}:
        return fallback()
    if not extension_controller_available(action):
        raise RuntimeError("Atlas browser extension is selected but disconnected. Open the Atlas extension and pair it again.")
    from atlas.engine.tools.browser_extension_bridge import call_extension
    result = call_extension(action, args, task_id=task_id)
    result["browser_target"] = "extension"
    try:
        from atlas.engine.tools.browser_tool_snapshot import _redact_browser_output
        result = _redact_browser_output(result)
    except Exception:
        pass
    return json.dumps(result, ensure_ascii=False)


def routed_browser_handler(
    action: str, args: dict[str, Any], *, fallback: Callable[[], Any], task_id: Optional[str] = None,
    session_id: Optional[str] = None, principal_id: Optional[str] = None,
    transport_family: Optional[str] = None, tool_call_id: Optional[str] = None,
) -> Any:
    del session_id, principal_id, transport_family, tool_call_id
    selected = _mode()
    if selected not in {"extension", "auto"}:
        return fallback()
    if selected == "auto" and not extension_controller_available(action):
        from atlas.engine.tools.browser_extension_bridge import has_pairing
        if has_pairing():
            raise RuntimeError("Atlas browser extension disconnected during automatic selection. Reconnect the extension to continue on the same browser.")
        return fallback()
    # Explicitly selected extensions are authoritative. Auto mode only reaches this
    # lane while the controller is connected; disconnects must not switch browsers.
    return route_browser_tool(action, args, fallback=fallback, enabled=True, task_id=task_id)
