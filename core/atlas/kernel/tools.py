# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/tools/parallel.rs (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/tools/orchestrator.rs (Apache-2.0)
# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede: apps/zcode-cli/packages/core/src/tool/scheduler.ts (Apache-2.0)
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
    "lsp_definition", "lsp_references", "lsp_document_symbols",
})
EDIT_TOOL_NAMES = frozenset({"apply_patch", "edit", "write"})


@dataclass(slots=True)
class ToolExecutionResult:
    call_id: str
    name: str
    output: Any
    receipt: ToolReceipt


def _call(call: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    function = call.get("function") or call
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
    return isinstance(output, dict) and bool(output.get("is_error") or output.get("error"))


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

    async def _execute(self, call: dict[str, Any]) -> ToolExecutionResult:
        started = time.monotonic()
        call_id = str(call.get("id") or call.get("call_id") or "")
        name = str((call.get("function") or call).get("name") or "")
        state = "not_started"
        try:
            call_id, name, args = _call(call)
            if not name or not call_id:
                raise ValueError("Tool calls require an id and name")
            policy_name = "local_edit" if name in EDIT_TOOL_NAMES else name
            if not tool_allowed(policy_name, self.allow, self.deny):
                output = {"is_error": True, "error": "Tool is not allowed in this run"}
            else:
                async with self._slots:
                    state = "unknown"
                    output = await self.dispatch(call_id, name, args)
                state = "failed" if is_error(output) else "completed"
                if isinstance(output, dict):
                    state = str(output.get("outcome") or state)
        except asyncio.CancelledError:
            # Cancellation must reach the batch coordinator so it never starts
            # later exclusive writes after the user has interrupted this turn.
            raise
        except Exception as exc:
            output = {"is_error": True, "error": f"{type(exc).__name__}: {exc}", "outcome": state}
        ref = output.get("output_ref") if isinstance(output, dict) else None
        receipt = ToolReceipt(call_id, name, state, int((time.monotonic() - started) * 1000), ref)
        return ToolExecutionResult(call_id, name, output, receipt)

    async def execute(self, call: dict[str, Any]) -> ToolExecutionResult:
        return (await self.run([call]))[0]

    async def run(self, calls: list[dict[str, Any]]) -> list[ToolExecutionResult]:
        async with self._batch_lock:
            results: list[ToolExecutionResult] = []
            reads: list[dict[str, Any]] = []

            async def flush() -> None:
                if reads:
                    # gather retains input order regardless of completion order.
                    results.extend(await asyncio.gather(*(self._execute(c) for c in reads)))
                    reads.clear()

            for call in calls:
                try:
                    parallel = self.supports_parallel(call)
                except (ValueError, TypeError):
                    parallel = False
                if parallel:
                    reads.append(call)
                    if len(reads) >= self.max_concurrency:
                        await flush()
                else:
                    await flush()
                    results.append(await self._execute(call))
            await flush()
            return results
