"""工作台会话：每个挂件会话是一个独立子进程，事件广播给界面并写进挂件自己的 jsonl。

ACP 模式用官方 ACP SDK 连挂件；一次性命令模式每次任务跑一遍命令，把输出包装成同样的
``agent_message_chunk`` 事件，界面只需要认一种格式。终端模式不经过这里（见 router 的 WebSocket）。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

import structlog

from atlas.workbench.store import AgentManifest, WorkbenchStore

log = structlog.get_logger()

_PERMISSION_TIMEOUT = 600.0


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


class WorkbenchSession:
    """一个挂件会话。``id`` 是工作台自己的会话号，``acp_id`` 是挂件那边的。"""

    def __init__(self, host: WorkbenchHost, manifest: AgentManifest, session_id: str) -> None:
        self.host = host
        self.manifest = manifest
        self.id = session_id
        self.acp_id: str | None = None
        self.status = "starting"
        self.busy = False
        self.info: dict[str, Any] = {}
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.pending: dict[str, asyncio.Future[str | None]] = {}
        self._manager: Any = None
        self._conn: Any = None
        self._task: asyncio.Task[None] | None = None
        self._command_proc: asyncio.subprocess.Process | None = None
        self._replaying = False
        self.path = host.store.sessions_dir(manifest.id) / f"{session_id}.jsonl"

    # -- event fan-out ---------------------------------------------------
    def emit(self, kind: str, data: dict[str, Any] | None = None, *, persist: bool = True) -> None:
        event = {"kind": kind, "t": time.time(), **(data or {})}
        if persist:
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError:
                log.warning("workbench.transcript_write_failed", agent=self.manifest.id, session=self.id)
        for queue in list(self.subscribers):
            queue.put_nowait(event)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id, "agent_id": self.manifest.id, "status": self.status, "busy": self.busy,
            "acp_session_id": self.acp_id, "info": self.info,
            "pending_permissions": [key for key, fut in self.pending.items() if not fut.done()],
        }

    # -- lifecycle -------------------------------------------------------
    async def start(self, resume_acp_id: str | None = None) -> None:
        if self.manifest.mode == "command":
            self.status = "ready"
            self.emit("status", {"status": "ready"}, persist=False)
            return
        from acp import PROTOCOL_VERSION, spawn_agent_process
        from acp.interfaces import Client
        from acp.schema import ClientCapabilities, Implementation

        session = self

        class WorkbenchClient(Client):
            async def session_update(self, session_id: str, update: Any, **_kwargs: Any) -> None:
                # load_session 会把旧对话重放一遍；记录里已经有了，不再重复写。
                if not session._replaying:
                    session.emit("update", {"update": _dump(update)})

            async def request_permission(self, session_id: str, tool_call: Any, options: Any, **_kwargs: Any) -> Any:
                return await session._ask_permission(tool_call, options)

        store = self.host.store
        argv = store.argv(self.manifest)
        cwd = store.workspace(self.manifest)
        self._manager = spawn_agent_process(
            WorkbenchClient(), argv[0], *argv[1:], env=store.environment(self.manifest), cwd=str(cwd),
        )
        try:
            self._conn, _process = await self._manager.__aenter__()
            init = await asyncio.wait_for(self._conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=ClientCapabilities(),
                client_info=Implementation(name="atlas-workbench", title="Atlas 工作台", version="1"),
            ), timeout=180)
            caps = init.agent_capabilities
            self.info = {
                "agent": _dump(init.agent_info) if getattr(init, "agent_info", None) else None,
                "auth_methods": _dump(init.auth_methods or []),
                "load_session": bool(caps and caps.load_session),
            }
        except BaseException as exc:
            self.status = "failed"
            detail = _error_text(exc)
            self.emit("error", {"detail": detail})
            await self._shutdown()
            raise RuntimeError(detail) from exc
        try:
            await self._open(resume_acp_id, str(cwd))
        except Exception as exc:  # noqa: BLE001
            if self.info.get("auth_methods"):
                # 多半是没登录：进程留着，界面上点登录方式后再开会话。
                self.status = "auth_required"
                self.emit("error", {"detail": f"需要先登录：{_error_text(exc)}", "auth_methods": self.info["auth_methods"]})
                return
            self.status = "failed"
            detail = _error_text(exc)
            self.emit("error", {"detail": detail, "auth_methods": self.info.get("auth_methods", [])})
            await self._shutdown()
            raise RuntimeError(detail) from exc

    async def _open(self, resume_acp_id: str | None, cwd: str) -> None:
        if resume_acp_id and self.info.get("load_session"):
            self.status = "loading"
            self._replaying = True
            try:
                await self._conn.load_session(cwd=cwd, session_id=resume_acp_id, mcp_servers=[])
                self.acp_id = resume_acp_id
            except Exception as exc:  # noqa: BLE001 — 挂件那边找不到旧会话：开新的，记录照旧接着写
                log.info("workbench.load_session_failed", agent=self.manifest.id, error=_error_text(exc))
            finally:
                self._replaying = False
        if self.acp_id is None:
            # 不给挂件任何 Atlas 的 MCP：和主体的工具、记忆完全隔开。
            response = await self._conn.new_session(cwd=cwd, mcp_servers=[])
            self.acp_id = response.session_id
            self.info["modes"] = _dump(response.modes) if getattr(response, "modes", None) else None
            self.info["config_options"] = _dump(getattr(response, "config_options", None) or [])
        self.status = "ready"
        self.emit("session", {"acp_session_id": self.acp_id, "info": self.info})

    async def authenticate(self, method_id: str) -> None:
        if self._conn is None:
            raise RuntimeError("挂件没有在运行")
        await self._conn.authenticate(method_id=method_id)
        await self._open(None, str(self.host.store.workspace(self.manifest)))

    async def set_mode(self, mode_id: str) -> None:
        if self._conn is None:
            raise RuntimeError("挂件没有在运行")
        await self._conn.set_session_mode(session_id=self.acp_id, mode_id=mode_id)
        if isinstance(self.info.get("modes"), dict):
            self.info["modes"]["currentModeId"] = mode_id

    async def set_option(self, config_id: str, value: str | bool) -> None:
        if self._conn is None:
            raise RuntimeError("挂件没有在运行")
        response = await self._conn.set_config_option(config_id=config_id, session_id=self.acp_id, value=value)
        options = getattr(response, "config_options", None)
        if options is not None:
            self.info["config_options"] = _dump(options)

    async def prompt(self, text: str) -> None:
        if self.busy:
            raise RuntimeError("它还在干上一件事，等它做完或先停止")
        if self.status != "ready":
            raise RuntimeError("挂件还没准备好")
        self.busy = True
        self.emit("user", {"text": text})
        runner = self._run_command if self.manifest.mode == "command" else self._run_acp
        self._task = asyncio.create_task(runner(text))

    async def _run_acp(self, text: str) -> None:
        from acp.schema import TextContentBlock

        try:
            result = await self._conn.prompt(session_id=self.acp_id, prompt=[TextContentBlock(type="text", text=text)])
            self.emit("done", {"stop_reason": getattr(result, "stop_reason", None), "usage": _dump(getattr(result, "usage", None))})
        except asyncio.CancelledError:
            self.emit("done", {"stop_reason": "cancelled"})
        except Exception as exc:  # noqa: BLE001 — agent errors go to the UI, not the server log
            self.emit("error", {"detail": _error_text(exc)})
        finally:
            self.busy = False

    async def _run_command(self, text: str) -> None:
        store = self.host.store
        argv = store.argv(self.manifest, prompt=text)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=str(store.workspace(self.manifest)), env=store.environment(self.manifest),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL,
            )
            self._command_proc = proc
            assert proc.stdout is not None
            while chunk := await proc.stdout.read(4096):
                self.emit("update", {"update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": chunk.decode("utf-8", errors="replace")},
                }})
            code = await proc.wait()
            self.emit("done", {"stop_reason": "end_turn" if code == 0 else f"exit {code}"})
        except Exception as exc:  # noqa: BLE001
            self.emit("error", {"detail": _error_text(exc)})
        finally:
            self._command_proc = None
            self.busy = False

    async def cancel(self) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_result(None)
        if self.manifest.mode == "command":
            if self._command_proc and self._command_proc.returncode is None:
                self._command_proc.kill()
            return
        if self._conn is not None and self.acp_id:
            try:
                await self._conn.cancel(session_id=self.acp_id)
            except Exception:  # noqa: BLE001
                log.debug("workbench.cancel_failed", exc_info=True)

    async def close(self) -> None:
        await self.cancel()
        if self._task and not self._task.done():
            self._task.cancel()
        await self._shutdown()
        self.status = "closed"
        self.emit("status", {"status": "closed"}, persist=False)

    async def _shutdown(self) -> None:
        manager, self._manager, self._conn = self._manager, None, None
        if manager is not None:
            try:
                await manager.__aexit__(None, None, None)
            except BaseException:  # noqa: BLE001
                log.debug("workbench.shutdown_error", exc_info=True)

    # -- permissions -----------------------------------------------------
    async def _ask_permission(self, tool_call: Any, options: Any) -> Any:
        from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

        if self.manifest.permission == "allow":
            from atlas.runtime.backends import full_access_permission_response

            return full_access_permission_response(options)
        request_id = uuid.uuid4().hex[:12]
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        self.emit("permission", {"request_id": request_id, "tool_call": _dump(tool_call), "options": _dump(list(options))})
        try:
            option_id = await asyncio.wait_for(future, timeout=_PERMISSION_TIMEOUT)
        except asyncio.TimeoutError:
            option_id = None
        finally:
            self.pending.pop(request_id, None)
        self.emit("permission_result", {"request_id": request_id, "option_id": option_id})
        if option_id is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(outcome=AllowedOutcome(optionId=option_id, outcome="selected"))

    def answer_permission(self, request_id: str, option_id: str | None) -> None:
        future = self.pending.get(request_id)
        if future is None or future.done():
            raise KeyError(request_id)
        future.set_result(option_id)


class WorkbenchHost:
    """工作台里所有在跑的挂件会话（只在内存里，进程退出就结束；记录在磁盘上）。"""

    def __init__(self, store: WorkbenchStore | None = None) -> None:
        self.store = store or WorkbenchStore()
        self.sessions: dict[str, WorkbenchSession] = {}

    async def start(self, agent_id: str, resume: str | None = None) -> WorkbenchSession:
        manifest = self.store.get(agent_id)
        if not manifest.enabled:
            raise RuntimeError("这个挂件已停用")
        if manifest.mode == "terminal":
            raise ValueError("终端模式的挂件直接在终端里打开")
        resume_acp_id = None
        if resume:
            meta = read_transcript(self.store, agent_id, resume)
            resume_acp_id = next((e.get("acp_session_id") for e in reversed(meta) if e.get("kind") == "session"), None)
            existing = self.sessions.get(resume)
            if existing and existing.status in {"ready", "loading"}:
                return existing
        session = WorkbenchSession(self, manifest, resume or uuid.uuid4().hex[:16])
        self.sessions[session.id] = session
        try:
            await session.start(resume_acp_id)
        except Exception:
            self.sessions.pop(session.id, None)
            raise
        return session

    def get(self, session_id: str) -> WorkbenchSession:
        return self.sessions[session_id]

    def running(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        return [s.snapshot() for s in self.sessions.values() if agent_id in (None, s.manifest.id) and s.status != "closed"]

    async def close(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            await session.close()

    async def close_agent(self, agent_id: str) -> None:
        for session_id in [sid for sid, s in self.sessions.items() if s.manifest.id == agent_id]:
            await self.close(session_id)

    async def shutdown(self) -> None:
        for session_id in list(self.sessions):
            await self.close(session_id)


def read_transcript(store: WorkbenchStore, agent_id: str, session_id: str) -> list[dict[str, Any]]:
    if not session_id.isalnum():
        raise KeyError(session_id)
    path = store.sessions_dir(agent_id) / f"{session_id}.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def list_transcripts(store: WorkbenchStore, agent_id: str) -> list[dict[str, Any]]:
    items = []
    for path in sorted(store.sessions_dir(agent_id).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        title = ""
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    event = json.loads(line)
                    if event.get("kind") == "user":
                        title = str(event.get("text", ""))[:80]
                        break
        except (OSError, json.JSONDecodeError):
            pass
        items.append({"id": path.stem, "title": title or "（空会话）", "updated_at": path.stat().st_mtime})
    return items


def delete_transcript(store: WorkbenchStore, agent_id: str, session_id: str) -> None:
    if not session_id.isalnum():
        raise KeyError(session_id)
    path: Path = store.sessions_dir(agent_id) / f"{session_id}.jsonl"
    path.unlink(missing_ok=True)


def _error_text(exc: BaseException) -> str:
    data = getattr(exc, "data", None)
    message = str(exc) or type(exc).__name__
    if isinstance(data, dict) and data.get("details"):
        message = f"{message}：{data['details']}"
    elif isinstance(exc, FileNotFoundError):
        message = f"找不到启动命令：{exc.filename or exc}"
    return message[:2000]
