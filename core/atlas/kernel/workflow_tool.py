# SPDX-License-Identifier: Apache-2.0
"""AtlasKernel tool adapter for the standalone DAG workflow engine."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from atlas.engine.tool_permissions import tool_allowed
from atlas.kernel.model_call import complete_stream
from atlas.kernel.subagents import KernelWorkflowSubagentRunner
from atlas.workflow import (
    WorkflowJournal,
    WorkflowResult,
    plan_workflow,
    pause_workflow,
    resume_workflow,
    run_workflow,
)


WORKFLOW_TOOL_SPEC: dict[str, Any] = {
    "name": "workflow",
    "description": (
        "Plan a larger task as a dependency graph and execute its ready tasks in parallel. "
        "Each node runs as an isolated Atlas subagent in the current workspace. Use goal for a "
        "new workflow, or resume_workflow_id to continue a previously paused workflow."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "The complete task to decompose and execute."},
            "resume_workflow_id": {
                "type": "string",
                "description": "Resume a previously paused workflow by its workflow_id.",
            },
        },
        "additionalProperties": False,
    },
}


async def execute_workflow_tool(
    agent: Any,
    runtime: Any,
    arguments: Mapping[str, Any],
    *,
    usage_callback: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Plan and execute a DAG using the caller's model, policy and run signals."""
    if not isinstance(arguments, Mapping):
        raise ValueError("Workflow arguments must be an object")
    if not tool_allowed("workflow", getattr(runtime, "tool_allow", None),
                        getattr(runtime, "tool_deny", ())):
        raise PermissionError("Workflow is not allowed in this run")
    if bool(getattr(runtime, "read_only", False)) or getattr(runtime, "mode", "act") == "plan":
        raise PermissionError("Workflow execution is unavailable in read-only plan mode")

    workspace = str(getattr(runtime, "workspace", "") or "").strip()
    if not workspace:
        raise ValueError("Workflow execution requires an active workspace")
    goal = str(arguments.get("goal") or "").strip()
    resume_id = str(arguments.get("resume_workflow_id") or "").strip()
    if bool(goal) == bool(resume_id):
        raise ValueError("Provide exactly one of goal or resume_workflow_id")

    from atlas.config import get_config

    config = get_config()
    try:
        max_parallel = int(config.get("engine.workflow_max_parallel", 4))
    except (TypeError, ValueError) as exc:
        raise ValueError("engine.workflow_max_parallel must be a positive integer") from exc
    if max_parallel < 1:
        raise ValueError("engine.workflow_max_parallel must be a positive integer")
    configured_retries = config.get("engine.model_retries")
    max_retries = int(configured_retries) if configured_retries is not None else None

    selected_model = str(
        getattr(runtime, "model", None) or agent._model_mgr.current_model
    )
    cancel_event = getattr(runtime, "cancel_event", None)
    pause_event = getattr(runtime, "pause_event", None)
    journal = WorkflowJournal()

    async def call_planner(*, prompt: str, model: str | None) -> str:
        await _wait_for_planner_resume(pause_event, cancel_event)

        async def hold_while_paused(_text: str) -> None:
            await _wait_for_planner_resume(pause_event, cancel_event)

        result = await complete_stream(
            agent,
            model or selected_model,
            [{"role": "user", "content": prompt}],
            [],
            reasoning_effort=getattr(runtime, "reasoning_effort", None),
            max_output_tokens=int(config.get("engine.workflow_planner_max_tokens", 4096)),
            cancel_event=cancel_event,
            max_retries=max_retries,
            fallback_models=list(getattr(runtime, "fallback_models", []) or []),
            on_text=hold_while_paused,
            usage_budget=getattr(runtime, "kernel_usage_budget", None),
        )
        await _wait_for_planner_resume(pause_event, cancel_event)
        usage = _planner_usage(result)
        if usage_callback is not None:
            await _maybe_await(usage_callback(usage))
        return result.text

    if not resume_id:
        graph = await plan_workflow(
            goal,
            workspace=workspace,
            call_model=call_planner,
            model=selected_model,
        )
        graph.workflow_id = str(uuid.uuid4())
        workflow_id = graph.workflow_id
    else:
        workflow_id = resume_id

    conversation_id = str(getattr(runtime, "conversation_id", "") or "")

    async def on_workflow_event(event: dict[str, Any]) -> None:
        if conversation_id and event.get("type") in {"workflow_started", "workflow_resumed"}:
            journal.bind_context(workflow_id, conversation_id, kind="expert")
        await _workflow_event(runtime, event)

    resume_existing = bool(resume_id)
    while True:
        runner = KernelWorkflowSubagentRunner(agent, runtime, workflow_id)
        execute_workflow = (
            resume_workflow(
                workflow_id,
                runner,
                max_parallel=max_parallel,
                on_event=on_workflow_event,
                planner=call_planner,
                journal=journal,
            )
            if resume_existing else run_workflow(
                graph,
                runner,
                max_parallel=max_parallel,
                on_event=on_workflow_event,
                planner=call_planner,
                journal=journal,
            )
        )
        result = await _run_with_pause_bridge(
            execute_workflow,
            workflow_id=workflow_id,
            journal=journal,
            pause_event=pause_event,
            cancel_event=cancel_event,
        )
        if result.status != "paused" or not journal.pause_requested(workflow_id):
            break
        await _wait_for_planner_resume(pause_event, cancel_event)
        resume_existing = True

    await _complete_workflow_group(runtime, result)
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "error": result.error,
        "nodes": [
            {
                "id": node.id,
                "title": node.title,
                "goal": node.goal,
                "status": node.status,
                "attempts": node.attempts,
                "error": node.error,
                "output": node.output,
                "metadata": node.metadata,
            }
            for node in result.graph.nodes
        ],
    }


async def _run_with_pause_bridge(
    initial: Any,
    *,
    workflow_id: str,
    journal: WorkflowJournal,
    pause_event: Any,
    cancel_event: Any,
) -> WorkflowResult:
    """Translate the run's cleared pause event into a journaled workflow pause."""
    task = asyncio.create_task(initial)
    watcher = asyncio.create_task(
        _watch_pause(workflow_id, journal, pause_event, cancel_event),
    ) if pause_event is not None else None
    try:
        return await task
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


async def _watch_pause(
    workflow_id: str,
    journal: WorkflowJournal,
    pause_event: Any,
    cancel_event: Any,
) -> None:
    """Watch the legacy clear/set Event, which has no wait-for-clear operation."""
    requested = False
    while True:
        if cancel_event is not None and cancel_event.is_set():
            return
        if not pause_event.is_set() and not requested:
            try:
                await asyncio.to_thread(pause_workflow, workflow_id, journal=journal)
            except KeyError:
                pass
            else:
                requested = True
        elif pause_event.is_set() and requested:
            try:
                await asyncio.to_thread(journal.clear_pause_request, workflow_id)
            except KeyError:
                pass
            requested = False
        await asyncio.sleep(0.05)


async def _workflow_event(runtime: Any, event: dict[str, Any]) -> None:
    kind = str(event.get("type") or "workflow")
    if kind == "workflow_started":
        text = "工作流已启动，正在执行依赖就绪的子任务。"
    elif kind == "workflow_resumed":
        text = "工作流已恢复。"
    elif kind == "node_started":
        text = str(event.get("message") or "工作流子任务已启动。")
    elif kind == "node_completed":
        text = str(event.get("message") or "工作流子任务已完成。")
    elif kind == "node_failed":
        text = str(event.get("message") or "工作流子任务失败，正在处理依赖或重试。")
    elif kind == "planner_started":
        text = "工作流正在细化后续任务。"
    elif kind == "workflow_paused":
        text = "工作流已暂停，等待运行恢复。"
    elif kind == "workflow_completed":
        text = "工作流节点已完成。"
    else:
        return
    await _queue_runtime_event(runtime, {"type": "run_status", "status": "running", "text": text})


async def _complete_workflow_group(runtime: Any, result: WorkflowResult) -> None:
    callback = getattr(runtime, "subtask_group_completed", None)
    ordered = result.graph.nodes
    summary = f"工作流 {result.workflow_id} 状态：{result.status}。"
    payload = {
        "subtask_id": result.workflow_id,
        "group_id": result.workflow_id,
        "status": result.status,
        "summary": summary,
        "results": [
            {
                "index": index,
                "title": node.title or node.id,
                "status": node.status,
                "summary": node.output or node.error or "",
                "changed_files": list(node.metadata.get("changed_files") or []),
                "metadata": node.metadata,
            }
            for index, node in enumerate(ordered)
        ],
    }
    if callable(callback):
        await _maybe_await(callback(payload))
    else:
        await _queue_runtime_event(runtime, {"type": "subtask.group_completed", **payload})


async def _queue_runtime_event(runtime: Any, event: dict[str, Any]) -> None:
    queue = getattr(runtime, "event_queue", None)
    if queue is not None:
        await queue.put(event)


def _planner_usage(result: Any) -> dict[str, Any]:
    usage = dict(getattr(result, "usage", {}) or {})
    def integer(*keys: str) -> int:
        for key in keys:
            if usage.get(key) is not None:
                try:
                    return max(0, int(usage[key]))
                except (TypeError, ValueError):
                    return 0
        return 0

    return {
        "request_id": uuid.uuid4().hex,
        "purpose": "workflow_planner",
        "model": getattr(result, "model", None),
        "provider": getattr(result, "provider", None),
        "input_tokens": integer("prompt_tokens", "input_tokens", "input"),
        "output_tokens": integer("completion_tokens", "output_tokens", "output"),
        "duration_ms": getattr(result, "duration_ms", None),
        "usage_available": bool(usage),
        **{key: value for key, value in usage.items() if key not in {
            "prompt_tokens", "input_tokens", "input", "completion_tokens", "output_tokens", "output",
        }},
    }


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _wait_for_planner_resume(pause_event: Any, cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError
    if pause_event is None or pause_event.is_set():
        return
    pause_waiter = asyncio.create_task(pause_event.wait())
    waiters = {pause_waiter}
    if cancel_event is not None:
        waiters.add(asyncio.create_task(cancel_event.wait()))
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError


__all__ = ["WORKFLOW_TOOL_SPEC", "execute_workflow_tool"]
