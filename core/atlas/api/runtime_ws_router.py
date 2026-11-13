"""Runtime chat WebSocket protocol, bound to each FastAPI app's services."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.runtime import RunState
from atlas.approval_policy import grant as grant_approval_permission

router = APIRouter()


@router.get("/api/runtime/runs/{run_id}/events")
async def page_run_events(
    run_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict[str, object]:
    """Read a bounded event page for repairing a live WebSocket sequence gap."""
    run = services.runtime_mgr.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run state is no longer available")
    async with run.event_lock:
        events = [event for event in run.events if int(event.get("sequence", 0)) > after_sequence]
        page = events[:limit]
        cursor = max((int(event.get("sequence", 0)) for event in run.events), default=0)
        header = run.events[:1]
        tail = run.events[-10:]
        return {
            "events": page,
            "next_cursor": int(page[-1]["sequence"]) if page else after_sequence,
            "cursor": cursor,
            "header": header,
            "tail": tail,
            "projection_baseline": {"run_id": run_id, "sequence": cursor},
            "has_more": bool(page and int(page[-1]["sequence"]) < cursor),
        }


@router.websocket("/ws/chat")
async def ws_chat(
    ws: WebSocket, services: Annotated[AppServices, Depends(get_app_services)],
) -> None:
    """Runtime Event Protocol 1.2 WebSocket endpoint.

    Client sends:
        {"type": "run.start", "run_id": "...", "content": "...",
         "conversation_id": "...", "model": "..."}
        {"type": "resume", "run_id": "...", "after_sequence": N}
        {"type": "run.cancel", "run_id": "..."}
        {"type": "run.pause", "run_id": "..."}
        {"type": "run.resume", "run_id": "..."}
        {"type": "approval.response", "event_id": "...", "choice": "allow"|"deny"}

    Server sends:
        {"type": "agent_event", "run_id": "...", "event_id": "...", "sequence": N,
         "timestamp": "...", "event": "<event_type>", "data": {...}}

    Event types: run.started, run.status, run.phase, message.delta,
    message.completed, tool.started, tool.completed, approval.required,
    approval.responded, artifact.updated, run.paused, run.resumed,
    run.completed, run.failed, run.cancelled
    """
    conn_id = str(uuid.uuid4())
    await services.runtime_mgr.connect(ws, conn_id)

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type == "run.start":
                await services.runtime_start_handler(conn_id, data, services.runtime_mgr)

            elif msg_type == "resume":
                await services.runtime_resume_handler(conn_id, data, services.runtime_mgr)

            elif msg_type == "rules.trust":
                await services.rules_trust_handler(conn_id, data, services.runtime_mgr)

            elif msg_type == "run.cancel":
                run_id = data.get("run_id", "")
                run = services.runtime_mgr.runs.get(run_id)
                if run and run.status not in ("completed", "failed", "cancelled"):
                    run.cancel_event.set()
                    if run.trust_future is not None and not run.trust_future.done():
                        run.trust_future.set_result(False)
                    elif run.task is not None and not run.task.done():
                        run.task.cancel()
                    if run.task is not None:
                        await asyncio.gather(run.task, return_exceptions=True)
                    if not any(event.get("event") in (
                        "run.completed", "run.failed", "run.cancelled",
                    ) for event in run.events):
                        run.status = "cancelled"
                        await services.runtime_mgr.send_run(
                            run, run.next_envelope("run.cancelled", {}), conn_id,
                        )

            elif msg_type == "run.steer":
                run_id = str(data.get("run_id", ""))
                run = services.runtime_mgr.runs.get(run_id)
                if not run:
                    rejected = RunState(run_id, "", "")
                    await services.runtime_mgr.send(conn_id, rejected.next_envelope(
                        "run.steer.rejected", {"reason": "run_not_active"},
                    ))
                else:
                    if data.get("inject") is True or "lane" in data:
                        from atlas.api.run_drive import _inject_run_message

                        reason, _inbox_event_id = await _inject_run_message(run, data)
                    else:
                        from atlas.engine.steer_dispatch import queue_run_steer

                        reason = queue_run_steer(run, data)
                    if reason:
                        rejected = RunState(run_id, "", "")
                        await services.runtime_mgr.send(conn_id, rejected.next_envelope(
                            "run.steer.rejected", {"reason": reason},
                        ))

            elif msg_type == "subtask.message":
                run_id = str(data.get("run_id", ""))
                subtask_id = str(data.get("subtask_id", ""))
                text = data.get("text")
                run = services.runtime_mgr.runs.get(run_id)
                delegation = getattr(services.orchestrator, "_delegation", None)
                service = delegation if services.orchestrator else None
                if (run is None or service is None or not isinstance(text, str)
                        or not service.steer_subtask(subtask_id, text)):
                    # Report every refusal, including the ``run is None`` case: the
                    # renderer correlates on ``data.subtask_id`` and would otherwise
                    # show its optimistic 「已发送补充要求」 forever, because
                    # steerSubtask() here returns True before the outcome is known.
                    if run is None:
                        reason = "run_not_active"
                    elif service is None:
                        reason = "orchestrator_unavailable"
                    elif not isinstance(text, str):
                        reason = "invalid_content"
                    else:
                        reason = "subtask_not_active"
                    if run is not None:
                        await services.runtime_mgr.send_run(run, run.next_envelope(
                            "subtask.steer_rejected",
                            {"subtask_id": subtask_id, "reason": reason},
                        ), conn_id)
                    else:
                        # No run to address and nothing to persist: reply on the
                        # connection that asked, using a throwaway envelope.
                        rejected = RunState(run_id, "", "")
                        await services.runtime_mgr.send(conn_id, rejected.next_envelope(
                            "subtask.steer_rejected",
                            {"subtask_id": subtask_id, "reason": reason},
                        ))
                else:
                    await services.runtime_mgr.send_run(run, run.next_envelope(
                        "subtask.steered", {"subtask_id": subtask_id, "text": text.strip()},
                    ), conn_id)

            elif msg_type == "input.response":
                event_id = str(data.get("event_id", ""))
                for run in services.runtime_mgr.runs.values():
                    future = run.input_futures.pop(event_id, None)
                    if future and not future.done():
                        future.set_result(str(data.get("text", "")))
                        break

            elif msg_type == "run.plan.approve":
                run = services.runtime_mgr.runs.get(str(data.get("run_id", "")))
                if (run and run.status == "waiting" and run.plan_future
                        and not run.plan_future.done()
                        and data.get("event_id") == f"plan:{run.run_id}"):
                    run.plan_future.set_result({
                        "action": "approve", "edits": str(data.get("edits", "")),
                    })

            elif msg_type == "run.pause":
                run_id = data.get("run_id", "")
                run = services.runtime_mgr.runs.get(run_id)
                if run and run.status == "running":
                    run.pause_event.clear()
                    run.status = "paused"
                    env = run.next_envelope("run.paused", {"status": "paused"})
                    await services.runtime_mgr.persist_run(run)
                    await services.runtime_mgr.send(conn_id, env)

            elif msg_type == "run.resume":
                run_id = data.get("run_id", "")
                run = services.runtime_mgr.runs.get(run_id)
                if run and run.status == "paused":
                    run.pause_event.set()
                    run.status = "running"
                    env = run.next_envelope("run.resumed", {"status": "running"})
                    await services.runtime_mgr.persist_run(run)
                    await services.runtime_mgr.send(conn_id, env)

            elif msg_type in {"run.background", "run.foreground"}:
                run = services.runtime_mgr.runs.get(str(data.get("run_id", "")))
                if run and run.status not in {"completed", "failed", "cancelled"}:
                    run.background = msg_type == "run.background"
                    env = run.next_envelope("run.background", {"background": run.background})
                    await services.runtime_mgr.persist_run(run)
                    await services.runtime_mgr.send(conn_id, env)

            elif msg_type == "approval.response":
                event_id = str(data.get("event_id", ""))
                requested_choice = str(data.get("choice", "deny"))
                reason = data.get("reason")
                reason = str(reason).strip()[:1000] if reason is not None else ""
                if requested_choice == "allow":  # protocol 1.2 compatibility
                    requested_choice = "allow_once"
                # Find the run that has this approval
                for run in services.runtime_mgr.runs.values():
                    fut = run.approval_futures.pop(event_id, None)
                    if fut and not fut.done():
                        context = run.approval_contexts.get(event_id, {})
                        permission = context.get("permission_scope")
                        choice = requested_choice
                        if choice == "allow_always":
                            if not context.get("allow_always_available") or not permission:
                                choice = "deny"
                                reason = "此请求没有可安全持久化的权限范围，操作未执行。"
                            else:
                                try:
                                    await asyncio.to_thread(grant_approval_permission, permission)
                                except (OSError, ValueError):
                                    choice = "deny"
                                    reason = "始终允许无法安全保存，操作未执行。"
                        if choice in {"allow_once", "allow_always"}:
                            fut.set_result("allow")
                        elif choice == "deny":
                            reason = reason or "用户拒绝了此操作。"
                            fut.set_result(f"deny:{reason}")
                        else:
                            # Unknown choices fail closed and preserve the reason in the execution result.
                            choice = "deny"
                            reason = "无法识别的审批选择，操作未执行。"
                            fut.set_result(f"deny:{reason}")
                        response_data: dict[str, object] = {
                            "event_id": event_id, "choice": choice,
                        }
                        if reason:
                            response_data["reason"] = reason
                        if permission is not None:
                            response_data["permission_scope"] = permission
                        env = run.next_envelope("approval.responded", response_data)
                        await services.runtime_mgr.persist_run(run)
                        await services.runtime_mgr.send(conn_id, env)
                        break

    except WebSocketDisconnect:
        services.runtime_mgr.disconnect(conn_id)
