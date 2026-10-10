# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/agent/control.rs (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/tools/handlers/multi_agents.rs (Apache-2.0)
# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede: apps/zcode-cli/packages/core/src/subagent/runner.ts (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
"""Native child lifecycle receipts over Atlas's existing delegated worker.

Sources (Apache-2.0; lifecycle/status/result aggregation adapted to Python):
* openai/codex @ 806d9732c974bc8a51b8317c1bd8985544fe627c
  codex-rs/core/src/agent/control.rs (completion watcher, final status)
  codex-rs/core/src/tools/handlers/multi_agents.rs (collaboration status mapping)
* zai-org/ZCode @ 29628c9acdb81b703bbd4080c207a0e7ce5e276ede
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

from atlas.config import get_config
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
        if str(get_config().get("engine.kernel", "atlas")).strip().lower() != "atlas":
            raise RuntimeError("Native subagents require engine.kernel=atlas")
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
