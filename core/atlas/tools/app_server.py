# Protocol behavior references: OpenAI Codex app-server docs and CLI `codex exec`;
# Anthropic Claude Code `claude -p` docs; Agent Client Protocol v1 session setup
# (https://agentclientprotocol.com/protocol/session-setup).
# This is an independent Atlas JSON-RPC/ACP adapter; no upstream source is copied.
"""Atlas JSON-RPC stdio SDK server with an ACP v1 session adapter."""

from __future__ import annotations

import asyncio
import json
import logging
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


def _resolve_session_working_directory(
    workspace: str, value: Any, *, base_directory: str | None = None,
) -> str:
    """Resolve a local session cwd without allowing it to widen the trusted workspace."""
    if workspace.strip().casefold().startswith("ssh://"):
        raise ValueError("session working-directory changes require a local workspace")
    root = Path(workspace).expanduser().resolve(strict=True)
    candidate = Path(str(value or "")).expanduser()
    if not candidate.is_absolute():
        candidate = Path(base_directory or workspace) / candidate
    candidate = candidate.resolve(strict=True)
    if not root.is_dir() or not candidate.is_dir():
        raise ValueError("working directory and workspace must be existing directories")
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("working directory must remain inside the trusted workspace") from exc
    return str(candidate)


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
    local_execution = None
    try:
        from atlas.engine.session_migration import migrate_legacy_sessions

        migration = await migrate_legacy_sessions(DATA_ROOT / "engine", memory)
        if migration.status != "ready":
            raise RuntimeError(migration.error or "Session migration is not ready")
        from atlas.tools.local_execution import LocalExecutionRuntime

        local_execution = LocalExecutionRuntime()
        orchestrator = AgentOrchestrator(
            model_mgr=ModelManager(), memory=memory, local_execution=local_execution,
        )
        default_workspace = str(Path(workspace or Path.cwd()).expanduser().resolve())
        sessions: dict[str, dict[str, Any]] = {}
        active: dict[str, asyncio.Event] = {}
        active_tasks: dict[str, asyncio.Task[None]] = {}
        next_turn_workers: dict[str, asyncio.Task[None]] = {}
        session_inboxes: dict[str, Any] = {}
        pending_approvals: dict[str, asyncio.Future[str]] = {}
        pending_inputs: dict[str, asyncio.Future[str]] = {}
        app_server_instance_id = uuid.uuid4().hex
        pending_request_meta: dict[str, dict[str, Any]] = {}
        pending_request_by_wire_id: dict[tuple[str, str], str] = {}
        active_task_request_ids: dict[str, str] = {}
        task_cancel_responders: set[asyncio.Task[None]] = set()
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

        async def record_pending_request(request_id: str, session_id: str,
                                         kind: str, wire_id: str,
                                         details: dict[str, Any]) -> None:
            from atlas.engine.session_sync import append_session_event

            session = sessions.get(session_id)
            if session is None:
                raise ValueError("unknown session")
            conversation_id = str(session["conversation_id"])
            await asyncio.to_thread(
                append_session_event, DATA_ROOT / "engine", conversation_id,
                "appserver.request", {
                    "request_id": request_id, "session_id": session_id,
                    "kind": kind, "state": "pending",
                    "instance_id": app_server_instance_id,
                },
            )
            pending_request_meta[request_id] = {
                "request_id": request_id, "session_id": session_id,
                "conversation_id": conversation_id, "kind": kind,
                "state": "pending", "instance_id": app_server_instance_id,
                "wire_id": wire_id, **details,
            }
            pending_request_by_wire_id[(kind, wire_id)] = request_id

        async def set_pending_request_state(request_id: str, state: str) -> bool:
            meta = pending_request_meta.get(request_id)
            if meta is None or meta.get("state") != "pending":
                return False
            from atlas.engine.session_sync import append_session_event

            await asyncio.to_thread(
                append_session_event, DATA_ROOT / "engine", meta["conversation_id"],
                "appserver.request", {
                    "request_id": request_id, "session_id": meta["session_id"],
                    "kind": meta["kind"], "state": state,
                    "instance_id": app_server_instance_id,
                },
            )
            meta["state"] = state
            return True

        async def list_pending_requests(session_id: str) -> list[dict[str, Any]]:
            session = sessions.get(session_id)
            if session is None:
                raise ValueError("unknown session")
            from atlas.engine.session_sync import append_session_event, read_session_events

            conversation_id = str(session["conversation_id"])
            rows: list[dict[str, Any]] = []
            cursor = 0
            for _ in range(10):
                page = await asyncio.to_thread(
                    read_session_events, DATA_ROOT / "engine", conversation_id,
                    after_seq=cursor, limit=1000,
                )
                rows.extend(page)
                if len(page) < 1000:
                    break
                cursor = int(page[-1]["seq"])
            else:
                raise ValueError("pending request history exceeds the bounded recovery scan")

            latest: dict[str, dict[str, Any]] = {}
            for row in rows:
                if row.get("event_type") != "appserver.request":
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                request_id = str(payload.get("request_id") or "")
                if request_id:
                    latest[request_id] = payload

            result: list[dict[str, Any]] = []
            for request_id, event in latest.items():
                state = str(event.get("state") or "")
                if state != "pending":
                    if state == "invalidated":
                        result.append({
                            **event, "status": "invalidated",
                        })
                    continue
                meta = pending_request_meta.get(request_id)
                if (meta is None or meta.get("state") != "pending"
                        or meta.get("instance_id") != app_server_instance_id
                        or meta.get("session_id") != session_id):
                    await asyncio.to_thread(
                        append_session_event, DATA_ROOT / "engine", conversation_id,
                        "appserver.request", {
                            "request_id": request_id,
                            "session_id": str(event.get("session_id") or session_id),
                            "kind": str(event.get("kind") or "unknown"),
                            "state": "invalidated",
                            "instance_id": str(event.get("instance_id") or "unknown"),
                        },
                    )
                    result.append({
                        "request_id": request_id,
                        "session_id": str(event.get("session_id") or session_id),
                        "kind": str(event.get("kind") or "unknown"),
                        "state": "invalidated",
                        "status": "invalidated",
                        "instance_id": str(event.get("instance_id") or "unknown"),
                    })
                else:
                    result.append({
                        **{
                            key: value for key, value in meta.items()
                            if key not in {"conversation_id", "wire_id", "instance_id", "state"}
                        },
                        "status": "pending",
                    })
            return result

        async def record_task_state(session_id: str, request_id: str,
                                    event_id: str, state: str,
                                    run_id: str | None = None) -> None:
            from atlas.engine.session_sync import append_session_event

            session = sessions.get(session_id)
            if session is None:
                raise ValueError("unknown session")
            payload: dict[str, Any] = {
                "session_id": session_id, "request_id": request_id,
                "event_id": event_id, "state": state,
                "instance_id": app_server_instance_id,
            }
            if run_id:
                payload["run_id"] = run_id
            await asyncio.to_thread(
                append_session_event, DATA_ROOT / "engine",
                str(session["conversation_id"]), "appserver.task", payload,
            )

        async def get_task_status(session_id: str, request_id: str) -> dict[str, Any]:
            session = sessions.get(session_id)
            if session is None:
                raise ValueError("unknown session")
            from atlas.engine.session_sync import read_session_events

            conversation_id = str(session["conversation_id"])
            rows: list[dict[str, Any]] = []
            cursor = 0
            for _ in range(10):
                page = await asyncio.to_thread(
                    read_session_events, DATA_ROOT / "engine", conversation_id,
                    after_seq=cursor, limit=1000,
                )
                rows.extend(page)
                if len(page) < 1000:
                    break
                cursor = int(page[-1]["seq"])
            else:
                raise ValueError("task history exceeds the bounded recovery scan")

            enqueued: dict[str, Any] | None = None
            started: dict[str, Any] | None = None
            consumed = False
            inbox_cancelled = False
            latest_state: dict[str, Any] | None = None
            for row in rows:
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                event_type = row.get("event_type")
                if (event_type == "inbox.enqueued"
                        and str(payload.get("request_id") or "") == request_id):
                    enqueued = payload
                elif (enqueued is not None
                      and str(payload.get("event_id") or "") == str(enqueued.get("event_id") or "")):
                    if event_type == "inbox.started":
                        started = payload
                    elif event_type == "inbox.consumed":
                        consumed = True
                    elif event_type == "inbox.cancelled":
                        inbox_cancelled = True
                if (event_type == "appserver.task"
                        and str(payload.get("request_id") or "") == request_id):
                    latest_state = payload
            if enqueued is None:
                raise ValueError("unknown task")

            event_id = str(enqueued.get("event_id") or "")
            run_id = str((latest_state or {}).get("run_id") or
                         (started or {}).get("run_id") or "")
            state = str((latest_state or {}).get("state") or "")
            terminal = {"completed", "failed", "cancelled"}
            if state in terminal:
                status = state
            elif inbox_cancelled:
                status = "cancelled"
            elif consumed:
                status = "completed"
            elif active_task_request_ids.get(session_id) == request_id:
                status = state if state in {"running", "cancelling"} else "running"
            elif started is not None:
                status = "outcome_unknown"
            else:
                status = "queued"
            return {
                "session_id": session_id, "request_id": request_id,
                "event_id": event_id, "run_id": run_id or None,
                "status": status,
            }

        async def respond_after_task_cancel(rpc_id: Any, session_id: str,
                                            request_id: str,
                                            worker: asyncio.Task[None]) -> None:
            try:
                done, _pending = await asyncio.wait({worker}, timeout=30)
                if done:
                    try:
                        worker.result()
                    except Exception:
                        pass
                status = await get_task_status(session_id, request_id)
                if not done and status["status"] not in {"cancelled", "failed", "completed"}:
                    status["status"] = "cancelling"
                await response(rpc_id, result=status)
            except Exception:
                await response(rpc_id, error={
                    "code": -32603, "message": "task cancellation status is unavailable",
                })

        async def run_prompt(request_id: Any, session_id: str, prompt: str,
                             session: dict[str, str], cancel: asyncio.Event,
                             *, acp: bool = False,
                             defer_session_cleanup: bool = False,
                             inbox_ack: tuple[Any, Any] | None = None,
                             run_id: str | None = None) -> str:
            text_parts: list[str] = []
            pending_attempt_text: dict[str, list[str]] = {}
            message_id = str(uuid.uuid4())
            outcome = "failed"

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
                request_id = uuid.uuid4().hex
                try:
                    await record_pending_request(
                        request_id, session_id, "approval", event_id,
                        {"tool_name": tool_name, "arguments": dict(args)},
                    )
                    await notify("approval/request", {
                        "session_id": session_id, "event_id": event_id,
                        "request_id": request_id,
                        "tool_name": tool_name, "arguments": args,
                    })
                    result = await _wait_with_cancel(future, cancel)
                    if cancel.is_set():
                        return "deny"
                    return str(result)
                finally:
                    await set_pending_request_state(
                        request_id,
                        "invalidated" if not future.done() or cancel.is_set() else "resolved",
                    )
                    pending_approvals.pop(event_id, None)
                    pending_request_meta.pop(request_id, None)
                    pending_request_by_wire_id.pop(("approval", event_id), None)

            async def ask_user(call_id: str, prompt_text: str,
                               options: list[str] | None = None) -> str:
                if acp:
                    return "This ACP v1 adapter does not support free-text elicitation; use Atlas app-server input/request."
                future = asyncio.get_running_loop().create_future()
                pending_inputs[call_id] = future
                request_id = uuid.uuid4().hex
                try:
                    await record_pending_request(
                        request_id, session_id, "input", call_id,
                        {"prompt": prompt_text, "options": list(options or [])},
                    )
                    await notify("input/request", {
                        "session_id": session_id, "call_id": call_id,
                        "request_id": request_id,
                        "prompt": prompt_text, "options": options or [],
                    })
                    answer = await _wait_with_cancel(future, cancel)
                    if cancel.is_set():
                        return ""
                    return answer
                finally:
                    await set_pending_request_state(
                        request_id,
                        "invalidated" if not future.done() or cancel.is_set() else "resolved",
                    )
                    pending_inputs.pop(call_id, None)
                    pending_request_meta.pop(request_id, None)
                    pending_request_by_wire_id.pop(("input", call_id), None)

            async def set_working_directory_from_run(value: str | None) -> str:
                if active.get(session_id) is not cancel or cancel.is_set():
                    raise PermissionError("working-directory update is not owned by the active session run")
                canonical_session = sessions.get(session_id)
                if canonical_session is None:
                    raise ValueError("working-directory session is no longer available")
                workspace = str(canonical_session["workspace"])
                previous = str(session.get("working_directory") or workspace)
                recovered = False
                if value is None:
                    try:
                        selected = _resolve_session_working_directory(
                            workspace, previous, base_directory=previous,
                        )
                    except (OSError, ValueError):
                        selected = _resolve_session_working_directory(
                            workspace, workspace, base_directory=workspace,
                        )
                        recovered = selected != previous
                else:
                    selected = _resolve_session_working_directory(
                        workspace, value, base_directory=previous,
                    )
                if selected == previous:
                    return selected
                conversation_id = str(canonical_session["conversation_id"])
                conversation = await memory.get_conversation(conversation_id)
                if conversation is None:
                    raise ValueError("session conversation was not found")
                metadata = _conversation_metadata(conversation)
                app_server_metadata = metadata.get("app_server")
                if not isinstance(app_server_metadata, dict):
                    app_server_metadata = {}
                app_server_metadata["workingDirectory"] = selected
                metadata["app_server"] = app_server_metadata
                if not await memory.update_conversation(conversation_id, metadata=metadata):
                    raise RuntimeError("session working directory could not be persisted")
                canonical_session["working_directory"] = selected
                session["working_directory"] = selected
                change = {
                    "from": previous, "to": selected, "workspace": workspace,
                    "applies_from_next_process": True, "recovered": recovered,
                }
                try:
                    from atlas.config import DATA_ROOT
                    from atlas.engine.session_sync import append_session_event

                    append_session_event(
                        DATA_ROOT / "engine", conversation_id,
                        "working-directory/change", change,
                    )
                except Exception:
                    pass
                try:
                    await notify("working-directory/change", {
                        "session_id": session_id, **change,
                    })
                except Exception:
                    pass
                return selected

            failure_detail = ""
            fs_token = None
            if not acp and not defer_session_cleanup:
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
                    working_directory=session.get("working_directory", session["workspace"]),
                    working_directory_callback=set_working_directory_from_run,
                    run_id=run_id,
                    workspace_trusted=True, permission_mode=session.get("permission_mode", "ask_writes"),
                    agent_preset_id=session.get("agent_preset_id", "default"),
                    agent_preset_capabilities=session.get("agent_preset_capabilities"),
                    permission_preset=session.get("permission_preset", "ask"),
                    cancel_event=cancel, approval_callback=approve,
                    input_callback=ask_user,
                    inbox=inbox_ack[0] if inbox_ack is not None else None,
                ):
                    if event.get("type") == "chunk":
                        chunk = str(event.get("content") or "")
                        attempt_id = str(event.get("attempt_id") or "")
                        if attempt_id:
                            pending_attempt_text.setdefault(attempt_id, []).append(chunk)
                        else:
                            text_parts.append(chunk)
                        if acp and chunk and not attempt_id:
                            await notify("session/update", {
                                "sessionId": session_id,
                                "update": {
                                    "sessionUpdate": "agent_message_chunk",
                                    "messageId": message_id,
                                    "content": {"type": "text", "text": chunk},
                                },
                            })
                    elif event.get("type") == "message.rollback":
                        pending_attempt_text.pop(str(event.get("attempt_id") or ""), None)
                    elif event.get("type") == "model_attempt_committed":
                        attempt_id = str(event.get("attempt_id") or "")
                        committed_text = "".join(pending_attempt_text.pop(attempt_id, []))
                        if committed_text:
                            text_parts.append(committed_text)
                            if acp:
                                await notify("session/update", {
                                    "sessionId": session_id,
                                    "update": {
                                        "sessionUpdate": "agent_message_chunk",
                                        "messageId": message_id,
                                        "content": {"type": "text", "text": committed_text},
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
                    if not acp and event.get("type") != "model_attempt_committed":
                        await notify("session/event", {"session_id": session_id, "event": event})
                outcome = "cancelled" if cancel.is_set() else "failed" if failure_detail else "completed"
                if outcome == "completed" and inbox_ack is not None:
                    inbox, inbox_item = inbox_ack
                    try:
                        if not await inbox.ack(inbox_item.event_id, lane=inbox_item.lane):
                            raise RuntimeError("queued item no longer exists")
                    except Exception:
                        outcome = "failed"
                        failure_detail = "Queued work finished but its durable acknowledgement could not be stored."
                        await notify("session/event", {
                            "session_id": session_id,
                            "event": {"type": "error", "category": "inbox_ack_failed"},
                        })
                if acp:
                    if failure_detail:
                        if request_id is not None:
                            await response(request_id, result={
                                "stopReason": "error",
                                "error": {"code": -32010, "message": failure_detail},
                            })
                    else:
                        if request_id is not None:
                            await response(request_id, result={
                                "stopReason": "cancelled" if cancel.is_set() else "end_turn",
                            })
                else:
                    if request_id is not None:
                        await response(request_id, result={
                            "session_id": session_id, "text": "".join(text_parts),
                            "status": outcome,
                        })
            except Exception as exc:  # keep the JSON-RPC process alive across run failures
                outcome = "failed"
                if request_id is not None:
                    await response(request_id, error={"code": -32010, "message": f"{type(exc).__name__}: {exc}"})
                else:
                    await notify("session/event", {
                        "session_id": session_id,
                        "event": {"type": "error", "category": "queued_run_failed"},
                    })
            finally:
                if fs_token is not None:
                    reset_current(fs_token)
                if inbox_ack is not None:
                    inbox_ack[0].set_current_turn_event(None)
                if not acp and not defer_session_cleanup:
                    await notify("session/status", {
                        "session_id": session_id, "status": "idle",
                    })
                if not defer_session_cleanup:
                    active.pop(session_id, None)
                    active_tasks.pop(session_id, None)
                    for waiter in pending_session_waits.pop(session_id, []):
                        if not waiter.done():
                            waiter.set_result(None)
                    if session_id in sessions:
                        schedule_next_turn_worker(session_id)

            return outcome

        def schedule_next_turn_worker(session_id: str) -> None:
            if session_id not in sessions:
                return
            current = active_tasks.get(session_id)
            if current is not None and not current.done():
                return
            worker = next_turn_workers.get(session_id)
            if worker is not None and not worker.done():
                return
            task = asyncio.create_task(
                drain_next_turn_inbox(session_id),
                name=f"atlas-inbox-worker:{session_id[:12]}",
            )
            next_turn_workers[session_id] = task
            active_tasks[session_id] = task

        def durable_inbox_for_session(session_id: str) -> Any:
            session = sessions.get(session_id)
            if session is None:
                raise ValueError("unknown session")
            inbox = session_inboxes.get(session_id)
            if inbox is None:
                from atlas.engine.kernel.inbox import DurableInbox

                inbox = DurableInbox(
                    DATA_ROOT / "engine", str(session["conversation_id"]),
                )
                session_inboxes[session_id] = inbox
            return inbox

        async def drain_next_turn_inbox(session_id: str) -> None:
            cancel = asyncio.Event()
            active[session_id] = cancel
            inbox = durable_inbox_for_session(session_id)
            current_task = asyncio.current_task()
            worker_running = False
            try:
                while session_id in sessions and not cancel.is_set():
                    item = await inbox.peek("next-turn")
                    if item is None:
                        break
                    if item.started_run_id:
                        await notify("session/event", {
                            "session_id": session_id,
                            "event": {
                                "type": "queue.recovery_required",
                                "event_id": item.event_id,
                                "run_id": item.started_run_id,
                            },
                        })
                        break
                    run_id = uuid.uuid4().hex
                    if not await inbox.mark_started(
                        item.event_id, lane="next-turn", run_id=run_id,
                    ):
                        break
                    if item.request_id:
                        active_task_request_ids[session_id] = item.request_id
                        await record_task_state(
                            session_id, item.request_id, item.event_id,
                            "running", run_id,
                        )
                    if not worker_running:
                        await notify("session/status", {
                            "session_id": session_id, "status": "running",
                        })
                        worker_running = True
                    inbox.set_current_turn_event(item.event_id)
                    outcome = await run_prompt(
                        None, session_id, item.content, dict(sessions[session_id]), cancel,
                        inbox_ack=(inbox, item), run_id=run_id,
                        defer_session_cleanup=True,
                    )
                    if item.request_id:
                        await record_task_state(
                            session_id, item.request_id, item.event_id,
                            outcome, run_id,
                        )
                    if outcome != "completed":
                        break
            finally:
                if worker_running:
                    await notify("session/status", {
                        "session_id": session_id, "status": "idle",
                    })
                if active.get(session_id) is cancel:
                    active.pop(session_id, None)
                if active_tasks.get(session_id) is current_task:
                    active_tasks.pop(session_id, None)
                if next_turn_workers.get(session_id) is current_task:
                    next_turn_workers.pop(session_id, None)
                active_task_request_ids.pop(session_id, None)
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
                if method in {"session/start", "session/new", "session/list", "session/resume", "session/enqueue",
                              "session/retry_recovery",
                              "session/events",
                              "session/pending_requests",
                              "session/task_status", "session/task_cancel",
                              "session/set_config_option", "session/prompt", "session/cancel",
                              "session/close", "session/wait", "session/working-directory/get",
                              "session/working-directory/set", "shutdown"}:
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
                    conversation = await memory.get_conversation(conversation_id)
                    metadata = _conversation_metadata(conversation or {})
                    working_directory = cwd
                    if not acp:
                        stored_workspace = str((conversation or {}).get("workspace") or "")
                        if stored_workspace:
                            try:
                                stored_root = str(Path(stored_workspace).expanduser().resolve(strict=True))
                            except OSError:
                                stored_root = ""
                            if (not stored_root or not Path(stored_root).is_dir()
                                    or os.path.normcase(stored_root) != os.path.normcase(cwd)):
                                await response(request_id, error={
                                    "code": -32602,
                                    "message": "session/start workspace must match the existing trusted workspace",
                                })
                                continue
                        app_server_metadata = metadata.get("app_server")
                        if isinstance(app_server_metadata, dict):
                            try:
                                working_directory = _resolve_session_working_directory(
                                    cwd, app_server_metadata.get("workingDirectory"),
                                )
                            except (OSError, ValueError, TypeError):
                                working_directory = cwd
                        if not isinstance(app_server_metadata, dict):
                            app_server_metadata = {}
                        app_server_metadata["workingDirectory"] = working_directory
                        metadata["app_server"] = app_server_metadata
                        if not await memory.update_conversation(
                            conversation_id, workspace=cwd, metadata=metadata,
                        ):
                            await response(request_id, error={
                                "code": -32603, "message": "session working directory could not be persisted",
                            })
                            continue
                    sessions[session_id] = {
                        "workspace": cwd, "conversation_id": conversation_id,
                        "working_directory": working_directory,
                        "agent_preset_id": agent_preset_id,
                        "agent_preset_capabilities": preset_capabilities,
                        "permission_preset": permission_preset,
                        "permission_mode": PERMISSION_PRESETS[permission_preset]["mode"],
                    }
                    session_fs[session_id] = dict(session_fs.get("__initialize__", {})) if acp else {}
                    if acp:
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
                elif method == "session/working-directory/get":
                    session_id = str(params.get("session_id") or "")
                    session = sessions.get(session_id)
                    if session is None:
                        await response(request_id, error={
                            "code": -32002, "message": "unknown session",
                        })
                    else:
                        await response(request_id, result={
                            "working_directory": str(session.get("working_directory") or session["workspace"]),
                            "workspace": str(session["workspace"]),
                        })
                elif method == "session/working-directory/set":
                    session_id = str(params.get("session_id") or "")
                    session = sessions.get(session_id)
                    if session is None:
                        await response(request_id, error={
                            "code": -32002, "message": "unknown session",
                        })
                        continue
                    task = active_tasks.get(session_id)
                    if (session_id in active or (task is not None and not task.done())
                            or session_id in next_turn_workers):
                        await response(request_id, error={
                            "code": -32011, "message": "working directory cannot change during an active session run",
                        })
                        continue
                    try:
                        selected = _resolve_session_working_directory(
                            str(session["workspace"]), params.get("working_directory"),
                            base_directory=str(session.get("working_directory") or session["workspace"]),
                        )
                    except (OSError, ValueError, TypeError) as exc:
                        await response(request_id, error={"code": -32602, "message": str(exc)})
                        continue
                    conversation = await memory.get_conversation(str(session["conversation_id"]))
                    if conversation is None:
                        await response(request_id, error={
                            "code": -32002, "message": "session conversation was not found",
                        })
                        continue
                    metadata = _conversation_metadata(conversation)
                    app_server_metadata = metadata.get("app_server")
                    if not isinstance(app_server_metadata, dict):
                        app_server_metadata = {}
                    previous = str(session.get("working_directory") or session["workspace"])
                    app_server_metadata["workingDirectory"] = selected
                    metadata["app_server"] = app_server_metadata
                    if not await memory.update_conversation(
                        str(session["conversation_id"]), metadata=metadata,
                    ):
                        await response(request_id, error={
                            "code": -32603, "message": "session working directory could not be persisted",
                        })
                        continue
                    session["working_directory"] = selected
                    event_mirror_error = ""
                    try:
                        from atlas.config import DATA_ROOT
                        from atlas.engine.session_sync import append_session_event

                        append_session_event(DATA_ROOT / "engine", str(session["conversation_id"]),
                                             "working-directory/change", {
                            "from": previous, "to": selected,
                            "workspace": str(session["workspace"]),
                            "applies_from_next_run": True,
                        })
                    except Exception as exc:
                        event_mirror_error = str(exc)
                    result = {
                        "working_directory": selected,
                        "workspace": str(session["workspace"]),
                    }
                    if event_mirror_error:
                        result["event_mirror_error"] = event_mirror_error
                    await response(request_id, result=result)
                elif method == "session/enqueue":
                    session_id = str(params.get("session_id") or "")
                    request_id_value = str(params.get("request_id") or "").strip()
                    prompt = params.get("prompt")
                    if session_id not in sessions or not isinstance(prompt, str) or not prompt.strip():
                        await response(request_id, error={
                            "code": -32602, "message": "session_id and non-empty prompt are required",
                        })
                        continue
                    if not request_id_value or len(request_id_value) > 256:
                        await response(request_id, error={
                            "code": -32602, "message": "request_id must be non-empty and at most 256 characters",
                        })
                        continue
                    conversation_id = str(sessions[session_id]["conversation_id"])
                    try:
                        inbox = durable_inbox_for_session(session_id)
                        event_id, _created = await inbox.inject_with_receipt(
                            prompt, lane="next-turn", request_id=request_id_value,
                        )
                    except ValueError as exc:
                        await response(request_id, error={"code": -32012, "message": str(exc)})
                        continue
                    except Exception:
                        # Do not acknowledge an enqueue whose durable receipt could not
                        # be written, but keep the JSON-RPC process available for a
                        # retry with the same request id.
                        await response(request_id, error={
                            "code": -32603, "message": "enqueue could not be durably recorded",
                        })
                        continue
                    try:
                        task = await get_task_status(session_id, request_id_value)
                        if task["status"] == "queued":
                            await record_task_state(
                                session_id, request_id_value, event_id, "queued",
                            )
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "app-server failed to persist queued task state",
                        )
                        await response(request_id, error={
                            "code": -32603, "message": "queued task state could not be durably recorded",
                        })
                        continue
                    await response(request_id, result={
                        "session_id": session_id,
                        "conversation_id": conversation_id,
                        "request_id": request_id_value,
                        "event_id": event_id,
                        "status": "queued",
                    })
                    if task["status"] == "queued":
                        schedule_next_turn_worker(session_id)
                elif method == "session/retry_recovery":
                    session_id = str(params.get("session_id") or "")
                    session = sessions.get(session_id)
                    if session is None:
                        await response(request_id, error={
                            "code": -32002, "message": "unknown session",
                        })
                        continue
                    from atlas.engine.session_sync import (
                        classify_retry_recovery, read_session_events,
                    )

                    conversation_id = str(session["conversation_id"])
                    rows: list[dict[str, Any]] = []
                    cursor = 0
                    while True:
                        page = await asyncio.to_thread(
                            read_session_events, DATA_ROOT / "engine", conversation_id,
                            after_seq=cursor, limit=1000,
                        )
                        if not page:
                            break
                        rows.extend(page)
                        cursor = int(page[-1].get("seq") or cursor)
                        if len(page) < 1000:
                            break
                    attempt_rows = [
                        row for row in rows
                        if row.get("event_type") == "model/attempt"
                        and isinstance(row.get("payload"), dict)
                    ]
                    latest_run_id = next((
                        str(row["payload"].get("run_id") or "")
                        for row in reversed(attempt_rows)
                        if str(row["payload"].get("run_id") or "")
                    ), "")
                    recovery = (
                        classify_retry_recovery(rows, run_id=latest_run_id)
                        if latest_run_id else {"state": "none", "run_id": ""}
                    )
                    recommended_action = {
                        "none": "none",
                        "settled": "none",
                        "retry_scheduled_not_started": "explicit_resume_required",
                        "outcome_unknown": "do_not_replay",
                        "state_unknown": "manual_review",
                    }.get(str(recovery.get("state")), "manual_review")
                    await response(request_id, result={
                        "session_id": session_id,
                        "conversation_id": conversation_id,
                        **recovery,
                        "recommended_action": recommended_action,
                    })
                elif method == "session/events":
                    session_id = str(params.get("session_id") or "")
                    session = sessions.get(session_id)
                    if session is None:
                        await response(request_id, error={
                            "code": -32002, "message": "unknown session",
                        })
                        continue
                    after_seq = params.get("after_seq", 0)
                    limit = params.get("limit", 100)
                    if (type(after_seq) is not int or after_seq < 0
                            or type(limit) is not int or not 1 <= limit <= 1000):
                        await response(request_id, error={
                            "code": -32602,
                            "message": "session/events after_seq or limit is invalid",
                        })
                        continue
                    from atlas.engine.session_sync import read_session_events

                    conversation_id = str(session["conversation_id"])
                    rows = await asyncio.to_thread(
                        read_session_events, DATA_ROOT / "engine", conversation_id,
                        after_seq=after_seq, limit=limit + 1,
                    )
                    has_more = len(rows) > limit
                    page = rows[:limit]
                    next_cursor = int(page[-1]["seq"]) if has_more and page else None
                    await response(request_id, result={
                        "session_id": session_id,
                        "conversation_id": conversation_id,
                        "after_seq": after_seq,
                        "events": page,
                        "next_cursor": next_cursor,
                    })
                elif method == "session/pending_requests":
                    session_id = str(params.get("session_id") or "")
                    try:
                        requests = await list_pending_requests(session_id)
                    except ValueError as exc:
                        await response(request_id, error={
                            "code": -32002 if str(exc) == "unknown session" else -32003,
                            "message": str(exc),
                        })
                        continue
                    await response(request_id, result={
                        "session_id": session_id, "requests": requests,
                    })
                elif method == "session/task_status":
                    session_id = str(params.get("session_id") or "")
                    task_id = str(params.get("request_id") or "").strip()
                    if not task_id:
                        await response(request_id, error={
                            "code": -32602, "message": "request_id must be non-empty",
                        })
                        continue
                    try:
                        task = await get_task_status(session_id, task_id)
                    except ValueError as exc:
                        await response(request_id, error={"code": -32002, "message": str(exc)})
                        continue
                    await response(request_id, result=task)
                elif method == "session/task_cancel":
                    session_id = str(params.get("session_id") or "")
                    task_id = str(params.get("request_id") or "").strip()
                    if not task_id:
                        await response(request_id, error={
                            "code": -32602, "message": "request_id must be non-empty",
                        })
                        continue
                    try:
                        task = await get_task_status(session_id, task_id)
                    except ValueError as exc:
                        await response(request_id, error={"code": -32002, "message": str(exc)})
                        continue
                    if task["status"] == "completed":
                        await response(request_id, result={**task, "status": "too_late"})
                        continue
                    if task["status"] in {"failed", "cancelled", "outcome_unknown"}:
                        await response(request_id, result=task)
                        continue
                    if task["status"] == "queued":
                        inbox = durable_inbox_for_session(session_id)
                        if await inbox.cancel(task["event_id"], lane="next-turn"):
                            await record_task_state(
                                session_id, task_id, task["event_id"], "cancelled",
                            )
                            await response(request_id, result={**task, "status": "cancelled"})
                            continue
                        task = await get_task_status(session_id, task_id)
                        if task["status"] in {"failed", "cancelled", "completed", "outcome_unknown"}:
                            if task["status"] == "completed":
                                task["status"] = "too_late"
                            await response(request_id, result=task)
                            continue
                    cancel_event = active.get(session_id)
                    worker = next_turn_workers.get(session_id)
                    if (active_task_request_ids.get(session_id) != task_id
                            or cancel_event is None or worker is None):
                        task = await get_task_status(session_id, task_id)
                        if task["status"] == "completed":
                            task["status"] = "too_late"
                        elif task["status"] in {"running", "cancelling"}:
                            task["status"] = "outcome_unknown"
                        await response(request_id, result=task)
                        continue
                    try:
                        await record_task_state(
                            session_id, task_id, task["event_id"],
                            "cancelling", task.get("run_id"),
                        )
                    except Exception:
                        await response(request_id, error={
                            "code": -32603, "message": "task cancellation intent could not be persisted",
                        })
                        continue
                    cancel_event.set()
                    responder = asyncio.create_task(
                        respond_after_task_cancel(request_id, session_id, task_id, worker),
                        name=f"atlas-task-cancel-wait:{task_id[:12]}",
                    )
                    task_cancel_responders.add(responder)
                    responder.add_done_callback(task_cancel_responders.discard)
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
                    request_id_value = str(params.get("request_id") or "")
                    meta = pending_request_meta.get(request_id_value)
                    event_id = str(meta.get("wire_id") or "") if (
                        meta and meta.get("kind") == "approval"
                    ) else str(params.get("event_id") or "")
                    future = pending_approvals.get(event_id)
                    choice = "allow" if params.get("choice") == "allow" else "deny"
                    if future is None or future.done():
                        await response(request_id, error={"code": -32602, "message": "approval request is no longer pending"})
                    else:
                        durable_id = request_id_value or pending_request_by_wire_id.get(("approval", event_id), "")
                        try:
                            if durable_id:
                                await set_pending_request_state(durable_id, "resolved")
                        except Exception:
                            await response(request_id, error={
                                "code": -32603, "message": "approval request could not be durably recorded",
                            })
                            continue
                        future.set_result(choice)
                        await response(request_id, result={"accepted": True})
                elif method == "input/response":
                    request_id_value = str(params.get("request_id") or "")
                    meta = pending_request_meta.get(request_id_value)
                    call_id = str(meta.get("wire_id") or "") if (
                        meta and meta.get("kind") == "input"
                    ) else str(params.get("call_id") or "")
                    future = pending_inputs.get(call_id)
                    if future is None or future.done():
                        await response(request_id, error={"code": -32602, "message": "input request is no longer pending"})
                    else:
                        durable_id = request_id_value or pending_request_by_wire_id.get(("input", call_id), "")
                        try:
                            if durable_id:
                                await set_pending_request_state(durable_id, "resolved")
                        except Exception:
                            await response(request_id, error={
                                "code": -32603, "message": "input request could not be durably recorded",
                            })
                            continue
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
                    session_inboxes.pop(session_id, None)
                    await response(request_id, result={} if acp else {"closed": True})
                else:
                    await response(request_id, error={"code": -32601, "message": f"method not found: {method}"})
            except (json.JSONDecodeError, ValueError) as exc:
                await response(None, error={"code": -32700, "message": str(exc)})

        for event in active.values():
            event.set()
        for pending_id, meta in list(pending_request_meta.items()):
            try:
                await set_pending_request_state(pending_id, "invalidated")
            except Exception:
                pass
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
        if task_cancel_responders:
            await asyncio.gather(*list(task_cancel_responders), return_exceptions=True)
        if wait_responders:
            await asyncio.gather(*list(wait_responders), return_exceptions=True)
        await outgoing.put(None)
        await writer
    finally:
        try:
            if local_execution is not None:
                await local_execution.shutdown()
        finally:
            await memory.close()
