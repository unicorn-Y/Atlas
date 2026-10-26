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
from urllib.parse import quote, quote_plus

from fastapi import APIRouter, Depends, HTTPException
from mcp.types import PaginatedRequestParams
from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.mcp_resource_contract import ResourceReadRequest, ResourceTemplateReadRequest

router = APIRouter()
_RESOURCE_TIMEOUT_SECONDS = 20.0
_MAX_RESOURCE_PAGES = 100
_MAX_RESOURCES = 500
_MAX_TOTAL_RESOURCES = 1000
_MAX_RESOURCE_TEMPLATES = 500
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
_URI_TEMPLATE_EXPR = re.compile(r"\{([^{}]+)\}")
_URI_TEMPLATE_VAR = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)(?::([0-9]+))?(\*)?$")


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


def _expand_uri_template(template: str, variables: dict[str, str]) -> str:
    """Expand the common RFC 6570 operators used by MCP resource templates."""
    _check_text_limit(template, _MAX_URI_BYTES, "URI")
    if len(variables) > 100:
        raise ValueError("MCP resource templates accept at most 100 variables.")
    if any(not isinstance(name, str) or not isinstance(value, str) for name, value in variables.items()):
        raise ValueError("MCP resource template variables must be text values.")
    for name, value in variables.items():
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name):
            raise ValueError(f"Invalid MCP resource template variable: {name}")
        _check_text_limit(value, 4096, "template variable")

    def expand(match: re.Match[str]) -> str:
        expression = match.group(1)
        operator = expression[0] if expression and expression[0] in "+#./;?&" else ""
        names_text = expression[1:] if operator else expression
        specs: list[tuple[str, str, bool]] = []
        for raw in names_text.split(","):
            parsed = _URI_TEMPLATE_VAR.fullmatch(raw)
            if parsed is None:
                raise ValueError(f"Unsupported MCP URI template expression: {{{expression}}}")
            name, prefix, explode = parsed.groups()
            if name not in variables:
                raise ValueError(f"Missing MCP resource template variable: {name}")
            value = variables[name]
            if prefix:
                value = value[:int(prefix)]
            specs.append((name, value, bool(explode)))
        reserved = ":/?#[]@!$&'()*+,;="
        if operator in {"?", "&"}:
            pairs = [(name, value) for name, value, _ in specs if value != ""]
            if not pairs:
                return ""
            return ("?" if operator == "?" else "&") + "&".join(
                f"{quote_plus(name)}={quote_plus(value)}" for name, value in pairs
            )
        if operator == ";":
            return "".join(f";{quote(name)}={quote(value)}" if value else f";{quote(name)}"
                           for name, value, _ in specs)
        if operator in {"/", "."}:
            separator = operator
            return separator + separator.join(quote(value, safe="") for _, value, _ in specs)
        if operator == "#":
            return "#" + ",".join(quote(value, safe=reserved) for _, value, _ in specs)
        if operator == "+":
            return ",".join(quote(value, safe=reserved) for _, value, _ in specs)
        return ",".join(quote(value, safe="") for _, value, _ in specs)

    expanded = _URI_TEMPLATE_EXPR.sub(expand, template)
    if "{" in expanded or "}" in expanded:
        raise ValueError("MCP URI template contains an unsupported expression.")
    _check_text_limit(expanded, _MAX_URI_BYTES, "URI")
    return expanded


def _template_fields(item: Any) -> dict[str, Any]:
    uri_template = getattr(item, "uriTemplate", None)
    if not isinstance(uri_template, str) or not uri_template:
        raise ValueError("MCP returned a resource template without a URI template.")
    _check_text_limit(uri_template, _MAX_URI_BYTES, "URI")
    return {
        "uri_template": uri_template,
        "name": _metadata_text(item, "name", _MAX_NAME_BYTES) or "",
        "title": _metadata_text(item, "title", _MAX_TITLE_BYTES),
        "description": _metadata_text(item, "description", _MAX_DESCRIPTION_BYTES),
        "mime_type": _metadata_text(item, "mimeType", _MAX_MIME_TYPE_BYTES),
    }


async def _list_template_page(client: Any, server_name: str, cursor: str | None) -> dict[str, Any]:
    pages = await asyncio.wait_for(client.list_resource_templates(server_name, cursor), timeout=_RESOURCE_TIMEOUT_SECONDS)
    page = pages.get(server_name, {}) if isinstance(pages, dict) else {}
    if not isinstance(page, dict):
        raise ValueError("MCP resource template response is malformed.")
    if page.get("error"):
        raise RuntimeError(_CONTROL_CHARS.sub(" ", str(page["error"])).strip()[:500])
    raw = page.get("resourceTemplates", [])
    if not isinstance(raw, list) or len(raw) > _MAX_RESOURCE_TEMPLATES:
        raise ResourceLimitExceeded(f"MCP resource template page exceeds {_MAX_RESOURCE_TEMPLATES} entries.")
    templates = []
    for item in raw:
        if isinstance(item, dict):
            # MCPClient converts SDK dataclasses to protocol-shaped dictionaries.
            values = dict(item)
            class TemplateRow:
                pass
            row = TemplateRow()
            for source, target in (("uriTemplate", "uriTemplate"), ("name", "name"), ("title", "title"),
                                   ("description", "description"), ("mimeType", "mimeType")):
                setattr(row, target, values.get(source))
            templates.append(_template_fields(row))
        else:
            templates.append(_template_fields(item))
    next_cursor = page.get("nextCursor")
    if next_cursor is not None:
        next_cursor = str(next_cursor)
        _check_text_limit(next_cursor, _MAX_CURSOR_BYTES, "pagination cursor")
    return {"templates": templates, "next_cursor": next_cursor}


async def list_mcp_resource_templates(
    services: AppServices, *, server_name: str | None = None, cursor: str | None = None,
) -> dict[str, Any]:
    client = _mcp_client(services)
    if client is None:
        return {"available": False, "error": "MCP runtime is unavailable.", "servers": []}
    if cursor:
        _check_text_limit(cursor, _MAX_CURSOR_BYTES, "pagination cursor")
    try:
        statuses = _runtime_rows(client)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="MCP runtime status is unavailable.") from exc
    selected = [row for row in statuses if server_name is None or str(row.get("name")) == server_name]
    if server_name and not selected:
        raise HTTPException(status_code=404, detail="MCP server is not configured.")
    rows = []
    for status in selected:
        name = str(status["name"])
        row = {"name": name, "enabled": bool(status.get("enabled", False)),
               "connected": bool(status.get("connected", False)), "state": str(status.get("state") or "unknown"),
               "template_state": "disconnected", "templates": [], "next_cursor": None, "error": None}
        session = _connected_session(client, name)
        if session is None:
            row["error"] = _CONTROL_CHARS.sub(" ", str(status.get("blocking_reason") or "MCP 服务当前未连接。"))[:500]
            rows.append(row); continue
        row["connected"] = True
        if not callable(getattr(session, "list_resource_templates", None)):
            row["template_state"] = "unsupported"; row["error"] = "此 MCP 服务未提供资源模板接口。"
            rows.append(row); continue
        try:
            page = await _list_template_page(client, name, cursor if server_name else None)
            row.update(page); row["template_state"] = "ready"
        except TimeoutError:
            row["template_state"] = "timeout"; row["error"] = "MCP 资源模板请求超时。"
        except ResourceLimitExceeded as exc:
            row["template_state"] = "limit_exceeded"; row["error"] = str(exc)[:500]
        except Exception as exc:  # noqa: BLE001
            row["template_state"] = "error"; row["error"] = _CONTROL_CHARS.sub(" ", str(exc))[:500]
        rows.append(row)
    return {"available": True, "servers": rows}


async def read_mcp_resource_template(
    req: ResourceTemplateReadRequest, services: AppServices,
) -> dict[str, Any]:
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
        raise HTTPException(status_code=409, detail="MCP server is not connected.")
    if not callable(getattr(session, "list_resource_templates", None)) or not callable(
        getattr(session, "read_resource", None)
    ):
        raise HTTPException(status_code=409, detail="MCP server does not support resource templates.")
    cursor: str | None = None
    seen: set[str] = set()
    advertised = False
    for _ in range(_MAX_RESOURCE_PAGES):
        try:
            page = await _list_template_page(client, req.server_name, cursor)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="MCP resource template lookup timed out.") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc
        if any(item["uri_template"] == req.uri_template for item in page["templates"]):
            advertised = True; break
        next_cursor = page.get("next_cursor")
        if not next_cursor:
            break
        if next_cursor in seen:
            raise HTTPException(status_code=502, detail="MCP returned a repeated resource template cursor.")
        seen.add(next_cursor); cursor = next_cursor
    if not advertised:
        raise HTTPException(status_code=404, detail="URI template is not currently advertised by this MCP server.")
    try:
        uri = _expand_uri_template(req.uri_template, req.variables)
    except (ValueError, ResourceLimitExceeded) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        result = await asyncio.wait_for(session.read_resource(uri), timeout=_RESOURCE_TIMEOUT_SECONDS)
        contents = []
        total_size = 0
        for item in list(getattr(result, "contents", []) or [])[:_MAX_READ_CONTENTS]:
            content, total_size = _checked_content(item, uri, total_size)
            contents.append(content)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="MCP resource template read timed out.") from exc
    except ResourceLimitExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        message, _, _ = _error_details(exc)
        raise HTTPException(status_code=502, detail=message) from exc
    return {"server_name": req.server_name, "uri_template": req.uri_template, "uri": uri, "contents": contents}
