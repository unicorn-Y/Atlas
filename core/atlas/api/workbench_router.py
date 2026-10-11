"""工作台 API（``/api/workbench/*``、``/ws/workbench/*``）：挂件的增删改、注册表安装、会话和终端。

改挂件配置（PUT/DELETE/升级）必须带 ``confirm: true``——只有用户在工作台界面里解锁后才会带上，
主体的其他流程不会改到挂件。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from atlas.workbench import registry
from atlas.workbench.sessions import WorkbenchHost, delete_transcript, list_transcripts, read_transcript
from atlas.workbench.store import AgentManifest, WorkbenchStore
from atlas.workbench.template import create_template_agent

log = structlog.get_logger()

router = APIRouter()


def _host(app: Any) -> WorkbenchHost:
    host = getattr(app.state, "workbench_host", None)
    if host is None:
        host = WorkbenchHost()
        app.state.workbench_host = host
    return host


class ManifestBody(BaseModel):
    manifest: dict[str, Any]
    confirm: bool = False


class ConfirmBody(BaseModel):
    confirm: bool = False


class EnabledBody(BaseModel):
    enabled: bool


class TemplateBody(BaseModel):
    name: str


class StartBody(BaseModel):
    resume: str | None = None


class PromptBody(BaseModel):
    text: str


class PermissionBody(BaseModel):
    request_id: str
    option_id: str | None = None


class ModeBody(BaseModel):
    mode_id: str


class OptionBody(BaseModel):
    config_id: str
    value: str | bool


class AuthBody(BaseModel):
    method_id: str


def _require_confirm(confirm: bool) -> None:
    if not confirm:
        raise HTTPException(status_code=423, detail="挂件配置已锁定：在工作台里点「解锁编辑」后再改")


def _agent_view(host: WorkbenchHost, manifest: AgentManifest) -> dict[str, Any]:
    return {
        **manifest.to_dict(),
        "folder": str(host.store.agent_dir(manifest.id)),
        "workspace": str(host.store.workspace(manifest)),
        "running": len(host.running(manifest.id)),
    }


def _get_manifest(host: WorkbenchHost, agent_id: str) -> AgentManifest:
    try:
        return host.store.get(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有这个挂件") from None


# -- agents ------------------------------------------------------------------
@router.get("/api/workbench/agents")
async def list_agents(request: Request) -> dict[str, Any]:
    host = _host(request.app)
    return {"agents": [_agent_view(host, m) for m in host.store.list()], "root": str(host.store.root)}


@router.post("/api/workbench/agents")
async def create_agent(request: Request, body: ManifestBody) -> dict[str, Any]:
    host = _host(request.app)
    data = dict(body.manifest)
    data["id"] = data.get("id") or host.store.unique_id(str(data.get("name") or "agent"))
    data.setdefault("source", "custom")
    try:
        manifest = host.store.save(AgentManifest.from_dict(data), create=True)
    except FileExistsError:
        raise HTTPException(status_code=409, detail="已经有同名（同 id）的挂件") from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _agent_view(host, manifest)


@router.post("/api/workbench/agents/template")
async def create_from_template(request: Request, body: TemplateBody) -> dict[str, Any]:
    host = _host(request.app)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="给它起个名字")
    return _agent_view(host, create_template_agent(host.store, body.name.strip()))


@router.put("/api/workbench/agents/{agent_id}")
async def update_agent(request: Request, agent_id: str, body: ManifestBody) -> dict[str, Any]:
    _require_confirm(body.confirm)
    host = _host(request.app)
    current = _get_manifest(host, agent_id)
    data = {**current.to_dict(), **body.manifest, "id": agent_id, "created_at": current.created_at}
    try:
        manifest = host.store.save(AgentManifest.from_dict(data))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await host.close_agent(agent_id)  # 新配置从下一个会话生效
    return _agent_view(host, manifest)


@router.post("/api/workbench/agents/{agent_id}/enabled")
async def set_enabled(request: Request, agent_id: str, body: EnabledBody) -> dict[str, Any]:
    host = _host(request.app)
    manifest = _get_manifest(host, agent_id)
    manifest.enabled = body.enabled
    host.store.save(manifest)
    if not body.enabled:
        await host.close_agent(agent_id)
    return _agent_view(host, manifest)


@router.delete("/api/workbench/agents/{agent_id}")
async def delete_agent(request: Request, agent_id: str, confirm: bool = Query(default=False)) -> dict[str, Any]:
    _require_confirm(confirm)
    host = _host(request.app)
    _get_manifest(host, agent_id)
    await host.close_agent(agent_id)
    host.store.delete(agent_id)
    return {"deleted": agent_id}


@router.post("/api/workbench/agents/{agent_id}/upgrade")
async def upgrade_agent(request: Request, agent_id: str, body: ConfirmBody) -> dict[str, Any]:
    _require_confirm(body.confirm)
    host = _host(request.app)
    _get_manifest(host, agent_id)
    await host.close_agent(agent_id)
    try:
        manifest = await registry.upgrade(host.store, agent_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"连不上 ACP 注册表：{type(exc).__name__}") from None
    return _agent_view(host, manifest)


# -- registry ----------------------------------------------------------------
@router.get("/api/workbench/registry")
async def get_registry(refresh: bool = Query(default=False)) -> dict[str, Any]:
    try:
        data = await registry.fetch_registry(force=refresh)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"连不上 ACP 注册表：{type(exc).__name__}") from None
    return {"agents": [registry.describe(entry) for entry in data.get("agents", [])], "platform": registry.platform_key()}


@router.post("/api/workbench/registry/{registry_id}/install")
async def install_from_registry(request: Request, registry_id: str) -> dict[str, Any]:
    host = _host(request.app)
    try:
        manifest = await registry.install(host.store, registry_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="注册表里没有这个 agent") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"下载失败：{type(exc).__name__}") from None
    return _agent_view(host, manifest)


# -- sessions ----------------------------------------------------------------
@router.get("/api/workbench/agents/{agent_id}/sessions")
async def list_sessions(request: Request, agent_id: str) -> dict[str, Any]:
    host = _host(request.app)
    _get_manifest(host, agent_id)
    return {"history": list_transcripts(host.store, agent_id), "running": host.running(agent_id)}


@router.post("/api/workbench/agents/{agent_id}/sessions")
async def start_session(request: Request, agent_id: str, body: StartBody) -> dict[str, Any]:
    host = _host(request.app)
    _get_manifest(host, agent_id)
    try:
        session = await host.start(agent_id, body.resume)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有这个会话") from None
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"挂件启动失败：{exc}") from None
    return session.snapshot()


@router.get("/api/workbench/agents/{agent_id}/sessions/{session_id}/events")
async def session_events(request: Request, agent_id: str, session_id: str) -> dict[str, Any]:
    host = _host(request.app)
    _get_manifest(host, agent_id)
    try:
        return {"events": read_transcript(host.store, agent_id, session_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="没有这个会话") from None


@router.delete("/api/workbench/agents/{agent_id}/sessions/{session_id}")
async def remove_session(request: Request, agent_id: str, session_id: str) -> dict[str, Any]:
    host = _host(request.app)
    _get_manifest(host, agent_id)
    await host.close(session_id)
    try:
        delete_transcript(host.store, agent_id, session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有这个会话") from None
    return {"deleted": session_id}


def _session(request: Request, session_id: str) -> Any:
    try:
        return _host(request.app).get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="这个会话已经结束，重新打开它") from None


@router.post("/api/workbench/sessions/{session_id}/prompt")
async def prompt_session(request: Request, session_id: str, body: PromptBody) -> dict[str, Any]:
    session = _session(request, session_id)
    try:
        await session.prompt(body.text)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return session.snapshot()


@router.post("/api/workbench/sessions/{session_id}/cancel")
async def cancel_session(request: Request, session_id: str) -> dict[str, Any]:
    session = _session(request, session_id)
    await session.cancel()
    return session.snapshot()


@router.post("/api/workbench/sessions/{session_id}/permission")
async def answer_permission(request: Request, session_id: str, body: PermissionBody) -> dict[str, Any]:
    session = _session(request, session_id)
    try:
        session.answer_permission(body.request_id, body.option_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="这个请求已经过期") from None
    return session.snapshot()


@router.post("/api/workbench/sessions/{session_id}/authenticate")
async def authenticate_session(request: Request, session_id: str, body: AuthBody) -> dict[str, Any]:
    session = _session(request, session_id)
    try:
        await session.authenticate(body.method_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"登录没成功：{exc}") from None
    return session.snapshot()


@router.post("/api/workbench/sessions/{session_id}/mode")
async def set_session_mode(request: Request, session_id: str, body: ModeBody) -> dict[str, Any]:
    session = _session(request, session_id)
    try:
        await session.set_mode(body.mode_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"切换模式失败：{exc}") from None
    return session.snapshot()


@router.post("/api/workbench/sessions/{session_id}/option")
async def set_session_option(request: Request, session_id: str, body: OptionBody) -> dict[str, Any]:
    session = _session(request, session_id)
    try:
        await session.set_option(body.config_id, body.value)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"修改失败：{exc}") from None
    return session.snapshot()


@router.post("/api/workbench/sessions/{session_id}/close")
async def close_session(request: Request, session_id: str) -> dict[str, Any]:
    await _host(request.app).close(session_id)
    return {"closed": session_id}


@router.websocket("/ws/workbench/sessions/{session_id}")
async def session_stream(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    session = _host(ws.app).sessions.get(session_id)
    if session is None:
        await ws.send_json({"kind": "error", "detail": "这个会话已经结束"})
        await ws.close(code=1008)
        return
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    session.subscribers.add(queue)
    await ws.send_json({"kind": "snapshot", **session.snapshot()})
    try:
        while True:
            getter = asyncio.create_task(queue.get())
            receiver = asyncio.create_task(ws.receive_text())
            done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                getter.cancel()
                receiver.result()  # raises WebSocketDisconnect when the panel closes
                continue
            receiver.cancel()
            await ws.send_json(getter.result())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        session.subscribers.discard(queue)


@router.websocket("/ws/workbench/agents/{agent_id}/terminal")
async def agent_terminal(ws: WebSocket, agent_id: str, shell: bool = Query(default=False)) -> None:
    """终端模式：在挂件自己的工作目录、隔离环境里跑它的命令行界面。

    ``shell=true`` 开一个同样隔离的 PowerShell（给挂件登录、装依赖用）。"""
    await ws.accept()
    store: WorkbenchStore = _host(ws.app).store
    try:
        manifest = store.get(agent_id)
        from winpty import PtyProcess
    except KeyError:
        await ws.send_json({"type": "error", "error": "没有这个挂件"})
        await ws.close(code=1008)
        return
    except ImportError:
        await ws.send_json({"type": "error", "error": "pywinpty is not installed"})
        await ws.close(code=1011)
        return
    try:
        argv = ["powershell.exe", "-NoLogo", "-NoProfile"] if shell else store.argv(manifest)
        pty = PtyProcess.spawn(argv, cwd=str(store.workspace(manifest)), env=store.environment(manifest))
    except Exception as exc:  # noqa: BLE001
        log.warning("workbench.terminal_spawn_failed", agent=agent_id, error=str(exc))
        await ws.send_json({"type": "error", "error": f"启动失败：{exc}"})
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
        try:
            await ws.send_json({"type": "exit", "code": pty.exitstatus})
        except (RuntimeError, WebSocketDisconnect):
            pass

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
