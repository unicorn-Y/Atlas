"""Typed node RPC tools backed by the authenticated paired-device inbox."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable


_TOOL_DEFINITIONS = [
    ("node_status", "Read live status from an approved paired device.", "status", {}),
    ("node_notify", "Show a notification on an approved paired device.", "notification", {
        "title": {"type": "string", "maxLength": 120}, "message": {"type": "string", "maxLength": 1000},
    }),
    ("node_camera", "Capture one image from an approved paired device camera after its local permission prompt.", "camera", {
        "facing_mode": {"type": "string", "enum": ["user", "environment"]},
    }),
    ("node_location", "Read a one-time location from an approved paired device after its local permission prompt.", "location", {}),
    ("node_media", "Control media on an approved paired device: play a URL or pause, resume, stop, or set volume.", "media", {
        "action": {"type": "string", "enum": ["play", "pause", "resume", "stop", "volume"]},
        "url": {"type": "string", "maxLength": 2000}, "volume": {"type": "number", "minimum": 0, "maximum": 1},
    }),
]


async def dispatch_node_command(device_id: str, kind: str, arguments: dict[str, Any], *, timeout: float = 120) -> dict[str, Any]:
    """Queue one typed command and wait for the paired device's real response."""
    from atlas.api import device_router

    if kind not in device_router._NODE_COMMAND_CAPABILITIES:
        raise ValueError("unsupported node command")
    capability = device_router._NODE_COMMAND_CAPABILITIES[kind]
    registry = device_router.get_registry()
    device_router._require_device_capability(registry, device_id, capability)
    store = device_router._pairing_store(registry)
    if not store.has_credential(device_id):
        raise RuntimeError("设备配对凭据已撤销")
    payload = json.dumps({"kind": kind, "arguments": arguments}, ensure_ascii=False)
    command = store.create_command(device_id, payload)
    command_id = command["id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        device_router._require_device_capability(registry, device_id, capability)
        row = next((item for item in store.list_commands(device_id) if item["id"] == command_id), None)
        if row and row["status"] == "completed":
            try:
                return json.loads(row["result"])
            except (TypeError, json.JSONDecodeError):
                return {"result": row["result"]}
        await asyncio.sleep(0.5)
    raise TimeoutError(f"设备 {device_id} 在 {timeout:g} 秒内没有返回 {kind} 结果；设备可能离线或尚未处理本机权限提示")


def register_node_tools(
    register: Callable[..., Any], register_toolset_name: Callable[[str], None],
    resolve: Callable[[str], Any], toolset: str = "atlas",
) -> list[str]:
    names: list[str] = []
    for name, description, kind, properties in _TOOL_DEFINITIONS:
        parameters: dict[str, Any] = {
            "type": "object", "properties": {"device_id": {"type": "string", "minLength": 1, "maxLength": 64}, **properties},
            "required": ["device_id"], "additionalProperties": False,
        }
        if name == "node_notify":
            parameters["required"] = ["device_id", "title", "message"]
        elif name == "node_media":
            parameters["required"] = ["device_id", "action"]

        def handler(args: dict[str, Any], *, _kind: str = kind, **kwargs: Any) -> str:
            session_id = str(kwargs.get("session_id") or "")
            bound = resolve(session_id)
            if bound is None:
                return json.dumps({"error": "节点能力工具不在活动 Atlas 运行中"}, ensure_ascii=False)
            try:
                _agent, _runtime, loop = bound
                future = asyncio.run_coroutine_threadsafe(dispatch_node_command(
                    str(args["device_id"]), _kind,
                    {key: value for key, value in args.items() if key != "device_id"},
                ), loop)
                value = future.result(timeout=125)
                return json.dumps(value, ensure_ascii=False, default=str)
            except Exception as exc:  # surfaced as a tool result, never hidden
                return json.dumps({"error": str(exc)}, ensure_ascii=False)

        register(name=name, toolset=toolset, schema={"name": name, "description": description, "parameters": parameters},
                 handler=handler, is_async=False, description=description, override=True)
        register_toolset_name(name)
        names.append(name)
    return names


__all__ = ["dispatch_node_command", "register_node_tools"]
