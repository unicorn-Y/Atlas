# Protocol behavior references: OpenAI Codex app-server docs and CLI `codex exec`;
# Anthropic Claude Code `claude -p` docs; Agent Client Protocol v1 session setup
# (https://agentclientprotocol.com/protocol/session-setup).
# This is an independent Atlas JSON-RPC/ACP adapter; no upstream source is copied.
"""Atlas JSON-RPC stdio SDK server with an ACP v1 session adapter."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any


async def _wait_with_cancel(future: asyncio.Future[Any], cancel: asyncio.Event) -> Any:
    cancel_wait = asyncio.create_task(cancel.wait())
    try:
        done, _pending = await asyncio.wait(
            {future, cancel_wait}, return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_wait in done and cancel.is_set():
            if not future.done():
                future.cancel()
            return None
        return future.result()
    finally:
        if not cancel_wait.done():
            cancel_wait.cancel()
        await asyncio.gather(cancel_wait, return_exceptions=True)


def _claim_stdio_channel() -> tuple[Any, Any]:
    """Keep the JSON-RPC pipes for ourselves and hand child processes harmless fds.

    On Windows a thread blocked in ReadFile on the stdin pipe also blocks any child process
    (git, shells, tools) that inherits that same handle, so a prompt hangs right after the
    first event. Children inheriting fd 1 would also write stray bytes into the protocol
    stream. Duplicate the real pipes for the server, then point fd 0 at NUL and fd 1 at stderr.
    """
    rpc_in = os.fdopen(os.dup(0), "r", encoding="utf-8", newline="\n")
    rpc_out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.close(null_fd)
    os.dup2(2, 1)
    sys.stdin = open(os.devnull, encoding="utf-8")
    sys.stdout = sys.stderr
    return rpc_in, rpc_out


async def serve_stdio(*, workspace: str | None = None) -> None:
    """Serve newline-delimited JSON-RPC requests and streamed run notifications."""
    rpc_in, rpc_out = _claim_stdio_channel()
    from atlas.agent import AgentOrchestrator
    from atlas.config import DATA_ROOT
    from atlas.kernel.tools import kernel_tool_schemas
    from atlas.memory import MemoryStore
    from atlas.models import ModelManager

    memory = MemoryStore()
    await memory.init()
    try:
        from atlas.engine.session_migration import migrate_legacy_sessions

        migration = await migrate_legacy_sessions(DATA_ROOT / "engine", memory)
        if migration.status != "ready":
            raise RuntimeError(migration.error or "Session migration is not ready")
        orchestrator = AgentOrchestrator(model_mgr=ModelManager(), memory=memory)
        default_workspace = str(Path(workspace or Path.cwd()).expanduser().resolve())
        sessions: dict[str, dict[str, str]] = {}
        active: dict[str, asyncio.Event] = {}
        active_tasks: dict[str, asyncio.Task[None]] = {}
        pending_approvals: dict[str, asyncio.Future[str]] = {}
        pending_inputs: dict[str, asyncio.Future[str]] = {}
        pending_client_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}
        outgoing: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def write_output() -> None:
            while True:
                message = await outgoing.get()
                if message is None:
                    return
                rpc_out.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
                rpc_out.flush()

        writer = asyncio.create_task(write_output(), name="atlas-app-server-stdout")

        async def response(request_id: Any, *, result: Any = None,
                           error: dict[str, Any] | None = None) -> None:
            payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
            if error is None:
                payload["result"] = result
            else:
                payload["error"] = error
            await outgoing.put(payload)

        async def notify(method: str, params: dict[str, Any]) -> None:
            await outgoing.put({"jsonrpc": "2.0", "method": method, "params": params})

        async def run_prompt(request_id: Any, session_id: str, prompt: str,
                             session: dict[str, str], cancel: asyncio.Event,
                             *, acp: bool = False) -> None:
            text_parts: list[str] = []
            message_id = str(uuid.uuid4())

            async def approve(event_id: str, tool_name: str, args: dict[str, Any]) -> str:
                if acp:
                    await notify("session/update", {
                        "sessionId": session_id,
                        "update": {"sessionUpdate": "tool_call_update",
                                   "toolCallId": event_id.removeprefix("approval:"),
                                   "status": "in_progress", "rawInput": args},
                    })
                    return "allow"
                future = asyncio.get_running_loop().create_future()
                pending_approvals[event_id] = future
                await notify("approval/request", {
                    "session_id": session_id, "event_id": event_id,
                    "tool_name": tool_name, "arguments": args,
                })
                try:
                    result = await _wait_with_cancel(future, cancel)
                    if cancel.is_set():
                        return "deny"
                    return str(result)
                finally:
                    pending_approvals.pop(event_id, None)

            async def ask_user(call_id: str, prompt_text: str,
                               options: list[str] | None = None) -> str:
                if acp:
                    return "This ACP v1 adapter does not support free-text elicitation; use Atlas app-server input/request."
                future = asyncio.get_running_loop().create_future()
                pending_inputs[call_id] = future
                await notify("input/request", {
                    "session_id": session_id, "call_id": call_id,
                    "prompt": prompt_text, "options": options or [],
                })
                try:
                    answer = await _wait_with_cancel(future, cancel)
                    if cancel.is_set():
                        return ""
                    return answer
                finally:
                    pending_inputs.pop(call_id, None)

            failure_detail = ""
            try:
                async for event in orchestrator.run(
                    prompt, session["conversation_id"], workspace=session["workspace"],
                    workspace_trusted=True, permission_mode="ask_writes",
                    cancel_event=cancel, approval_callback=approve,
                    input_callback=ask_user,
                ):
                    if event.get("type") == "chunk":
                        chunk = str(event.get("content") or "")
                        text_parts.append(chunk)
                        if acp and chunk:
                            await notify("session/update", {
                                "sessionId": session_id,
                                "update": {
                                    "sessionUpdate": "agent_message_chunk",
                                    "messageId": message_id,
                                    "content": {"type": "text", "text": chunk},
                                },
                            })
                    elif acp and event.get("type") == "tool_call":
                        await notify("session/update", {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "tool_call",
                                "toolCallId": str(event.get("id") or uuid.uuid4().hex),
                                "title": str(event.get("name") or "Tool"),
                                "kind": "other", "status": "in_progress",
                                "rawInput": event.get("arguments") or {},
                            },
                        })
                    elif acp and event.get("type") == "tool_result":
                        output = event.get("content")
                        if isinstance(output, list):
                            output = "".join(str(item.get("text") or "") for item in output if isinstance(item, dict))
                        await notify("session/update", {
                            "sessionId": session_id,
                            "update": {
                                "sessionUpdate": "tool_call_update",
                                "toolCallId": str(event.get("id") or ""),
                                "status": "failed" if event.get("is_error") else "completed",
                                "rawOutput": str(output or ""),
                            },
                        })
                    elif acp and event.get("type") == "plan_updated":
                        plan = event.get("plan")
                        entries = plan.get("steps", []) if isinstance(plan, dict) else []
                        await notify("session/update", {
                            "sessionId": session_id,
                            "update": {"sessionUpdate": "plan", "entries": entries},
                        })
                    elif event.get("type") == "error":
                        failure_detail = str(event.get("detail") or "Agent run failed.")
                    if not acp:
                        await notify("session/event", {"session_id": session_id, "event": event})
                if acp:
                    if failure_detail:
                        await response(request_id, result={
                            "stopReason": "error",
                            "error": {"code": -32010, "message": failure_detail},
                        })
                    else:
                        await response(request_id, result={
                            "stopReason": "cancelled" if cancel.is_set() else "end_turn",
                        })
                else:
                    await response(request_id, result={
                        "session_id": session_id, "text": "".join(text_parts),
                        "status": "failed" if failure_detail else "completed",
                    })
            except Exception as exc:  # keep the JSON-RPC process alive across run failures
                await response(request_id, error={"code": -32010, "message": f"{type(exc).__name__}: {exc}"})
            finally:
                active.pop(session_id, None)
                active_tasks.pop(session_id, None)

        while True:
            line = await asyncio.to_thread(rpc_in.readline)
            if not line:
                break
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                    raise ValueError("expected a JSON-RPC 2.0 object")
                method = str(request.get("method") or "")
                params = request.get("params") if isinstance(request.get("params"), dict) else {}
                request_id = request.get("id")
                if not method and request_id is not None:
                    future = pending_client_requests.get(str(request_id))
                    if future is not None and not future.done():
                        result = request.get("result")
                        future.set_result(result if isinstance(result, dict) else {})
                    continue
                if request_id is None and method != "session/cancel":
                    continue
                if method == "initialize":
                    if params.get("protocolVersion", 1) != 1:
                        await response(request_id, error={
                            "code": -32002, "message": "Atlas supports ACP protocol version 1 only.",
                        })
                        continue
                    await response(request_id, result={
                        "protocolVersion": 1,
                        "agentInfo": {"name": "Atlas", "version": "0.1.0"},
                        "agentCapabilities": {
                            "loadSession": False,
                            "sessionCapabilities": {"close": {}},
                        },
                    })
                elif method == "tools/list":
                    tools = orchestrator._model_facing_tools()
                    existing = {
                        str(item.get("function", {}).get("name") or "")
                        for item in tools if isinstance(item, dict)
                    }
                    for item in kernel_tool_schemas(include_workflow=True):
                        name = str(item.get("function", {}).get("name") or "")
                        if name and name not in existing:
                            tools.append(item)
                            existing.add(name)
                    await response(request_id, result={"tools": tools})
                elif method in {"session/start", "session/new"}:
                    acp = method == "session/new"
                    if acp and params.get("mcpServers"):
                        await response(request_id, error={
                            "code": -32602,
                            "message": "Per-session ACP MCP server injection is unavailable; configure MCP servers in Atlas.",
                        })
                        continue
                    cwd_arg = params.get("cwd") if acp else params.get("workspace")
                    if acp and (not cwd_arg or not Path(str(cwd_arg)).is_absolute()):
                        await response(request_id, error={
                            "code": -32602, "message": "ACP session/new requires an absolute cwd.",
                        })
                        continue
                    cwd = str(Path(str(cwd_arg or default_workspace)).expanduser().resolve())
                    if not Path(cwd).is_dir():
                        await response(request_id, error={"code": -32602, "message": "workspace is not a directory"})
                        continue
                    session_id = str(uuid.uuid4())
                    conversation_id = str(params.get("conversation_id") or uuid.uuid4())
                    await memory.save_conversation_metadata(conversation_id, title_hint="Atlas app-server")
                    sessions[session_id] = {"workspace": cwd, "conversation_id": conversation_id}
                    if acp:
                        await response(request_id, result={"sessionId": session_id})
                    else:
                        await response(request_id, result={
                            "session_id": session_id, "conversation_id": conversation_id, "workspace": cwd,
                        })
                elif method == "session/prompt":
                    acp = "sessionId" in params
                    session_id = str((params.get("sessionId") if acp else params.get("session_id")) or "")
                    prompt_value = params.get("prompt")
                    if acp and isinstance(prompt_value, list):
                        if any(not isinstance(item, dict) or item.get("type") != "text"
                               for item in prompt_value):
                            await response(request_id, error={
                                "code": -32602, "message": "Atlas ACP adapter currently accepts text prompt blocks only.",
                            })
                            continue
                        prompt = "\n".join(
                            str(item.get("text") or "") for item in prompt_value
                            if isinstance(item, dict) and item.get("type") == "text"
                        ).strip()
                    else:
                        prompt = str(prompt_value or "").strip()
                    if session_id not in sessions or not prompt.strip():
                        await response(request_id, error={"code": -32602, "message": "session_id and non-empty prompt are required"})
                    elif session_id in active:
                        await response(request_id, error={"code": -32011, "message": "session already has an active run"})
                    else:
                        cancel = asyncio.Event()
                        active[session_id] = cancel
                        task = asyncio.create_task(
                            run_prompt(request_id, session_id, prompt, dict(sessions[session_id]), cancel,
                                       acp=acp),
                            name=f"atlas-run:{session_id}",
                        )
                        active_tasks[session_id] = task
                elif method == "session/cancel":
                    acp = "sessionId" in params
                    session_id = str((params.get("sessionId") if acp else params.get("session_id")) or "")
                    event = active.get(session_id)
                    if event is None:
                        if request_id is not None:
                            await response(request_id, result={"cancelled": False})
                    else:
                        event.set()
                        if request_id is not None:
                            await response(request_id, result={"cancelled": True})
                elif method == "approval/response":
                    event_id = str(params.get("event_id") or "")
                    future = pending_approvals.get(event_id)
                    choice = "allow" if params.get("choice") == "allow" else "deny"
                    if future is None or future.done():
                        await response(request_id, error={"code": -32602, "message": "approval request is no longer pending"})
                    else:
                        future.set_result(choice)
                        await response(request_id, result={"accepted": True})
                elif method == "input/response":
                    call_id = str(params.get("call_id") or "")
                    future = pending_inputs.get(call_id)
                    if future is None or future.done():
                        await response(request_id, error={"code": -32602, "message": "input request is no longer pending"})
                    else:
                        future.set_result(str(params.get("value") or ""))
                        await response(request_id, result={"accepted": True})
                elif method == "session/close":
                    acp = "sessionId" in params
                    session_id = str((params.get("sessionId") if acp else params.get("session_id")) or "")
                    event = active.get(session_id)
                    if event is not None:
                        event.set()
                    sessions.pop(session_id, None)
                    await response(request_id, result={} if acp else {"closed": True})
                else:
                    await response(request_id, error={"code": -32601, "message": f"method not found: {method}"})
            except (json.JSONDecodeError, ValueError) as exc:
                await response(None, error={"code": -32700, "message": str(exc)})

        for event in active.values():
            event.set()
        for future in pending_approvals.values():
            if not future.done():
                future.set_result("deny")
        for future in pending_inputs.values():
            if not future.done():
                future.set_result("")
        for future in pending_client_requests.values():
            if not future.done():
                future.set_result({"outcome": "cancelled"})
        if active_tasks:
            await asyncio.gather(*list(active_tasks.values()), return_exceptions=True)
        await outgoing.put(None)
        await writer
    finally:
        await memory.close()
