# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/agent/control.rs (Apache-2.0)
# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/tools/handlers/multi_agents.rs (Apache-2.0)
# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/subagent/runner.ts (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
"""Native child lifecycle receipts over Atlas's existing delegated worker.

Sources (Apache-2.0; lifecycle/status/result aggregation adapted to Python):
* openai/codex @ 6c0c6759d0617d7670826b61aca0a931bbb6db1f
  codex-rs/core/src/agent/control.rs (completion watcher, final status)
  codex-rs/core/src/tools/handlers/multi_agents.rs (collaboration status mapping)
* zai-org/ZCode @ aac4755666d09fdcd70272fcf063c077a639015f
  apps/zcode-cli/packages/core/src/subagent/runner.ts
  (completed/failed receipt, duration/token aggregation, cancellation cleanup)

Atlas delta: retain _run_atlas_subtask's canonical session, policy and hooks.
No additional session store, worker loop, permission authority or worktree owner.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from atlas.logs import LOG_DIR


class SubagentManager:
    """Wrap the original bound AgentOrchestrator._run_atlas_subtask method.

    Install ``delegation.atlas_runner = manager.run`` after saving that original
    bound method in this manager. DelegationService remains the lifecycle owner:
    its cancellation, steering and worktree policy continue to apply. The bound
    runner creates/deletes the independent canonical child conversation and fires
    SubagentStart/SubagentStop (including stop-hook continuations) itself.
    """

    def __init__(self, runner: Callable[..., Any]) -> None:
        self._runner = runner

    async def run(
        self, *, goal: str, context: str | None, cwd: str | None,
        subtask_id: str, atlas_options: dict[str, Any], on_progress: Callable[[str], Any],
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", subtask_id):
            raise ValueError("Invalid subtask_id")
        started = time.monotonic()
        options = dict(atlas_options)
        parent_hook = options.get("user_hook_callback")
        changed_files: set[str] = set()
        session_id: str | None = None
        untracked_mutations = False

        async def hook(event: str, payload: dict[str, Any]) -> Any:
            nonlocal session_id, untracked_mutations
            # Forward first and retain the exact hook outcome (permission/stop
            # decisions and additional context), rather than swallowing it.
            outcome = parent_hook(event, payload) if parent_hook else None
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if event == "SessionEnd":
                session_id = str(payload.get("conversation_id") or "") or None
            if event in {"tool.after", "PostToolUse"}:
                result = payload.get("result") or payload.get("tool_response") or {}
                args = payload.get("parameters") or payload.get("tool_input") or {}
                name = str(payload.get("tool_name") or "")
                if isinstance(result, dict) and not result.get("is_error"):
                    receipt = result.get("data") or result
                    if isinstance(receipt, dict):
                        for item in receipt.get("changed_files", []) or []:
                            if isinstance(item, str):
                                changed_files.add(item)
                    if isinstance(args, dict):
                        writes_path = name in {"local_edit", "edit", "write"} or (
                            name == "local_file" and args.get("action") in
                            {"write", "append", "delete", "move", "copy"}
                        )
                        if writes_path:
                            for key in ("path", "file_path", "destination"):
                                raw = args.get(key)
                                if isinstance(raw, str) and raw:
                                    candidate = Path(raw)
                                    changed_files.add(str(candidate if candidate.is_absolute()
                                                          else Path(cwd or Path.cwd()) / candidate))
                    # Shell can modify arbitrary files; a tool receipt without a
                    # file list is not proof that no files changed.
                    if name in {"local_process", "bash", "shell", "apply_patch"}:
                        if not isinstance(receipt, dict) or not receipt.get("changed_files"):
                            untracked_mutations = True
            return outcome

        options["user_hook_callback"] = hook
        # Approval callback, allow/deny lists, role/depth, cancellation and
        # sandbox/SSH callbacks are copied untouched into the native worker.
        try:
            result = await self._runner(
                goal=goal, context=context, cwd=cwd, subtask_id=subtask_id,
                atlas_options=options, on_progress=on_progress,
            )
        except asyncio.CancelledError:
            raise  # DelegationService must relay cancellation to its parent.
        except Exception as exc:
            result = {"status": "failed", "result": f"{type(exc).__name__}: {exc}", "evidence": []}

        evidence = list(result.get("evidence") or [])
        token_rows = [row for row in evidence if isinstance(row, dict)]
        log_paths = sorted((LOG_DIR / "runs").glob(f"*/{subtask_id}.jsonl"))
        if not token_rows and log_paths:
            # Native failures may raise before returning usage; recover only
            # compact model usage events, never transcript/tool output.
            try:
                for line in log_paths[-1].read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    if row.get("event") == "model_request" and "duration_ms" in row:
                        token_rows.append(row)
                evidence = token_rows
            except (OSError, ValueError, TypeError):
                pass

        def tokens(row: dict[str, Any], *names: str) -> int:
            for name in names:
                value = row.get(name)
                if value is not None:
                    try:
                        return max(0, int(value))
                    except (TypeError, ValueError):
                        return 0
            return 0

        input_tokens = sum(tokens(row, "input_tokens", "prompt_tokens") for row in token_rows)
        output_tokens = sum(tokens(row, "output_tokens", "completion_tokens") for row in token_rows)
        return {
            **result, "subtask_id": subtask_id, "session_id": session_id,
            "status": result.get("status", "failed"),
            "changed_files": sorted(changed_files | set(result.get("changed_files") or [])),
            "changed_files_complete": not untracked_mutations,
            "evidence": evidence,
            "tokens": {"input": input_tokens, "output": output_tokens,
                       "total": input_tokens + output_tokens,
                       "available": any(any(row.get(key) is not None for key in
                                            ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"))
                                        for row in token_rows)},
            "duration_ms": int((time.monotonic() - started) * 1000),
            "log_path": str(log_paths[-1]) if log_paths else None,
        }


class KernelWorkflowSubagentRunner:
    """Run each workflow node through Atlas's canonical child-run lifecycle.

    The supplied ``AgentOrchestrator._run_atlas_subtask`` creates an isolated
    conversation and calls ``AgentOrchestrator.run``. With the Atlas engine
    selected, that public run path reaches the same ``AtlasKernel.run`` loop.
    """

    def __init__(self, agent: Any, runtime: Any, workflow_id: str) -> None:
        runner = getattr(agent, "_run_atlas_subtask", None)
        if not callable(runner):
            raise RuntimeError("Atlas workflow nodes require the native subagent runner")
        self._manager = SubagentManager(runner)
        self._agent = agent
        self._runtime = runtime
        self._workflow_id = workflow_id
        self._sequence = 0

    async def run(
        self, *, goal: str, context: str, workspace: str, model: str | None,
    ) -> Any:
        from atlas.workflow.types import NodeResult

        self._sequence += 1
        started = time.monotonic()
        subtask_id = _workflow_subtask_id(self._workflow_id, self._sequence)
        group_data = {
            "group_id": self._workflow_id,
            "workflow_id": self._workflow_id,
            "index": self._sequence,
            "title": goal[:160],
        }
        parent_cancel = getattr(self._runtime, "cancel_event", None)
        subtask_cancel: Any = None
        start_callback = getattr(self._runtime, "subtask_started", None)
        if callable(start_callback):
            subtask_cancel = await _call_callback(
                start_callback, subtask_id, goal, "atlas", group_data,
            )
        cancel_event = _AnyCancellationEvent(parent_cancel, subtask_cancel)

        async def on_progress(text: str) -> None:
            callback = getattr(self._runtime, "subtask_progress", None)
            if callable(callback):
                await _call_callback(callback, subtask_id, str(text), group_data)
            else:
                await _queue_runtime_event(self._runtime, {
                    "type": "subtask.output",
                    "subtask_id": subtask_id,
                    "text": str(text),
                    **group_data,
                })

        options = {
            "model": model,
            "cancel_event": cancel_event,
            "pause_event": getattr(self._runtime, "pause_event", None),
            "approval_callback": getattr(self._runtime, "approval_callback", None),
            "tool_allow": getattr(self._runtime, "tool_allow", None),
            "tool_deny": [*list(getattr(self._runtime, "tool_deny", []) or []), "workflow"],
            "permission_mode": getattr(self._runtime, "permission_mode", "full_access"),
            "allowed_paths": list(getattr(self._runtime, "allowed_paths", []) or []),
            "workspace_trusted": bool(getattr(self._runtime, "workspace_trusted", False)),
            "user_hook_callback": getattr(self._runtime, "user_hook_callback", None),
            "ssh_tool_callback": getattr(self._runtime, "ssh_tool_callback", None),
            "ssh_checkpoint_callback": getattr(self._runtime, "ssh_checkpoint_callback", None),
            "sandbox_tool_callback": getattr(self._runtime, "sandbox_tool_callback", None),
            "sandbox_enabled": bool(getattr(self._runtime, "sandbox_enabled", False)),
            "project_id": getattr(self._runtime, "project_id", None),
            "task_id": getattr(self._runtime, "task_id", None),
            "reasoning_effort": getattr(self._runtime, "reasoning_effort", None),
            "agent_role": "leaf",
            "agent_type": "workflow_node",
            "depth": int(getattr(self._runtime, "agent_depth", 0) or 0) + 1,
        }
        completion_sent = False

        async def complete(status: str, summary: str) -> None:
            nonlocal completion_sent
            if completion_sent:
                return
            completion_sent = True
            await self._complete_subtask(subtask_id, status, summary, started, group_data)

        try:
            result = await self._manager.run(
                goal=goal,
                context=context,
                cwd=workspace,
                subtask_id=subtask_id,
                atlas_options=options,
                on_progress=on_progress,
            )
            status = str(result.get("status") or "failed")
            summary = str(result.get("result") or "Workflow node returned no result.")
            if status == "cancelled":
                group_data["session_id"] = str(result.get("session_id") or "")
                group_data["tokens"] = result.get("tokens") or {}
                await complete(status, summary)
                if parent_cancel is not None and parent_cancel.is_set():
                    raise asyncio.CancelledError
                raise RuntimeError("Workflow node was cancelled")
            if status != "completed":
                group_data["session_id"] = str(result.get("session_id") or "")
                group_data["tokens"] = result.get("tokens") or {}
                await complete("failed", summary)
                raise RuntimeError(summary)
            group_data["session_id"] = str(result.get("session_id") or "")
            group_data["tokens"] = result.get("tokens") or {}
            await complete(status, summary)
            return NodeResult(
                response=summary,
                model=model,
                metadata={
                    key: result.get(key)
                    for key in ("session_id", "changed_files", "changed_files_complete", "tokens")
                    if key in result
                },
            )
        except asyncio.CancelledError:
            await complete("cancelled", "Workflow node cancelled.")
            raise
        except Exception as exc:
            await complete("failed", f"{type(exc).__name__}: {exc}")
            raise

    async def _complete_subtask(
        self, subtask_id: str, status: str, summary: str,
        started: float, group_data: dict[str, Any],
    ) -> None:
        callback = getattr(self._runtime, "subtask_completed", None)
        if callable(callback):
            await _call_callback(
                callback, subtask_id, status, summary[:4000],
                int((time.monotonic() - started) * 1000), group_data,
            )
        else:
            await _queue_runtime_event(self._runtime, {
                "type": "subtask.completed",
                "subtask_id": subtask_id,
                "status": status,
                "summary": summary[:4000],
                "duration_ms": int((time.monotonic() - started) * 1000),
                **group_data,
            })


class _AnyCancellationEvent:
    """Read-only cancellation view that combines the parent and node event."""

    def __init__(self, *events: Any) -> None:
        self._events = tuple(event for event in events if event is not None)

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)

    async def wait(self) -> bool:
        if self.is_set():
            return True
        waiters = [asyncio.create_task(event.wait()) for event in self._events]
        try:
            if not waiters:
                await asyncio.Future()
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            return True
        finally:
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)


async def _call_callback(callback: Callable[..., Any], *args: Any) -> Any:
    result = callback(*args)
    return await result if inspect.isawaitable(result) else result


async def _queue_runtime_event(runtime: Any, event: dict[str, Any]) -> None:
    queue = getattr(runtime, "event_queue", None)
    if queue is not None:
        await queue.put(event)


def _workflow_subtask_id(workflow_id: str, sequence: int) -> str:
    safe_workflow = re.sub(r"[^A-Za-z0-9_-]", "_", workflow_id)[:32]
    value = f"wf_{safe_workflow}_{sequence}_{uuid_hex(6)}"
    return value[:128]


def uuid_hex(length: int) -> str:
    from uuid import uuid4

    return uuid4().hex[:length]
