"""Read MCP resources exposed by Atlas' existing connected MCP sessions.

Runtime sources: ``atlas.tools.mcp_client.MCPClient._servers`` stores connected
``MCPServerHandle.session`` instances; MCP Python SDK 2.1.1 provides
``ClientSession.list_resources`` and ``ClientSession.read_resource``. This
router uses those protocol methods only and never returns tool input schemas.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from mcp.types import PaginatedRequestParams
from pydantic import BaseModel, Field, field_validator

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()
_RESOURCE_TIMEOUT_SECONDS = 20.0
_MAX_RESOURCE_PAGES = 100
_MAX_RESOURCES = 500
_MAX_TOTAL_RESOURCES = 1000
_MAX_READ_CONTENTS = 128
_MAX_READ_BYTES = 5 * 1024 * 1024
_MAX_CURSOR_BYTES = 4096
_MAX_URI_BYTES = 4096
_MAX_NAME_BYTES = 256
_MAX_TITLE_BYTES = 256
_MAX_DESCRIPTION_BYTES = 2048
_MAX_MIME_TYPE_BYTES = 256
_METHOD_NOT_FOUND = -32601
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ResourceReadRequest(BaseModel):
    server_name: str = Field(min_length=1, max_length=256)
    uri: str = Field(min_length=1, max_length=_MAX_URI_BYTES)


class McpServerSettingsPatch(BaseModel):
    enabled: bool | None = None
    allowed_tools: list[str] | None = None
    headers: dict[str, str] | None = None

    @field_validator("allowed_tools")
    @classmethod
    def validate_allowed_tools(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("allowed_tools entries must be non-empty tool names")
        return value

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and any(
            not key.strip() or any(char in key + item for char in "\r\n")
            for key, item in value.items()
        ):
            raise ValueError("header names and values cannot be empty or contain line breaks")
        return value


class ResourceLimitExceeded(ValueError):
    """An MCP resource response exceeds Atlas' response-size limits."""


def _check_text_limit(value: str, limit: int, field_name: str) -> int:
    """Return UTF-8 size without encoding strings already over the limit."""
    labels = {
        "URI": "URI",
        "content URI": "内容 URI",
        "name": "名称",
        "title": "标题",
        "description": "说明",
        "mimeType": "MIME 类型",
        "text content": "文本内容",
        "pagination cursor": "分页游标",
    }
    label = labels.get(field_name, field_name)
    if len(value) > limit:
        raise ResourceLimitExceeded(f"MCP 资源{label}超过 {limit} 字节上限。")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"MCP resource {field_name} is not valid UTF-8 text.") from exc
    if size > limit:
        raise ResourceLimitExceeded(f"MCP 资源{label}超过 {limit} 字节上限。")
    return size


def _metadata_text(item: Any, attribute: str, limit: int) -> str | None:
    value = getattr(item, attribute, None)
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    _check_text_limit(value, limit, attribute)
    return value


def _resource_size(item: Any) -> int | None:
    size = getattr(item, "size", None)
    if size is None:
        return None
    if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > (2**63 - 1):
        raise ResourceLimitExceeded("MCP 资源声明的 size 元数据超出允许范围。")
    return size


def _checked_content(item: Any, uri: str, current_size: int) -> tuple[dict[str, Any], int]:
    content_uri = getattr(item, "uri", uri)
    if not isinstance(content_uri, str):
        content_uri = str(content_uri)
    _check_text_limit(content_uri, _MAX_URI_BYTES, "content URI")
    mime_type = _metadata_text(item, "mimeType", _MAX_MIME_TYPE_BYTES)
    common = {"uri": content_uri, "mime_type": mime_type}
    if hasattr(item, "text"):
        text = item.text
        if not isinstance(text, str):
            raise ValueError("MCP returned a non-text value for a text resource.")
        size = _check_text_limit(text, _MAX_READ_BYTES, "text content")
        if current_size + size > _MAX_READ_BYTES:
            raise ResourceLimitExceeded(
                f"MCP 单次资源读取内容超过 {_MAX_READ_BYTES} 字节上限。"
            )
        return {**common, "type": "text", "text": text}, current_size + size
    if hasattr(item, "blob"):
        blob = item.blob
        if not isinstance(blob, str):
            raise ValueError("MCP returned a non-Base64 value for a binary resource.")
        max_encoded_bytes = ((_MAX_READ_BYTES + 2) // 3) * 4
        if len(blob) > max_encoded_bytes:
            raise ResourceLimitExceeded(
                f"MCP 单次资源读取内容超过 {_MAX_READ_BYTES} 字节上限。"
            )
        try:
            decoded = base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("MCP returned invalid Base64 binary content.") from exc
        size = len(decoded)
        if current_size + size > _MAX_READ_BYTES:
            raise ResourceLimitExceeded(
                f"MCP 单次资源读取内容超过 {_MAX_READ_BYTES} 字节上限。"
            )
        return {**common, "type": "blob", "base64": blob}, current_size + size
    raise ValueError("MCP returned an unsupported resource content type.")


def _mcp_client(services: AppServices) -> Any:
    client = services.mcp_client
    if client is None:
        from atlas import server

        client = getattr(server, "mcp_client", None)
    return client


def _runtime_rows(client: Any) -> list[dict[str, Any]]:
    get_status = getattr(client, "get_runtime_status", None)
    if not callable(get_status):
        return []
    value = get_status()
    rows = value.get("servers", []) if isinstance(value, dict) else []
    return [row for row in rows if isinstance(row, dict) and row.get("name")]


def _connected_session(client: Any, server_name: str) -> Any | None:
    """Resolve only a live session already owned by the Atlas MCP runtime."""
    handles = getattr(client, "_servers", None)
    if not isinstance(handles, dict):
        return None
    handle = handles.get(server_name)
    session = getattr(handle, "session", None)
    if session is None:
        return None
    if not callable(getattr(session, "list_resources", None)) or not callable(
        getattr(session, "read_resource", None)
    ):
        return None
    return session


def _supports_resources(session: Any) -> bool:
    capabilities = getattr(session, "server_capabilities", None)
    return capabilities is not None and getattr(capabilities, "resources", None) is not None


def _error_details(exc: BaseException) -> tuple[str, int | None, bool]:
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        nested = getattr(exc, "error", None)
        code = getattr(nested, "code", None)
    if not isinstance(code, int):
        code = None
    message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
    safe_message = _CONTROL_CHARS.sub(" ", str(message)).strip()[:500]
    unsupported = code == _METHOD_NOT_FOUND
    if unsupported:
        safe_message = "此 MCP 服务未提供资源读取方法。"
    elif not safe_message:
        safe_message = "MCP 服务请求失败。"
    return safe_message, code, unsupported


async def _list_all_resources(
    session: Any, *, resource_limit: int = _MAX_RESOURCES,
) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(_MAX_RESOURCE_PAGES):
        params = PaginatedRequestParams(cursor=cursor) if cursor else None
        result = await asyncio.wait_for(
            session.list_resources(params=params), timeout=_RESOURCE_TIMEOUT_SECONDS,
        )
        for item in getattr(result, "resources", []) or []:
            uri = getattr(item, "uri", None)
            if not isinstance(uri, str) or not uri:
                continue
            if len(resources) >= resource_limit:
                raise ResourceLimitExceeded(
                    f"MCP 资源列表超过本次响应中此服务 {resource_limit} 项的上限。"
                )
            _check_text_limit(uri, _MAX_URI_BYTES, "URI")
            resources.append({
                "uri": uri,
                "name": _metadata_text(item, "name", _MAX_NAME_BYTES) or "",
                "title": _metadata_text(item, "title", _MAX_TITLE_BYTES),
                "description": _metadata_text(item, "description", _MAX_DESCRIPTION_BYTES),
                "mime_type": _metadata_text(item, "mimeType", _MAX_MIME_TYPE_BYTES),
                "size": _resource_size(item),
            })
        next_cursor = getattr(result, "nextCursor", None)
        if not next_cursor:
            return resources
        next_cursor = str(next_cursor)
        _check_text_limit(next_cursor, _MAX_CURSOR_BYTES, "pagination cursor")
        if next_cursor in seen_cursors:
            raise RuntimeError("MCP 服务返回了重复的资源分页游标。")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise ResourceLimitExceeded(f"MCP 资源列表超过每个服务 {_MAX_RESOURCE_PAGES} 页的安全上限。")


async def _list_server_resources(
    client: Any, status: dict[str, Any], *, resource_limit: int = _MAX_RESOURCES,
) -> dict[str, Any]:
    name = str(status["name"])
    row: dict[str, Any] = {
        "name": name,
        "enabled": bool(status.get("enabled", False)),
        "connected": bool(status.get("connected", False)),
        "state": str(status.get("state") or "unknown"),
        "resource_state": "disconnected",
        "resources": [],
        "error": None,
        "error_code": None,
    }
    session = _connected_session(client, name)
    if session is None:
        row["error"] = _CONTROL_CHARS.sub(
            " ", str(status.get("blocking_reason") or "MCP 服务当前未连接。"),
        ).strip()[:500]
        return row
    row["connected"] = True
    if not _supports_resources(session):
        row["resource_state"] = "unsupported"
        row["error"] = "此 MCP 服务未声明 resources capability。"
        return row
    if resource_limit <= 0:
        row["resource_state"] = "limit_exceeded"
        row["error"] = f"所有 MCP 服务合计最多返回 {_MAX_TOTAL_RESOURCES} 项资源。"
        return row
    try:
        row["resources"] = await asyncio.wait_for(
            _list_all_resources(session, resource_limit=min(_MAX_RESOURCES, resource_limit)),
            timeout=_RESOURCE_TIMEOUT_SECONDS,
        )
        row["resource_state"] = "ready"
    except TimeoutError:
        row["resource_state"] = "timeout"
        row["error"] = "请求资源列表超时。"
    except ResourceLimitExceeded as exc:
        row["resource_state"] = "limit_exceeded"
        row["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 — isolate one server's protocol error from the rest
        message, code, unsupported = _error_details(exc)
        row["resource_state"] = "unsupported" if unsupported else "error"
        row["error"] = message
        row["error_code"] = code
    return row


@router.get("/api/mcp/resources")
async def list_mcp_resources(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """List resources advertised by live sessions and expose current lifecycle state."""
    client = _mcp_client(services)
    if client is None:
        return {"available": False, "error": "MCP runtime is unavailable.", "servers": []}
    try:
        statuses = _runtime_rows(client)
    except Exception as exc:  # noqa: BLE001 — report runtime status without leaking config
        raise HTTPException(status_code=503, detail="MCP runtime status is unavailable.") from exc
    servers: list[dict[str, Any]] = []
    total_resources = 0
    for status in statuses:
        remaining = _MAX_TOTAL_RESOURCES - total_resources
        row = await _list_server_resources(
            client, status, resource_limit=min(_MAX_RESOURCES, remaining),
        )
        total_resources += len(row["resources"])
        servers.append(row)
    return {"available": True, "servers": servers}


@router.post("/api/mcp/resources/read")
async def read_mcp_resource(
    req: ResourceReadRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Read one URI that the selected connected server currently advertises."""
    client = _mcp_client(services)
    if client is None:
        raise HTTPException(status_code=503, detail="MCP runtime is unavailable.")
    try:
        statuses = _runtime_rows(client)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="MCP runtime status is unavailable.") from exc
    status = next((item for item in statuses if str(item.get("name")) == req.server_name), None)
    if status is None:
        raise HTTPException(status_code=404, detail="MCP server is not configured.")
    session = _connected_session(client, req.server_name)
    if session is None:
        state = str(status.get("state") or "disconnected")
        raise HTTPException(status_code=409, detail=f"MCP server is not connected (state: {state}).")
    if not _supports_resources(session):
        raise HTTPException(status_code=409, detail="MCP server did not declare the resources capability.")
    try:
        _check_text_limit(req.uri, _MAX_URI_BYTES, "URI")
    except ResourceLimitExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    try:
        advertised = await asyncio.wait_for(
            _list_all_resources(session), timeout=_RESOURCE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="MCP resource listing timed out.") from exc
    except ResourceLimitExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        message, _, unsupported = _error_details(exc)
        code = 409 if unsupported else 502
        raise HTTPException(status_code=code, detail=message) from exc
    if not any(item["uri"] == req.uri for item in advertised):
        raise HTTPException(status_code=404, detail="URI is not currently advertised by this MCP server.")

    try:
        result = await asyncio.wait_for(
            session.read_resource(req.uri), timeout=_RESOURCE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="MCP resource read timed out.") from exc
    except Exception as exc:  # noqa: BLE001
        message, _, unsupported = _error_details(exc)
        code = 409 if unsupported else 502
        raise HTTPException(status_code=code, detail=message) from exc

    raw_contents = getattr(result, "contents", []) or []
    if len(raw_contents) > _MAX_READ_CONTENTS:
        raise HTTPException(
            status_code=413,
            detail=f"MCP 资源响应内容块超过每次读取 {_MAX_READ_CONTENTS} 项的上限。",
        )
    contents: list[dict[str, Any]] = []
    total_bytes = 0
    try:
        for item in raw_contents:
            content, total_bytes = _checked_content(item, req.uri, total_bytes)
            contents.append(content)
    except ResourceLimitExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "server_name": req.server_name,
        "uri": req.uri,
        "contents": contents,
    }


def _save_mcp_settings(server_name: str, patch: dict[str, Any]) -> None:
    """Persist a narrow MCP settings patch into the base atlas.toml."""
    import copy

    import tomli_w

    from atlas import config as config_module
    from atlas.config import get_config

    data = copy.deepcopy(get_config().base_raw)
    servers = data.setdefault("tools", {}).setdefault("servers", {})
    config = servers.get(server_name)
    if not isinstance(config, dict):
        raise KeyError(server_name)
    config.update(patch)
    if "enabled" in patch:
        tools = data.setdefault("tools", {})
        auto_start = list(tools.get("auto_start", []) or [])
        if auto_start:
            if patch["enabled"] and server_name not in auto_start:
                auto_start.append(server_name)
            elif not patch["enabled"]:
                auto_start = [name for name in auto_start if name != server_name]
        tools["auto_start"] = auto_start
    path = config_module.CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(tomli_w.dumps(data), encoding="utf-8")
    temporary.replace(path)
    config_module.reload_config()


def _configured_headers(server_name: str) -> dict[str, Any] | None:
    from atlas.config import get_config

    servers = get_config().get("tools.servers", {}) or {}
    value = servers.get(server_name)
    return value.get("headers", {}) if isinstance(value, dict) else None


@router.get("/api/mcp/settings/servers")
async def list_mcp_server_settings(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Return configured MCP policy without returning header secret values."""
    from atlas.config import get_config

    client = _mcp_client(services)
    rows = {str(row["name"]): row for row in _runtime_rows(client)}
    servers = get_config().get("tools.servers", {}) or {}
    result = []
    for name, config in servers.items():
        if not isinstance(config, dict):
            continue
        result.append({
            **rows.get(name, {"name": name, "connected": False, "state": "not_started", "tool_count": 0}),
            "enabled": rows.get(name, {}).get("enabled", bool(config.get("enabled", True))),
            "transport": config.get("transport", "stdio"),
            "allowed_tools": config.get("allowed_tools"),
            "header_names": sorted(str(key) for key in (config.get("headers") or {})),
        })
    return {"servers": result}


@router.patch("/api/mcp/settings/servers/{server_name}")
async def update_mcp_server_settings(
    server_name: str,
    req: McpServerSettingsPatch,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Update enabled state, per-server tool allowlist, or remote request headers."""
    from atlas.tools.mcp_client import _parse_server_configs

    client = _mcp_client(services)
    if client is None:
        raise HTTPException(status_code=503, detail="MCP runtime is unavailable")
    patch = req.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No MCP settings were supplied")
    if "headers" in patch and _configured_headers(server_name) is None:
        raise HTTPException(status_code=404, detail=f"MCP server is not configured: {server_name}")
    if server_name in getattr(client, "_servers", {}):
        await client.disconnect_server(server_name)
    try:
        _save_mcp_settings(server_name, patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"MCP server is not configured: {server_name}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="MCP settings could not be saved") from exc

    client._configured_configs = {config.name: config for config in _parse_server_configs()}
    config = client._configured_configs.get(server_name)
    if config is None:
        raise HTTPException(status_code=404, detail=f"MCP server is not configured: {server_name}")
    if config.enabled:
        try:
            await client._connect_server(config)
        except Exception:
            pass  # The persisted config and runtime status retain the actionable safe diagnostic.
    else:
        client._server_status.setdefault(server_name, {"name": server_name}).update({
            "enabled": False, "connected": False, "state": "disabled",
            "tool_count": 0, "blocking_reason": "server is disabled",
        })
    status = next(
        (row for row in client.get_runtime_status().get("servers", []) if row.get("name") == server_name),
        {},
    )
    return {
        "name": server_name,
        "enabled": config.enabled,
        "connected": status.get("connected", False),
        "state": status.get("state", "not_started"),
        "tool_count": status.get("tool_count", 0),
        "diagnostic": status.get("blocking_reason"),
    }
