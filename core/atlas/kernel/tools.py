# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/tools/parallel.rs (Apache-2.0)
# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/tools/orchestrator.rs (Apache-2.0)
# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/tool/scheduler.ts (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
"""Bounded read concurrency around Atlas's existing approval/dispatch route.

The dispatch callback is the canonical orchestrator, never a raw tool handler.
Sandbox escalation remains owned by that route: uncertain writes are not retried
by this scheduler. Unknown tools are exclusive, even with model safety metadata.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from atlas.engine.tool_permissions import tool_allowed
from atlas.kernel.state import ToolReceipt

Dispatch = Callable[[str, str, dict[str, Any]], Awaitable[Any]]
READ_ONLY_TOOLS = frozenset({
    "read_file", "search_files", "session_search", "web_search", "web_fetch",
    "read", "glob", "grep", "list_directory", "lsp_diagnostics", "lsp_hover",
    "lsp_definition", "lsp_references", "lsp_document_symbols", "build_repo_map",
    "read_office", "coding.repo_map", "coding.ast_grep.run",
})
EDIT_TOOL_NAMES = frozenset({"apply_patch", "edit", "write"})


def kernel_tool_schemas(*, include_workflow: bool) -> list[dict[str, Any]]:
    """Return the extra function schemas owned by AtlasKernel itself."""
    import copy

    from atlas.repomap import REPOMAP_TOOL_SPEC

    repo_parameters = copy.deepcopy(REPOMAP_TOOL_SPEC["input_schema"])
    repo_parameters["properties"].pop("root", None)
    repo_parameters["required"] = [
        name for name in repo_parameters.get("required", []) if name != "root"
    ]
    schemas = [{
        "type": "function",
        "function": {
            "name": str(REPOMAP_TOOL_SPEC["name"]),
            "description": (
                str(REPOMAP_TOOL_SPEC.get("description", ""))
                + " The repository root is inferred from the active Atlas workspace."
            ),
            "parameters": repo_parameters,
        },
    }]
    if include_workflow:
        from atlas.kernel.workflow_tool import WORKFLOW_TOOL_SPEC

        schemas.append({
            "type": "function",
            "function": {
                "name": str(WORKFLOW_TOOL_SPEC["name"]),
                "description": str(WORKFLOW_TOOL_SPEC["description"]),
                "parameters": copy.deepcopy(WORKFLOW_TOOL_SPEC["parameters"]),
            },
        })
    return schemas


@dataclass(slots=True)
class ToolExecutionResult:
    call_id: str
    name: str
    output: Any
    receipt: ToolReceipt


def _call_identity(call: Any) -> tuple[str, str]:
    if not isinstance(call, dict):
        return "", ""
    function = call.get("function")
    if function is None:
        function = call
    if not isinstance(function, dict):
        return str(call.get("id") or call.get("call_id") or ""), ""
    return str(call.get("id") or call.get("call_id") or ""), str(function.get("name") or "")


def _call(call: Any) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(call, dict):
        raise ValueError("Tool call must be an object")
    function = call.get("function")
    if function is None:
        function = call
    elif not isinstance(function, dict):
        raise ValueError("Tool function must be an object")
    args = function.get("arguments", call.get("arguments", {}))
    if isinstance(args, str):
        args = json.loads(args or "{}")
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be an object")
    return str(call.get("id") or call.get("call_id") or ""), str(function.get("name") or ""), args


def is_error(output: Any) -> bool:
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            return False
    return isinstance(output, dict) and bool(
        output.get("is_error") or output.get("error") or output.get("success") is False
    )


class ToolScheduler:
    def __init__(self, dispatch: Dispatch, *, max_concurrency: int = 10,
                 allow: Any = None, deny: Any = (),
                 read_only: Callable[[str, dict[str, Any]], bool] | None = None) -> None:
        self.dispatch = dispatch
        self.allow, self.deny = allow, deny
        self.read_only = read_only
        self.max_concurrency = max(1, int(max_concurrency))
        self._slots = asyncio.Semaphore(self.max_concurrency)
        # Serialize batches as well: a write in another caller cannot overlap reads.
        self._batch_lock = asyncio.Lock()

    def supports_parallel(self, call: dict[str, Any]) -> bool:
        _, name, args = _call(call)
        if name.startswith(("computer_", "browser_")) or name in {
            "terminal", "local_shell", "local_exec", "local_process", "process_manage",
            "execute_code", "exec_command", "write_stdin",
            "write_file", "patch", "apply_patch", "edit", "write", "local_edit",
        }:
            return False
        if name == "local_file":
            return args.get("action") in {"read", "list", "glob", "search", "stat"}
        if self.read_only is not None:
            return bool(self.read_only(name, args))
        return name in READ_ONLY_TOOLS

    async def _execute(
        self,
        call: dict[str, Any],
        cancelled_indices: set[int] | None = None,
        index: int | None = None,
    ) -> ToolExecutionResult:
        started = time.monotonic()
        call_id, name = _call_identity(call)
        handler_started = False
        state = "not_started"
        try:
            call_id, name, args = _call(call)
            if not name or not call_id:
                raise ValueError("Tool calls require an id and name")
            policy_name = "local_edit" if name in EDIT_TOOL_NAMES else name
            if not tool_allowed(policy_name, self.allow, self.deny):
                state = "failed"
                output = {
                    "is_error": True,
                    "error": "Tool is not allowed in this run",
                    "outcome": state,
                }
            else:
                async with self._slots:
                    state = "unknown"
                    handler_started = True
                    output = await self.dispatch(call_id, name, args)
                state = "failed" if is_error(output) else "completed"
                if isinstance(output, dict):
                    state = str(output.get("outcome") or state)
        except asyncio.CancelledError:
            if cancelled_indices is not None and index is not None:
                cancelled_indices.add(index)
            state = "cancelled"
            phase = "during execution" if handler_started else "before execution"
            output = {
                "is_error": True,
                "error": f"Tool call cancelled {phase}",
                "outcome": state,
            }
        except Exception as exc:
            state = "failed"
            output = {
                "is_error": True,
                "error": f"{type(exc).__name__}: {exc}",
                "outcome": state,
            }
        ref = output.get("output_ref") if isinstance(output, dict) else None
        receipt = ToolReceipt(call_id, name, state, int((time.monotonic() - started) * 1000), ref)
        return ToolExecutionResult(call_id, name, output, receipt)

    async def execute(self, call: dict[str, Any]) -> ToolExecutionResult:
        return (await self.run([call]))[0]

    async def _execute_parallel(
        self,
        calls: list[tuple[int, dict[str, Any]]],
        cancelled_indices: set[int],
    ) -> tuple[list[ToolExecutionResult], bool]:
        tasks = [
            asyncio.create_task(self._execute(call, cancelled_indices, index))
            for index, call in calls
        ]
        try:
            return list(await asyncio.gather(*tasks)), False
        except asyncio.CancelledError:
            # Keep one terminal result per started call when the batch is stopped.
            # _execute turns handler cancellation into a result; tasks cancelled
            # before their coroutine begins are represented here as not started.
            for task in tasks:
                if not task.done():
                    task.cancel()
            settled = await asyncio.gather(*tasks, return_exceptions=True)
            results: list[ToolExecutionResult] = []
            for (index, call), item in zip(calls, settled):
                if isinstance(item, ToolExecutionResult):
                    results.append(item)
                elif isinstance(item, asyncio.CancelledError):
                    cancelled_indices.add(index)
                    results.append(_cancelled_result(call, started=False))
                elif isinstance(item, Exception):
                    raise item
                else:
                    raise item
            return results, True

    async def run(self, calls: list[dict[str, Any]]) -> list[ToolExecutionResult]:
        results_by_index: dict[int, ToolExecutionResult] = {}
        cancelled_indices: set[int] = set()
        reads: list[tuple[int, dict[str, Any]]] = []

        async def flush() -> bool:
            if not reads:
                return False
            pending = list(reads)
            reads.clear()
            results, cancellation_requested = await self._execute_parallel(
                pending, cancelled_indices
            )
            results_by_index.update(
                (index, result) for (index, _), result in zip(pending, results)
            )
            return cancellation_requested or any(
                index in cancelled_indices for index, _ in pending
            )

        try:
            async with self._batch_lock:
                for index, call in enumerate(calls):
                    try:
                        parallel = self.supports_parallel(call)
                    except Exception:
                        # A bad classifier must serialize the call, not prevent its
                        # canonical dispatch path from returning an error or result.
                        parallel = False
                    if parallel:
                        reads.append((index, call))
                        if len(reads) >= self.max_concurrency:
                            if await flush():
                                break
                    else:
                        if await flush():
                            break
                        result = await self._execute(call, cancelled_indices, index)
                        results_by_index[index] = result
                        if index in cancelled_indices:
                            break
                else:
                    await flush()
        except asyncio.CancelledError:
            # Cancellation while queued on the batch lock has no started handlers;
            # cancellation during a serial call is already captured by _execute.
            pass

        # A cancellation stops future dispatches, but every model-issued call gets
        # a terminal receipt, matching the parallel coordinator's abort contract.
        for index, call in enumerate(calls):
            if index not in results_by_index:
                results_by_index[index] = _cancelled_result(
                    call, started=index in cancelled_indices
                )
        return [results_by_index[index] for index in range(len(calls))]


def _cancelled_result(call: Any, *, started: bool) -> ToolExecutionResult:
    call_id, name = _call_identity(call)
    phase = "during execution" if started else "before execution"
    output = {
        "is_error": True,
        "error": f"Tool call cancelled {phase}",
        "outcome": "cancelled",
    }
    return ToolExecutionResult(
        call_id,
        name,
        output,
        ToolReceipt(call_id, name, "cancelled", 0),
    )
