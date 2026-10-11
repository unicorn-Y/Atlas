"""Persistent MCP settings and prompt/template protocol operations.

Mount this router alongside tools_router; /api/mcp/configs deliberately avoids
the legacy connected-only /api/mcp/servers routes.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from mcp.types import PaginatedRequestParams
from pydantic import BaseModel, Field, model_validator

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.mcp_resources_router import ResourceLimitExceeded, _checked_content, _connected_session, _mcp_client, _runtime_rows
from atlas.api.skills_market_router import _require_trusted_origin
from atlas.api.tools_router import _persist_mcp_server_config
from atlas.config import get_config
from atlas.tools.mcp_client import MCPServerConfig

router = APIRouter(tags=["mcp-settings"], dependencies=[Depends(_require_trusted_origin)])
Services = Annotated[AppServices, Depends(get_app_services)]
_lock = asyncio.Lock()
_jobs: dict[str, asyncio.Task] = {}
_MASK = "********"


class ServerSettings(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    command: str = Field(default="", max_length=2000)
    args: list[str] = Field(default_factory=list, max_length=100)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str = Field(default="", max_length=4096)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    startup_timeout: float = Field(default=30, ge=1, le=300)
    oauth: bool = False
    oauth_scope: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "stdio":
            if not self.command.strip() or self.oauth:
                raise ValueError("stdio requires a command and cannot use OAuth")
        else:
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("Remote MCP requires an HTTP(S) URL without embedded credentials or fragment")
            if self.oauth and parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("OAuth requires HTTPS or loopback HTTP")
            if self.oauth and any(key.lower() == "authorization" for key in self.headers):
                raise ValueError("OAuth cannot be combined with a static Authorization header")
        for mapping in (self.env, self.headers):
            if len(mapping) > 100 or any(not key or len(key) > 256 or len(value) > 16000 or "\r" in key or "\n" in key for key, value in mapping.items()):
                raise ValueError("Too many or invalid environment/header entries")
        if any("\r" in value or "\n" in value for value in self.headers.values()):
            raise ValueError("Headers must not contain newlines")
        return self


def _saved() -> dict[str, dict[str, Any]]:
    rows = get_config().get("tools.servers", {}) or {}
    return {name: dict(value) for name, value in rows.items() if isinstance(value, dict)}


def _row(name, config, client):
    status = next((row for row in _runtime_rows(client) if row["name"] == name), {}) if client else {}
    safe = {**asdict(MCPServerConfig(name=name)), **config}
    for key in ("env", "headers"):
        safe[key] = {name: _MASK for name in config.get(key, {})}
    from atlas.api.mcp_oauth import AUTH_STATUS
    return {**safe, "name": name, "connected": status.get("connected", False),
            "state": status.get("state", "disabled" if not config.get("enabled", True) else "stopped"),
            "tool_count": status.get("tool_count", 0), "tools": [tool.qualified_name for tool in client.get_server_tools(name)] if client else [],
            "blocking_reason": status.get("blocking_reason"), "auth": AUTH_STATUS.get(name),
            "connecting": name in _jobs and not _jobs[name].done()}


async def _disconnect(client, name):
    if client is None:
        raise HTTPException(503, "MCP runtime is unavailable")
    task = _jobs.pop(name, None)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    tool_names = {tool.qualified_name for tool in client.get_server_tools(name)}
    await client.disconnect_server(name)
    from atlas.engine.hermes_runtime import HermesRuntime
    await asyncio.to_thread(HermesRuntime.unregister_atlas_mcp_server, name, tool_names)
    from atlas.api.mcp_oauth import AUTH_STATUS
    AUTH_STATUS.pop(name, None)


def _launch(client, name, config):
    async def connect():
        from atlas.api.mcp_oauth import AUTH_STATUS
        try:
            await client.connect_config(MCPServerConfig(name=name, **config))
            if config.get("oauth"):
                from atlas.api.mcp_oauth import CredentialStorage
                tokens = await CredentialStorage(name, config["url"], config.get("oauth_scope", "")).get_tokens()
                AUTH_STATUS[name] = {"state": "authenticated" if tokens else "connected",
                                     "message": "OAuth 已授权并连接" if tokens else "已连接；服务尚未要求 OAuth 授权"}
        except asyncio.CancelledError:
            raise
        except Exception:
            # SDK/provider errors can contain credentials or authorization codes.
            client._server_status.setdefault(name, {"name": name}).update(
                state="failed", connected=False, blocking_reason="连接失败；请检查配置、服务及授权后重新连接")
            if config.get("oauth"):
                AUTH_STATUS[name] = {"state": "failed", "message": "OAuth 连接失败或授权超时；可重新授权"}
    _jobs[name] = asyncio.create_task(connect())


async def _write(name, payload, services, create=False):
    client = _mcp_client(services)
    if client is None:
        raise HTTPException(503, "MCP runtime is unavailable")
    async with _lock:
        saved = _saved()
        if create and name in saved:
            raise HTTPException(409, "Server already exists")
        if create and name in client._configured_configs:
            raise HTTPException(409, "Server name is already owned by the runtime or a plugin")
        if not create and name not in saved:
            raise HTTPException(404, "Server not found")
        if payload.name != name:
            raise HTTPException(422, "Server name is immutable; create another entry to rename")
        old = saved.get(name, {})
        value = payload.model_dump(exclude={"name"})
        for key in ("env", "headers"):
            for field, content in value[key].items():
                if content == _MASK:
                    if field not in old.get(key, {}):
                        raise HTTPException(422, "A masked value has no saved credential")
                    value[key][field] = old[key][field]
        if value["oauth"]:
            from atlas.api.mcp_oauth import CredentialStorage
            CredentialStorage(name, value["url"], value["oauth_scope"])
        try:
            await _disconnect(client, name)
            _persist_mcp_server_config(name, value)
        except Exception as exc:
            if old.get("enabled", True) and old:
                _launch(client, name, old)
            raise HTTPException(500, "MCP configuration could not be saved; previous connection is being restored") from exc
        if old.get("oauth") and (not value["oauth"] or old.get("url") != value["url"] or old.get("oauth_scope", "") != value["oauth_scope"]):
            from atlas.api.mcp_oauth import CredentialStorage
            await CredentialStorage(name, old["url"], old.get("oauth_scope", "")).clear()
        client._configured_configs[name] = MCPServerConfig(name=name, **value)
        client._server_status[name] = {"name": name, "enabled": value["enabled"], "configured": True,
                                     "transport": value["transport"], "state": "starting" if value["enabled"] else "disabled", "connected": False}
        if value["enabled"]:
            _launch(client, name, value)
        return _row(name, value, client)


@router.get("/api/mcp/configs")
async def list_configs(services: Services):
    return {"servers": [_row(name, config, _mcp_client(services)) for name, config in _saved().items()],
            "scope": "user", "project_scope_supported": False}


@router.post("/api/mcp/configs", status_code=201)
async def create_config(payload: ServerSettings, services: Services):
    return await _write(payload.name, payload, services, create=True)


@router.put("/api/mcp/configs/{name}")
async def update_config(name: str, payload: ServerSettings, services: Services):
    return await _write(name, payload, services)


@router.post("/api/mcp/configs/{name}/reconnect")
async def reconnect(name: str, services: Services):
    saved = _saved().get(name)
    if saved is None:
        raise HTTPException(404, "Server not found")
    return await _write(name, ServerSettings(name=name, **{**saved, "enabled": True}), services)


@router.post("/api/mcp/configs/{name}/reauthorize")
async def reauthorize(name: str, services: Services):
    from atlas.api.mcp_oauth import CredentialStorage
    saved = _saved().get(name)
    if not saved or not saved.get("oauth"):
        raise HTTPException(409, "Server does not use OAuth")
    async with _lock:
        await _disconnect(_mcp_client(services), name)
        await CredentialStorage(name, saved["url"], saved.get("oauth_scope", "")).clear()
    return await reconnect(name, services)


@router.delete("/api/mcp/configs/{name}")
async def delete_config(name: str, services: Services):
    async with _lock:
        saved = _saved().get(name)
        if saved is None:
            raise HTTPException(404, "Server not found")
        await _disconnect(_mcp_client(services), name)
        if saved.get("oauth"):
            from atlas.api.mcp_oauth import CredentialStorage
            await CredentialStorage(name, saved["url"], saved.get("oauth_scope", "")).clear()
        _persist_mcp_server_config(name, None)
        client = _mcp_client(services)
        client._configured_configs.pop(name, None)
        client._server_status.pop(name, None)
    return {"deleted": True, "name": name}


class ProtocolRequest(BaseModel):
    server_name: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=4096)
    arguments: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_arguments(self):
        if len(self.arguments) > 100 or sum(len(key.encode()) + len(value.encode()) for key, value in self.arguments.items()) > 64000:
            raise ValueError("MCP arguments exceed safety limits")
        return self


def _session(services, name):
    session = _connected_session(_mcp_client(services), name)
    if session is None:
        raise HTTPException(409, "MCP server is not connected")
    return session


async def _catalog(session, kind):
    items, cursor, seen = [], None, set()
    method = session.list_prompts if kind == "prompts" else session.list_resource_templates
    attribute = "prompts" if kind == "prompts" else "resourceTemplates"
    for _ in range(20):
        response = await _protocol_call(method(params=PaginatedRequestParams(cursor=cursor) if cursor else None))
        values = getattr(response, attribute, None)
        if values is None and kind != "prompts":
            values = getattr(response, "resource_templates", [])
        items.extend(item.model_dump(mode="json", by_alias=True) for item in (values or []))
        if len(items) > 500 or len(json.dumps(items).encode()) > 1024 * 1024:
            raise HTTPException(413, "MCP catalog exceeds safety limit")
        cursor = getattr(response, "next_cursor", None) or getattr(response, "nextCursor", None)
        if not cursor:
            return items
        if cursor in seen:
            raise HTTPException(502, "MCP returned a repeated cursor")
        seen.add(cursor)
    raise HTTPException(413, "MCP catalog exceeds page limit")


async def _protocol_call(operation):
    try:
        return await asyncio.wait_for(operation, 20)
    except TimeoutError as exc:
        raise HTTPException(504, "MCP protocol request timed out") from exc
    except Exception as exc:
        raise HTTPException(502, "MCP server rejected the request or returned invalid content") from exc


@router.get("/api/mcp/catalog")
async def protocol_catalog(services: Services):
    result = []
    for status in _runtime_rows(_mcp_client(services)):
        row = {"name": status["name"], "prompts": [], "templates": [], "errors": {}}
        session = _connected_session(_mcp_client(services), status["name"])
        if session is not None:
            for kind, key in (("prompts", "prompts"), ("templates", "templates")):
                try:
                    row[key] = await asyncio.wait_for(_catalog(session, kind), 20)
                except Exception:
                    row["errors"][key] = "服务未支持此接口或请求失败/超时"
        else:
            row["errors"]["connection"] = "服务未连接"
        result.append(row)
    return {"servers": result}


@router.post("/api/mcp/prompts/get")
async def get_prompt(payload: ProtocolRequest, services: Services):
    session = _session(services, payload.server_name)
    prompts = await _catalog(session, "prompts")
    prompt = next((item for item in prompts if item.get("name") == payload.name), None)
    if prompt is None:
        raise HTTPException(404, "Prompt is not advertised by this server")
    arguments = prompt.get("arguments", [])
    allowed = {item["name"] for item in arguments}
    if set(payload.arguments) - allowed or any(item.get("required") and not payload.arguments.get(item["name"]) for item in arguments):
        raise HTTPException(422, "Unknown or missing required prompt argument")
    response = await _protocol_call(session.get_prompt(payload.name, arguments=payload.arguments))
    result = response.model_dump(mode="json", by_alias=True)
    if len(json.dumps(result).encode()) > 5 * 1024 * 1024:
        raise HTTPException(413, "Prompt response exceeds safety limit")
    return result


@router.post("/api/mcp/templates/read")
async def read_template(payload: ProtocolRequest, services: Services):
    session = _session(services, payload.server_name)
    templates = await _catalog(session, "templates")
    if not any(item.get("uriTemplate") == payload.name for item in templates):
        raise HTTPException(404, "Template is not advertised by this server")
    from mcp.shared.uri_template import UriTemplate
    try:
        template = UriTemplate.parse(payload.name)
    except ValueError as exc:
        raise HTTPException(422, "Invalid URI template advertised by the server") from exc
    if set(payload.arguments) - set(template.variable_names):
        raise HTTPException(422, "Unknown URI template argument")
    if set(template.variable_names) - template.query_variable_names - set(payload.arguments):
        raise HTTPException(422, "Missing URI template argument")
    uri = template.expand(payload.arguments)
    if len(uri.encode()) > 4096:
        raise HTTPException(413, "Expanded URI exceeds safety limit")
    response = await _protocol_call(session.read_resource(uri))
    contents, size = [], 0
    if len(response.contents) > 128:
        raise HTTPException(413, "Too many resource contents")
    for item in response.contents:
        try:
            content, size = _checked_content(item, uri, size)
        except ResourceLimitExceeded as exc:
            raise HTTPException(413, "Resource content exceeds safety limit") from exc
        except ValueError as exc:
            raise HTTPException(502, "MCP server returned invalid resource content") from exc
        contents.append(content)
    return {"server_name": payload.server_name, "uri": uri, "contents": contents}
