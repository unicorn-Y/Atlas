"""Tool, process and MCP server management surface (``/api/tools, /api/custom-tools, /api/mcp, /api/processes, /ws/terminal``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from datetime import UTC, datetime
import asyncio
import os
import secrets
from pathlib import Path

from fastapi import Request, WebSocket, WebSocketDisconnect

from atlas.skills.dependencies import dependency_preflight
router = APIRouter()
_terminal_buffers: dict[str, str] = {}


@router.put("/api/terminal/buffer")
async def update_terminal_buffer(payload: dict[str, Any]) -> dict[str, bool]:
    tab_id = str(payload.get("tab_id", ""))[:240]
    text = payload.get("text")
    if not tab_id or not isinstance(text, str):
        raise HTTPException(status_code=422, detail="tab_id and text are required")
    _terminal_buffers[tab_id] = text[-200_000:]
    return {"saved": True}
log = structlog.get_logger(__name__)

def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch."""
    import atlas.server

    return atlas.server


def _service(name: str, services: AppServices) -> Any:
    """Resolve an optional service: per-app container first, then the server module."""
    value = getattr(services, name, None)
    if value is None:
        value = getattr(_server(), name, None)
    return value



@router.get("/api/processes")
async def list_agent_processes(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[dict[str, Any]]:
    runtime = _service("local_execution", services)
    if runtime is None:
        return []
    return [{"id": item.execution_id, "command": item.command, "cwd": item.cwd,
             "status": "running" if item.state == "running" else "exited",
             "exit_code": item.exit_code, "started_at": item.started_at,
             "run_id": item.owner_run_id}
            for item in runtime._processes.values()]


@router.get("/api/processes/{process_id}/output")
async def get_agent_process_output(
    services: Annotated[AppServices, Depends(get_app_services)],
    process_id: str, after: int = Query(0, ge=0),
) -> dict[str, Any]:
    runtime = _service("local_execution", services)
    record = runtime._processes.get(process_id) if runtime else None
    if record is None:
        raise HTTPException(status_code=404, detail="Process not found")
    stdout_size = record.stdout_path.stat().st_size
    stream_path = record.stdout_path if after < stdout_size else record.stderr_path
    stream_offset = after if after < stdout_size else after - stdout_size
    with stream_path.open("rb") as output_file:
        output_file.seek(stream_offset)
        chunk = output_file.read(65536)
    return {"output": chunk.decode("utf-8", errors="replace"), "next": after + len(chunk),
            "status": "running" if record.state == "running" else "exited"}


@router.post("/api/processes/{process_id}/kill")
async def kill_agent_process(
    services: Annotated[AppServices, Depends(get_app_services)],
    process_id: str,
) -> dict[str, Any]:
    runtime = _service("local_execution", services)
    record = runtime._processes.get(process_id) if runtime else None
    if record is None:
        raise HTTPException(status_code=404, detail="Process not found")
    await runtime._cancel_process(record)
    return {"id": process_id, "status": "exited", "exit_code": record.exit_code}


@router.post("/api/processes/{process_id}/stdin")
async def write_agent_process_stdin(
    services: Annotated[AppServices, Depends(get_app_services)],
    process_id: str, payload: dict[str, Any],
) -> dict[str, Any]:
    """Send one line or raw text to a running process started with an open stdin."""
    runtime = _service("local_execution", services)
    record = runtime._processes.get(process_id) if runtime else None
    if record is None:
        raise HTTPException(status_code=404, detail="Process not found")
    action = str(payload.get("action") or "submit_stdin")
    if action not in {"write_stdin", "submit_stdin", "close_stdin"}:
        raise HTTPException(status_code=422, detail="Unsupported stdin action")
    data = payload.get("data", "")
    if not isinstance(data, str) or len(data) > 16_000:
        raise HTTPException(status_code=422, detail="stdin data must be text up to 16000 characters")
    try:
        return await runtime._write_process_stdin(record, action, data)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket, cwd: str = Query(...)) -> None:
    await ws.accept()
    try:
        from winpty import PtyProcess
    except ImportError:
        await ws.send_json({"type": "error", "error": "pywinpty is not installed"})
        await ws.close(code=1011)
        return
    directory = Path(cwd).expanduser().resolve()
    if not directory.is_dir():
        await ws.send_json({"type": "error", "error": "cwd must be an existing directory"})
        await ws.close(code=1008)
        return
    try:
        pty = PtyProcess.spawn(["powershell.exe", "-NoLogo", "-NoProfile"], cwd=str(directory))
    except Exception as exc:  # noqa: BLE001 — PTY providers can raise platform-specific spawn errors
        log.exception("terminal.spawn_failed", cwd=str(directory))
        await ws.send_json({"type": "error", "error": str(exc)})
        await ws.close(code=1011)
        return
    async def read_output() -> None:
        while pty.isalive():
            try:
                chunk = await asyncio.to_thread(pty.read, 4096)
                if chunk:
                    await ws.send_json({"type": "output", "data": chunk})
            except (EOFError, OSError, RuntimeError, WebSocketDisconnect):
                break
        await ws.send_json({"type": "exit", "code": pty.exitstatus})
    reader = asyncio.create_task(read_output())
    try:
        while True:
            item = await ws.receive_json()
            if item.get("type") == "input":
                pty.write(str(item.get("data", "")))
            elif item.get("type") == "resize":
                pty.setwinsize(int(item.get("rows", 24)), int(item.get("cols", 80)))
    except WebSocketDisconnect:
        pass
    finally:
        if pty.isalive():
            pty.terminate(force=True)
        reader.cancel()


@router.get("/api/tools")
async def list_tools(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Return all available MCP tools across connected servers."""
    mcp_client = services.mcp_client
    if mcp_client is None:
        from atlas import server as _atlas_server

        mcp_client = _atlas_server.mcp_client
    assert mcp_client is not None
    tools = mcp_client.list_tools()
    return {
        "servers": mcp_client.get_server_names(),
        "tool_count": mcp_client.tool_count,
        "tools": [
            {
                "name": t.qualified_name,
                "description": t.description,
                "server": t.server_name,
                "input_schema": t.input_schema,
            }
            for t in tools
        ],
    }


@router.get("/api/custom-tools")
async def list_custom_tools(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    custom_tools = services.custom_tools
    if custom_tools is None:
        from atlas import server as _atlas_server

        custom_tools = _atlas_server.custom_tools
    assert custom_tools is not None
    return {"tools": custom_tools.list_tools()}


@router.post("/api/custom-tools", status_code=201)
async def create_custom_tool(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    custom_tools = services.custom_tools
    if custom_tools is None:
        from atlas import server as _atlas_server

        custom_tools = _atlas_server.custom_tools
    assert custom_tools is not None
    try:
        return custom_tools.create(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/custom-tools/{tool_id}")
async def update_custom_tool(
    services: Annotated[AppServices, Depends(get_app_services)],
    tool_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    custom_tools = services.custom_tools
    if custom_tools is None:
        from atlas import server as _atlas_server

        custom_tools = _atlas_server.custom_tools
    assert custom_tools is not None
    try:
        result = custom_tools.update(tool_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="找不到这个自定义工具。")
    return result


@router.delete("/api/custom-tools/{tool_id}")
async def delete_custom_tool(
    services: Annotated[AppServices, Depends(get_app_services)],
    tool_id: str,
) -> dict[str, str]:
    custom_tools = services.custom_tools
    if custom_tools is None:
        from atlas import server as _atlas_server

        custom_tools = _atlas_server.custom_tools
    assert custom_tools is not None
    try:
        deleted = custom_tools.delete(tool_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="找不到这个自定义工具。")
    return {"status": "deleted", "id": tool_id}


@router.post("/api/custom-tools/{tool_id}/test")
async def test_custom_tool(
    services: Annotated[AppServices, Depends(get_app_services)],
    tool_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    custom_tools = services.custom_tools
    if custom_tools is None:
        from atlas import server as _atlas_server

        custom_tools = _atlas_server.custom_tools
    assert custom_tools is not None
    try:
        return await custom_tools.execute(
            tool_id, req.get("arguments", req), allow_disabled=True,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="找不到这个自定义工具。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class MCPServerAddRequest(BaseModel):
    name: str
    transport: str = "stdio"  # "stdio" | "sse"
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: str | None = None
    url: str = ""  # for SSE transport


@router.get("/api/mcp/servers")
async def list_mcp_servers(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Return all connected MCP servers and their tools."""
    mcp_client = services.mcp_client
    if mcp_client is None:
        from atlas import server as _atlas_server

        mcp_client = _atlas_server.mcp_client
    assert mcp_client is not None
    servers = []
    for name in mcp_client.get_server_names():
        tools = mcp_client.get_server_tools(name)
        servers.append({
            "name": name,
            "tool_count": len(tools),
            "tools": [t.qualified_name for t in tools],
        })
    return {"servers": servers}


@router.get("/api/runtime/dependency-check")
async def check_runtime_dependencies(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    mcp_client = _service("mcp_client", services)
    skill_registry = _service("skill_registry", services)
    """Read the current bundled runtime, MCP lifecycle, and canonical Skill dependencies."""
    node_status = _server().get_node_runtime_status()
    runtime_status = mcp_client.get_runtime_status() if mcp_client else {
        "available": False, "blocking_reason": "MCP runtime is unavailable", "servers": [],
    }
    server_states = runtime_status.get("servers", [])
    connected = {item["name"] for item in server_states if item.get("connected")}
    configured = {item["name"] for item in server_states if item.get("configured")}
    skills = []
    if skill_registry is not None:
        for record in skill_registry.list(status="active"):
            dependencies = dependency_preflight(
                record.get("requirements", []), connected_servers=connected,
                configured_servers=configured, registry=skill_registry,
            )
            blocking = [item for item in dependencies if item["state"] != "satisfied"]
            skills.append({
                "name": record["name"], "version": record["version"],
                "dependencies": dependencies, "blocking": blocking,
                "can_use": not blocking,
            })

    blockers = []
    if (not node_status["bundled"]["available"]
            or not node_status["bundled"]["npm_npx_available"]):
        blockers.append({
            "scope": "runtime", "reason": node_status["blocking_reason"]
            or node_status["bundled"]["blocking_reason"]
            or "Atlas bundled Node/npm/npx is unavailable",
        })
    if not runtime_status.get("available", False):
        blockers.append({
            "scope": "mcp_runtime",
            "reason": runtime_status.get("blocking_reason") or "MCP runtime is unavailable",
        })
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "node": node_status,
        "mcp_runtime": runtime_status,
        "mcp_servers": server_states,
        "skills": skills,
        "blocking": blockers,
    }


@router.post("/api/runtime/shutdown", status_code=202)
async def request_runtime_shutdown(
    services: Annotated[AppServices, Depends(get_app_services)],
    request: Request,
) -> dict[str, str]:
    """Gracefully stop an Electron-managed packaged backend with its launch token."""
    expected = os.environ.get("ATLAS_SHUTDOWN_TOKEN", "")
    supplied = request.headers.get("x-atlas-backend-shutdown-token", "")
    callback = getattr(request.app.state, "desktop_shutdown_callback", None)
    daemon_mode = os.environ.get("ATLAS_AUTOMATION_DAEMON") == "1"
    if not expected or not secrets.compare_digest(supplied, expected) or not (callable(callback) or daemon_mode):
        raise HTTPException(status_code=403, detail="Backend shutdown is not authorized")
    from atlas.api.skills_market_router import get_market

    await get_market().cancel_pending_searches()
    if callable(callback):
        asyncio.get_running_loop().call_soon(callback)
    else:
        # Let the response flush, then signal uvicorn so lifespan shutdown closes DBOS cleanly.
        def stop_daemon() -> None:
            import signal
            os.kill(os.getpid(), signal.SIGTERM)
        asyncio.get_running_loop().call_later(0.25, stop_daemon)
    return {"status": "shutting_down"}


@router.post("/api/mcp/servers")
async def add_mcp_server(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: MCPServerAddRequest,
) -> dict[str, Any]:
    """Dynamically add and connect a new MCP server."""
    mcp_client = services.mcp_client
    if mcp_client is None:
        from atlas import server as _atlas_server

        mcp_client = _atlas_server.mcp_client
    assert mcp_client is not None
    from atlas.tools.mcp_client import MCPServerConfig

    if req.name in mcp_client.get_server_names():
        raise HTTPException(status_code=409, detail=f"Server already exists: {req.name}")

    cfg = MCPServerConfig(
        name=req.name,
        transport=req.transport,
        command=req.command,
        args=req.args,
        env=req.env,
        cwd=req.cwd,
        url=req.url,
        enabled=True,
    )

    try:
        await mcp_client._connect_server(cfg)
    except Exception as e:  # noqa: BLE001 — MCP transports may raise transport-specific exception groups
        log.exception("mcp.server_connect_failed", server=req.name)
        raise HTTPException(status_code=500, detail=f"Failed to connect: {e}")

    try:
        _persist_mcp_server_config(req.name, {
            "transport": req.transport,
            "command": req.command,
            "args": req.args,
            "env": req.env,
            "cwd": req.cwd,
            "url": req.url,
            "enabled": True,
        })
    except Exception as exc:
        await mcp_client.disconnect_server(req.name)
        log.exception("mcp.config_persist_failed", server=req.name)
        raise HTTPException(
            status_code=500, detail="MCP server connected but configuration could not be saved",
        ) from exc

    tools = mcp_client.get_server_tools(req.name)
    return {
        "name": req.name,
        "tool_count": len(tools),
        "tools": [t.qualified_name for t in tools],
    }


@router.delete("/api/mcp/servers/{server_name}")
async def remove_mcp_server(
    services: Annotated[AppServices, Depends(get_app_services)],
    server_name: str,
) -> dict[str, str]:
    """Disconnect and remove an MCP server."""
    mcp_client = services.mcp_client
    if mcp_client is None:
        from atlas import server as _atlas_server

        mcp_client = _atlas_server.mcp_client
    assert mcp_client is not None

    if server_name not in mcp_client.get_server_names():
        raise HTTPException(status_code=404, detail=f"Server not found: {server_name}")

    from atlas.config import get_config

    saved_config = get_config().get("tools.servers", {}) or {}
    server_config = saved_config.get(server_name)
    runtime_config = mcp_client.get_server_config(server_name)
    runtime_tool_names = {
        tool.qualified_name for tool in mcp_client.get_server_tools(server_name)
    }
    await mcp_client.disconnect_server(server_name)
    try:
        _persist_mcp_server_config(server_name, None)
    except Exception as exc:
        if server_config:
            from atlas.tools.mcp_client import MCPServerConfig

            await mcp_client._connect_server(MCPServerConfig(name=server_name, **server_config))
        elif runtime_config is not None:
            await mcp_client._connect_server(runtime_config)
        log.exception("mcp.config_remove_failed", server=server_name)
        raise HTTPException(
            status_code=500, detail="MCP server configuration could not be removed",
        ) from exc

    try:
        from atlas.engine.hermes_runtime import HermesRuntime

        await asyncio.to_thread(
            HermesRuntime.unregister_atlas_mcp_server, server_name, runtime_tool_names,
        )
    except Exception as exc:
        log.exception("mcp.hermes_unregister_failed", server=server_name)
        raise HTTPException(
            status_code=500,
            detail="MCP server was removed from API but chat registry cleanup failed",
        ) from exc
    return {"status": "ok", "server": server_name}


def _persist_mcp_server_config(name: str, server_config: dict[str, Any] | None) -> None:
    """Persist API-managed MCP servers in the same TOML config Hermes loads per run."""
    import copy

    import tomli_w

    from atlas import config as config_module
    from atlas.config import get_config

    config = get_config()
    # 只改 atlas.toml 本身：专家模式开着时 raw 里混着覆盖层，不能写回去。
    data = copy.deepcopy(config.base_raw)
    tools = data.setdefault("tools", {})
    servers = tools.setdefault("servers", {})
    auto_start = list(tools.get("auto_start", []) or [])
    if server_config is None:
        servers.pop(name, None)
        if auto_start:
            auto_start = [item for item in auto_start if item != name]
            if not auto_start:
                # Empty means "all enabled servers" to Hermes. Preserve a non-empty
                # selection that has just become empty by disabling previously excluded
                # servers before switching back to that meaning.
                for remaining in servers.values():
                    if isinstance(remaining, dict) and remaining.get("enabled", True):
                        remaining["enabled"] = False
    else:
        servers[name] = {key: value for key, value in server_config.items() if value is not None}
        if auto_start and name not in auto_start:
            auto_start.append(name)
    tools["auto_start"] = auto_start

    config_path = config_module.CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(tomli_w.dumps(data), encoding="utf-8")
    temporary.replace(config_path)
    config_module.reload_config()


@router.post("/api/mcp/servers/{server_name}/restart")
async def restart_mcp_server(
    services: Annotated[AppServices, Depends(get_app_services)],
    server_name: str,
) -> dict[str, Any]:
    """Restart an MCP server (disconnect + reconnect)."""
    mcp_client = services.mcp_client
    if mcp_client is None:
        from atlas import server as _atlas_server

        mcp_client = _atlas_server.mcp_client
    assert mcp_client is not None

    if server_name not in mcp_client.get_server_names():
        raise HTTPException(status_code=404, detail=f"Server not found: {server_name}")

    try:
        await mcp_client.restart_server(server_name)
    except Exception as e:  # noqa: BLE001 — MCP transports may raise transport-specific exception groups
        log.exception("mcp.server_restart_failed", server=server_name)
        raise HTTPException(status_code=500, detail=f"Restart failed: {e}")

    tools = mcp_client.get_server_tools(server_name)
    return {
        "name": server_name,
        "tool_count": len(tools),
        "tools": [t.qualified_name for t in tools],
    }


@router.post("/api/mcp/servers/reconnect-failed")
async def reconnect_failed_mcp_servers(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Reconnect every configured MCP server requiring attention, with bounded concurrency."""
    mcp_client = services.mcp_client
    if mcp_client is None:
        from atlas import server as _atlas_server

        mcp_client = _atlas_server.mcp_client
    if mcp_client is None:
        raise HTTPException(status_code=503, detail="MCP client unavailable")
    runtime = mcp_client.get_runtime_status()
    states = {"failed", "error", "reconnecting", "auth-needed", "auth_needed",
              "authorization_required", "needs_authorization"}
    selected = [row for row in runtime.get("servers", [])
                if row.get("enabled", True) and str(row.get("state", "")).casefold() in states]
    semaphore = asyncio.Semaphore(3)

    async def reconnect(row: dict[str, Any]) -> dict[str, Any]:
        name = str(row.get("name") or "")
        async with semaphore:
            try:
                await mcp_client.restart_server(name)
                tools = mcp_client.get_server_tools(name)
                status = next((item for item in mcp_client.get_runtime_status().get("servers", [])
                               if item.get("name") == name), {})
                return {"name": name, "ok": bool(status.get("connected")),
                        "state": status.get("state", "unknown"), "tool_count": len(tools),
                        "reason": status.get("blocking_reason") or (None if status.get("connected") else "Server did not reach connected state")}
            except Exception as exc:  # MCP transports may raise transport-specific exception groups
                status = next((item for item in mcp_client.get_runtime_status().get("servers", [])
                               if item.get("name") == name), {})
                return {"name": name, "ok": False, "state": status.get("state", "failed"),
                        "tool_count": len(mcp_client.get_server_tools(name)),
                        "reason": status.get("blocking_reason") or f"重连失败（{type(exc).__name__}）"}

    results = await asyncio.gather(*(reconnect(row) for row in selected))
    return {"selected": len(selected), "succeeded": sum(bool(row["ok"]) for row in results),
            "failed": sum(not row["ok"] for row in results), "results": results,
            "concurrency_limit": 3}
