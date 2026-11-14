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
from typing import Any, Literal


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


def _acp_permission_allowed(result: Any) -> bool:
    """Fail closed unless the ACP client selected an offered allow option."""
    if not isinstance(result, dict):
        return False
    outcome = result.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("outcome") != "selected":
        return False
    return outcome.get("optionId") == "allow_once"


def _conversation_metadata(conversation: dict[str, Any]) -> dict[str, Any]:
    raw = conversation.get("metadata")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _acp_config_options(permission_preset: str) -> list[dict[str, Any]]:
    from atlas.approval_policy import PERMISSION_PRESETS

    options = [
        {"value": name, "name": str(item.get("label") or name)}
        for name, item in PERMISSION_PRESETS.items()
    ]
    return [{
        "configId": "permissionPreset",
        "name": "Permission preset",
        "type": "select",
        "currentValue": permission_preset,
        "options": options,
    }]


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


async def serve_stdio(*, workspace: str | None = None,
                      protocol: Literal["app-server", "acp"] = "app-server") -> None:
    """Serve newline-delimited JSON-RPC requests and streamed run notifications."""
    rpc_in, rpc_out = _claim_stdio_channel()
    from atlas.agent import AgentOrchestrator
    from atlas.config import DATA_ROOT
    from atlas.engine.kernel.tools import kernel_tool_schemas
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
        sessions: dict[str, dict[str, Any]] = {}
        active: dict[str, asyncio.Event] = {}
        active_tasks: dict[str, asyncio.Task[None]] = {}
        pending_approvals: dict[str, asyncio.Future[str]] = {}
        pending_inputs: dict[str, asyncio.Future[str]] = {}
        pending_client_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}
        pending_acp_permissions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # SDK session/settle barrier: `session/wait` registers one future per
        # waiter; the run task resolves them when it settles. The reader loop
        # never blocks on a run, so approvals/inputs stay answerable mid-wait.
        pending_session_waits: dict[str, list[asyncio.Future[None]]] = {}
        wait_responders: set[asyncio.Task[None]] = set()
        session_fs: dict[str, dict[str, bool]] = {}
        from atlas.tools.acp_fs import (
            AcpFilesystem, capabilities_from_initialize, reset_current, set_current,
        )
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
                    permission_id = f"acp-permission-{uuid.uuid4().hex}"
                    future = asyncio.get_running_loop().create_future()
                    pending_acp_permissions[permission_id] = future
                    await outgoing.put({
                        "jsonrpc": "2.0", "id": permission_id,
                        "method": "session/request_permission",
                        "params": {
                            "sessionId": session_id,
                            "toolCall": {
                                "toolCallId": event_id.removeprefix("approval:"),
                                "title": tool_name, "kind": "other",
                                "status": "in_progress", "rawInput": args,
                            },
                            "options": [
                                {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
                                {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
                            ],
                        },
                    })
                    try:
                        result = await _wait_with_cancel(future, cancel)
                        return "allow" if _acp_permission_allowed(result) else "deny"
                    finally:
                        pending_acp_permissions.pop(permission_id, None)
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
            fs_token = None
            if not acp:
                # Whole-session running/idle transitions, DSH `session.status`
                # semantics: one notification per transition, run-scoped.
                await notify("session/status", {
                    "session_id": session_id, "status": "running",
                })
            try:
                fs_caps = session_fs.get(session_id, {}) if acp else {}
                if acp and (fs_caps.get("read") or fs_caps.get("write")):
                    async def client_fs(method: str, params: dict[str, Any]) -> dict[str, Any]:
                        client_request_id = f"acp-fs-{uuid.uuid4().hex}"
                        future = asyncio.get_running_loop().create_future()
                        pending_client_requests[client_request_id] = future
                        await outgoing.put({"jsonrpc": "2.0", "id": client_request_id,
                                            "method": method, "params": params})
                        try:
                            return await asyncio.wait_for(future, timeout=120)
                        finally:
                            pending_client_requests.pop(client_request_id, None)
                    fs_token = set_current(AcpFilesystem(
                        session_id, session["workspace"], client_fs,
                        read_enabled=fs_caps.get("read", False),
                        write_enabled=fs_caps.get("write", False),
                    ))
                async for event in orchestrator.run(
                    prompt, session["conversation_id"], workspace=session["workspace"],
                    workspace_trusted=True, permission_mode=session.get("permission_mode", "ask_writes"),
                    agent_preset_id=session.get("agent_preset_id", "default"),
                    agent_preset_capabilities=session.get("agent_preset_capabilities"),
                    permission_preset=session.get("permission_preset", "ask"),
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
                        "status": "cancelled" if cancel.is_set() else "failed" if failure_detail else "completed",
                    })
            except Exception as exc:  # keep the JSON-RPC process alive across run failures
                await response(request_id, error={"code": -32010, "message": f"{type(exc).__name__}: {exc}"})
            finally:
                if fs_token is not None:
                    reset_current(fs_token)
                if not acp:
                    await notify("session/status", {
                        "session_id": session_id, "status": "idle",
                    })
                active.pop(session_id, None)
                active_tasks.pop(session_id, None)
                for waiter in pending_session_waits.pop(session_id, []):
                    if not waiter.done():
                        waiter.set_result(None)

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
                acp_wire = method in {"session/new", "session/list", "session/resume",
                                     "session/set_config_option"} or (
                    method in {"session/prompt", "session/cancel", "session/close"}
                    and "sessionId" in params
                )
                if method in {"session/start", "session/new", "session/list", "session/resume",
                              "session/set_config_option", "session/prompt", "session/cancel",
                              "session/close", "session/wait", "shutdown"}:
                    if (protocol == "acp") != acp_wire:
                        await response(request_id, error={
                            "code": -32601,
                            "message": f"{method} payload does not belong to the {protocol} protocol; ACP and Atlas app-server have separate method/field contracts.",
                        })
                        continue
                if not method and request_id is not None:
                    future = pending_client_requests.get(str(request_id))
                    if future is None:
                        future = pending_acp_permissions.get(str(request_id))
                    if future is not None and not future.done():
                        result = request.get("result")
                        future.set_result(result if isinstance(result, dict) else {})
                    continue
                if request_id is None and method != "session/cancel":
                    continue
                if method == "initialize":
                    if params.get("protocolVersion", 1) != 1:
                        await response(request_id, error={
                            "code": -32002, "message": "Atlas supports protocol version 1 only.",
                        })
                        continue
                    session_fs["__initialize__"] = capabilities_from_initialize(params)
                    if protocol == "acp":
                        await response(request_id, result={
                            "protocolVersion": 1,
                            "agentInfo": {"name": "Atlas", "version": "0.1.0"},
                            "agentCapabilities": {
                                "loadSession": False,
                                "sessionCapabilities": {
                                    # `list` is the ACP list-session extension;
                                    # configOptions advertises Atlas' permissionPreset option.
                                    "close": {}, "resume": {}, "list": {}, "configOptions": {},
                                },
                            },
                        })
                    else:
                        await response(request_id, result={
                            "protocolVersion": 1,
                            "serverInfo": {"name": "Atlas", "version": "0.1.0"},
                            "capabilities": {"tools": True, "sessions": True, "streaming": True,
                                             "approvals": True, "inputRequests": True},
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
                    if acp and method in {"session/new", "session/resume"} and params.get("mcpServers"):
                        await response(request_id, error={
                            "code": -32602,
                            "message": "Per-session ACP MCP server injection is unavailable; use an empty mcpServers list.",
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
                    agent_preset_id = str(params.get("agentPresetId") or "default").strip()
                    permission_preset = str(params.get("permissionPreset") or "ask").strip()
                    try:
                        from atlas.approval_policy import PERMISSION_PRESETS
                        from atlas.config import get_config
                        from atlas.task_artifacts import AgentPresetStore

                        if permission_preset not in PERMISSION_PRESETS:
                            raise ValueError(f"unknown permission preset: {permission_preset}")
                        preset_capabilities = AgentPresetStore(get_config().db_path.parent).resolve(agent_preset_id)
                    except (KeyError, ValueError) as exc:
                        await response(request_id, error={"code": -32602, "message": str(exc)})
                        continue
                    conversation_id = str(uuid.uuid4()) if acp else str(
                        params.get("conversation_id") or uuid.uuid4()
                    )
                    session_id = conversation_id if acp else str(uuid.uuid4())
                    await memory.save_conversation_metadata(conversation_id, title_hint="Atlas app-server")
                    sessions[session_id] = {
                        "workspace": cwd, "conversation_id": conversation_id,
                        "agent_preset_id": agent_preset_id,
                        "agent_preset_capabilities": preset_capabilities,
                        "permission_preset": permission_preset,
                        "permission_mode": PERMISSION_PRESETS[permission_preset]["mode"],
                    }
                    session_fs[session_id] = dict(session_fs.get("__initialize__", {})) if acp else {}
                    if acp:
                        conversation = await memory.get_conversation(conversation_id)
                        metadata = _conversation_metadata(conversation or {})
                        metadata["acp"] = {
                            "agentPresetId": agent_preset_id,
                            "permissionPreset": permission_preset,
                        }
                        await memory.update_conversation(
                            conversation_id, workspace=cwd,
                            permission_mode=PERMISSION_PRESETS[permission_preset]["mode"],
                            metadata=metadata,
                        )
                        await response(request_id, result={
                            "sessionId": session_id,
                            "configOptions": _acp_config_options(permission_preset),
                        })
                    else:
                        await response(request_id, result={
                            "session_id": session_id, "conversation_id": conversation_id, "workspace": cwd,
                        })
                elif method == "session/list":
                    try:
                        limit = max(1, min(100, int(params.get("limit", 50))))
                        cursor = max(0, int(params.get("cursor", "0")))
                    except (TypeError, ValueError):
                        await response(request_id, error={
                            "code": -32602, "message": "session/list limit or cursor is invalid",
                        })
                        continue
                    conversations = await memory.list_conversations(limit=None)
                    acp_conversations = [
                        item for item in conversations
                        if isinstance(_conversation_metadata(item).get("acp"), dict)
                    ]
                    page = acp_conversations[cursor:cursor + limit]
                    next_cursor = str(cursor + limit) if cursor + limit < len(acp_conversations) else None
                    await response(request_id, result={
                        "sessions": [{
                            "sessionId": str(item["id"]),
                            "cwd": str(item.get("workspace") or ""),
                            "title": str(item.get("title") or ""),
                            "updatedAt": str(item.get("updated_at") or ""),
                        } for item in page],
                        **({"nextCursor": next_cursor} if next_cursor is not None else {}),
                    })
                elif method == "session/resume":
                    session_id = str(params.get("sessionId") or "")
                    cwd_arg = params.get("cwd")
                    if not session_id or not cwd_arg or not Path(str(cwd_arg)).is_absolute():
                        await response(request_id, error={
                            "code": -32602, "message": "session/resume requires sessionId and an absolute cwd",
                        })
                        continue
                    cwd = str(Path(str(cwd_arg)).expanduser().resolve())
                    conversation = await memory.get_conversation(session_id)
                    metadata = _conversation_metadata(conversation or {})
                    acp_metadata = metadata.get("acp")
                    if conversation is None or not isinstance(acp_metadata, dict):
                        await response(request_id, error={"code": -32002, "message": "unknown ACP session"})
                        continue
                    stored_cwd = str(Path(str(conversation.get("workspace") or "")).expanduser().resolve())
                    if not Path(cwd).is_dir() or os.path.normcase(cwd) != os.path.normcase(stored_cwd):
                        await response(request_id, error={
                            "code": -32602, "message": "session/resume cwd must match the session workspace",
                        })
                        continue
                    agent_preset_id = str(acp_metadata.get("agentPresetId") or "default")
                    permission_preset = str(acp_metadata.get("permissionPreset") or "ask")
                    try:
                        from atlas.approval_policy import PERMISSION_PRESETS
                        from atlas.config import get_config
                        from atlas.task_artifacts import AgentPresetStore

                        if permission_preset not in PERMISSION_PRESETS:
                            raise ValueError(f"unknown permission preset: {permission_preset}")
                        preset_capabilities = AgentPresetStore(get_config().db_path.parent).resolve(agent_preset_id)
                    except (KeyError, ValueError) as exc:
                        await response(request_id, error={"code": -32602, "message": str(exc)})
                        continue
                    sessions[session_id] = {
                        "workspace": cwd, "conversation_id": session_id,
                        "agent_preset_id": agent_preset_id,
                        "agent_preset_capabilities": preset_capabilities,
                        "permission_preset": permission_preset,
                        "permission_mode": PERMISSION_PRESETS[permission_preset]["mode"],
                    }
                    session_fs[session_id] = dict(session_fs.get("__initialize__", {}))
                    await response(request_id, result={
                        "configOptions": _acp_config_options(permission_preset),
                    })
                elif method == "session/set_config_option":
                    # Atlas ACP extension: stable ACP v1 has no standardized
                    # permission-preset config option, so expose only this narrow
                    # selector and keep it independent from app-server methods.
                    session_id = str(params.get("sessionId") or "")
                    session = sessions.get(session_id)
                    if session is None:
                        await response(request_id, error={"code": -32002, "message": "unknown ACP session"})
                        continue
                    if session_id in active:
                        await response(request_id, error={
                            "code": -32011, "message": "cannot change session configuration during an active run",
                        })
                        continue
                    if params.get("configId") != "permissionPreset":
                        await response(request_id, error={
                            "code": -32602, "message": "unknown configId: permissionPreset is the only supported option",
                        })
                        continue
                    value = params.get("value")
                    if params.get("type") not in (None, "id") or not isinstance(value, str):
                        await response(request_id, error={
                            "code": -32602, "message": "permissionPreset requires a string id value",
                        })
                        continue
                    from atlas.approval_policy import PERMISSION_PRESETS

                    if value not in PERMISSION_PRESETS:
                        await response(request_id, error={
                            "code": -32602, "message": f"unknown permission preset: {value}",
                        })
                        continue
                    session["permission_preset"] = value
                    session["permission_mode"] = PERMISSION_PRESETS[value]["mode"]
                    conversation = await memory.get_conversation(session["conversation_id"])
                    metadata = _conversation_metadata(conversation or {})
                    acp_metadata = metadata.setdefault("acp", {})
                    acp_metadata["permissionPreset"] = value
                    await memory.update_conversation(
                        session["conversation_id"],
                        permission_mode=PERMISSION_PRESETS[value]["mode"], metadata=metadata,
                    )
                    await response(request_id, result={"configOptions": _acp_config_options(value)})
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
                elif method == "session/wait":
                    # DSH SDK `session/wait`: settle barrier for one session's
                    # active run. Returns {} once the root run is no longer
                    # active; unknown sessions are rejected. Registered waiters
                    # are resolved by the run task itself, so the reader loop
                    # stays free to answer approval/input requests mid-wait.
                    session_id = str(
                        (params.get("sessionId") if "sessionId" in params
                         else params.get("session_id")) or ""
                    )
                    if session_id not in sessions:
                        await response(request_id, error={
                            "code": -32002, "message": "unknown session",
                        })
                        continue
                    task = active_tasks.get(session_id)
                    if task is None or task.done():
                        await response(request_id, result={})
                        continue
                    waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
                    waits = pending_session_waits.setdefault(session_id, [])
                    waits.append(waiter)
                    if task.done():
                        # The run settled between the done-check and the
                        # registration; its finally already walked this list.
                        if not waiter.done():
                            waiter.set_result(None)
                        if waiter in waits:
                            waits.remove(waiter)
                        if not waits:
                            pending_session_waits.pop(session_id, None)

                    async def respond_when_settled(
                        future: asyncio.Future[None] = waiter, wait_id: Any = request_id,
                    ) -> None:
                        await future
                        await response(wait_id, result={})

                    responder = asyncio.create_task(
                        respond_when_settled(),
                        name=f"atlas-session-wait:{session_id[:12]}",
                    )
                    wait_responders.add(responder)
                    responder.add_done_callback(wait_responders.discard)
                elif method == "shutdown":
                    # DSH SDK `shutdown`: acknowledge, then run the same
                    # graceful drain as EOF (cancel active runs, fail pending
                    # client requests, flush ordered output, close the memory).
                    await response(request_id, result={})
                    break
                elif method == "session/close":
                    acp = "sessionId" in params
                    session_id = str((params.get("sessionId") if acp else params.get("session_id")) or "")
                    event = active.get(session_id)
                    if event is not None:
                        event.set()
                    sessions.pop(session_id, None)
                    session_fs.pop(session_id, None)
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
        for future in pending_acp_permissions.values():
            if not future.done():
                future.set_result({"outcome": "cancelled"})
        for waiters in pending_session_waits.values():
            for future in waiters:
                if not future.done():
                    future.set_result(None)
        if active_tasks:
            await asyncio.gather(*list(active_tasks.values()), return_exceptions=True)
        if wait_responders:
            await asyncio.gather(*list(wait_responders), return_exceptions=True)
        await outgoing.put(None)
        await writer
    finally:
        await memory.close()
