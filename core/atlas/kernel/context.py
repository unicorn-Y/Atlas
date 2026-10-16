# Behavior aligned with zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/compact/{policy,microcompact,prompt,manual}.ts (Apache-2.0)
# Behavior aligned with openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/{compact.rs,compact_remote_v2.rs,compact_remote_history.rs,compact_token_budget.rs,context_manager/} (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
# Behavior from Claude Code v2.1.296 docs: https://code.claude.com/docs/en/how-claude-code-works
"""Copy-on-success context reduction; session persistence belongs to the caller."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

DEFAULT_CONTEXT_WINDOW = 200_000
OUTPUT_RESERVE_TOKENS = 21_000
BUFFER_TOKENS = 13_000
MAX_CONSECUTIVE_FAILURES = 3
COMPACT_USER_MESSAGE_MAX_TOKENS = 20_000
COMPACTABLE_TOOLS = frozenset({
    "Read", "Bash", "Grep", "Glob", "WebFetch", "WebSearch", "Edit", "Write", "ApplyPatch",
    "read_file", "search_files", "terminal", "local_shell", "local_file", "local_edit",
    "write_file", "patch", "apply_patch", "edit", "exec_command", "web_fetch", "web_search",
    "local_exec", "local_process", "local_git", "local_edit_batch", "powershell", "execute_code",
    "session_search", "filesystem__read_text_file",
})
SUMMARY_PROMPT = (
    "Summarize this conversation for another agent to continue the same task. "
    "Preserve the user's explicit goals and constraints, the plan and completed or pending steps, "
    "important files and evidence references, decisions, errors and fixes, current work, "
    "unresolved problems, and pending tool calls with their IDs and completion state. "
    "Do not invent progress, perform tools, or continue the task. Return only a concise "
    "continuation summary."
)


def estimate_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    """Conservative UTF-8 estimate including tool arguments and message overhead."""
    return sum(8 + math.ceil(len(json.dumps(m, ensure_ascii=False, default=str).encode("utf-8")) / 3)
               for m in messages)


def _calls(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    return message.get("tool_calls") or message.get("toolCalls") or []


def _call_id(message: Mapping[str, Any]) -> str:
    return str(message.get("tool_call_id") or message.get("toolCallId") or "")


@dataclass(slots=True)
class CompactionResult:
    messages: list[dict[str, Any]]
    method: str
    before_tokens: int
    after_tokens: int
    budget_tokens: int
    error: str | None = None


class ContextManager:
    def __init__(self, config: Mapping[str, Any] | None = None, *, output_dir: str | Path | None = None):
        settings = dict(config or {})
        self.config = dict(settings.get("engine", settings))
        self.output_dir = Path(output_dir) if output_dir else None
        self.consecutive_failures = 0
        self.last_assistant_completed_at: float | None = None

    def budget(self, model_window: int = DEFAULT_CONTEXT_WINDOW) -> int:
        window = max(1, int(model_window))
        ratio = float(self.config.get("context_budget_ratio", 1.0))
        if not math.isfinite(ratio) or not 0 < ratio <= 1:
            raise ValueError("context_budget_ratio must be in (0, 1]")
        configured_cap = self.config.get("context_budget_tokens")
        cap = window if configured_cap is None else int(configured_cap)
        if cap <= 0:
            raise ValueError("context_budget_tokens must be positive")
        reserve = min(window, max(0, int(self.config.get("max_output_tokens", OUTPUT_RESERVE_TOKENS))),
                      OUTPUT_RESERVE_TOKENS)
        buffer = max(0, int(self.config.get("context_buffer_tokens", BUFFER_TOKENS)))
        return max(0, min(int(window * ratio), cap, window - reserve - buffer))

    def _output_ref(self, message: dict[str, Any], content: str) -> str | None:
        ref = message.get("output_ref")
        if ref:
            return str(ref)
        if self.output_dir is None:
            return None  # Full evidence must exist before any output can be cut.
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / (hashlib.sha256(content.encode("utf-8")).hexdigest() + ".txt")
        if not path.exists():
            try:
                with path.open("x", encoding="utf-8", newline="") as stream:
                    stream.write(content)
            except FileExistsError:
                pass
        return str(path.resolve())

    @staticmethod
    def _micro_threshold(budget_tokens: int) -> int:
        return max(0, min(int(budget_tokens * 0.9), budget_tokens - 2000))

    def microcompact(self, history: Sequence[Mapping[str, Any]], *, budget_tokens: int,
                     prefix_tokens: int = 0) -> list[dict[str, Any]]:
        messages = copy.deepcopy(list(history))
        cfg = self.config.get("microcompact", {})
        if cfg.get("enabled") is False:
            return messages
        threshold = self._micro_threshold(budget_tokens)
        idle = (self.last_assistant_completed_at is not None and
                time.time() - self.last_assistant_completed_at > float(cfg.get("idle_minutes", 60)) * 60)
        if not idle and estimate_tokens(messages) + prefix_tokens < threshold:
            return messages
        groups: list[list[int]] = []
        group: list[int] | None = None
        tool_names: dict[str, str] = {}
        allowed = cfg.get("compactable_tools", COMPACTABLE_TOOLS)
        for index, message in enumerate(messages):
            if message.get("role") == "assistant" and _calls(message):
                if group:
                    groups.append(group)
                group = []
                for call in _calls(message):
                    tool_names[str(call.get("id", ""))] = str(
                        call.get("name") or (call.get("function") or {}).get("name") or "")
            if message.get("role") != "tool" or not _call_id(message):
                continue
            content = message.get("content")
            if not isinstance(content, str) or message.get("microcompacted"):
                continue  # Structured/media outputs are protected as upstream.
            if (message.get("isError") or message.get("is_error")) and not cfg.get("clear_error_results"):
                continue
            name = message.get("name") or message.get("toolName") or tool_names.get(_call_id(message))
            if name not in allowed:
                continue
            if group is None:
                groups.append([index])
            else:
                group.append(index)
        if group:
            groups.append(group)
        keep = max(1, int(cfg.get("keep_recent_tool_results", 5)))
        head = max(0, int(cfg.get("head_chars", 2000)))
        tail = max(0, int(cfg.get("tail_chars", 2000)))
        for indices in groups[:-keep]:
            for index in indices:
                message = messages[index]
                content = message["content"]
                if len(content) <= head + tail + 256:
                    continue
                ref = self._output_ref(message, content)
                if ref is None:
                    continue
                message["content"] = (content[:head] +
                    f"\n[Old tool output shortened; full output: {ref}]\n" +
                    (content[-tail:] if tail else ""))
                message["output_ref"] = ref
                message["microcompacted"] = True
        savings = estimate_tokens(history) - estimate_tokens(messages)
        return messages if savings >= int(cfg.get("min_token_savings", 256)) else copy.deepcopy(list(history))

    async def prepare(self, history: Sequence[Mapping[str, Any]], *, model_window: int = DEFAULT_CONTEXT_WINDOW,
                      summarize: Callable[[list[dict[str, Any]], str], Awaitable[str]] | None = None,
                      preserved: Mapping[str, Any] | None = None, focus: str = "",
                      prefix_tokens: int = 0, manual: bool = False,
                      force: bool = False,
                      before_compact: Callable[[CompactionResult], Awaitable[None]] | None = None) -> CompactionResult:
        budget = self.budget(model_window)
        before = estimate_tokens(history) + prefix_tokens
        messages = await asyncio.to_thread(self.microcompact, history, budget_tokens=budget,
                                           prefix_tokens=prefix_tokens)
        after = estimate_tokens(messages) + prefix_tokens
        method = "microcompact" if messages != list(history) else "none"
        result = CompactionResult(messages, method, before, after, budget)
        announced = False
        if before_compact is not None and (method != "none" or after > budget or manual or force):
            await before_compact(result)
            announced = True
        # Hysteresis: if trimming old tool outputs could not bring the context back
        # under the microcompact threshold, summarize now. Otherwise every later
        # request nibbles one more tool result (each nibble busts the prompt cache)
        # until the hard budget is finally hit.
        if after <= self._micro_threshold(budget) and not manual and not force:
            return result
        if summarize is None:
            result.error = "context_over_budget: no summarizer available"
            return result
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES and not manual:
            result.error = "compaction_circuit_breaker"
            return result
        # Keep recent turns and every unmatched call outside the summarized range.
        keep_messages = max(1, int(self.config.get("context_keep_messages", 6)))
        cut = max(0, len(messages) - keep_messages)
        latest_user = next((i for i in range(len(messages) - 1, -1, -1)
                            if messages[i].get("role") == "user"), None)
        pending: dict[str, int] = {}
        for index, message in enumerate(messages):
            for call in _calls(message):
                pending[str(call.get("id", ""))] = index
            if message.get("role") == "tool":
                pending.pop(_call_id(message), None)
        if pending:
            cut = min(cut, min(pending.values()))
        # Move a boundary before the associated assistant call, never split pairs.
        while cut > 0 and messages[cut].get("role") == "tool":
            cut -= 1
        for index in range(cut):
            ids = {str(call.get("id", "")) for call in _calls(messages[index])}
            if any(m.get("role") == "tool" and _call_id(m) in ids for m in messages[cut:]):
                cut = index
                break
        old = [m for m in messages[:cut] if m.get("role") != "system"]
        if not old:
            result.error = "context_over_budget: no safely compactable history"
            return result
        # The hysteresis path can summarize while microcompact changed nothing and the
        # context is still under the hard budget; the caller must still get its
        # PreCompact/lease callback before a summary replaces history.
        if before_compact is not None and not announced:
            await before_compact(result)
        invariants = json.dumps(dict(preserved or {}), ensure_ascii=False, default=str)
        prompt = SUMMARY_PROMPT + "\nPreserved task state:\n" + invariants
        if focus:
            prompt += "\nUser compaction focus: " + focus
        try:
            summary = await summarize(copy.deepcopy(old), prompt)
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("compaction completed without a summary")
            retained_user: list[dict[str, Any]] = []
            if latest_user is not None and latest_user < cut:
                remaining_user_tokens = min(COMPACT_USER_MESSAGE_MAX_TOKENS, budget)
                for index in range(latest_user, -1, -1):
                    if messages[index].get("role") != "user":
                        continue
                    message_tokens = estimate_tokens([messages[index]])
                    if message_tokens > remaining_user_tokens:
                        break
                    retained_user.append(messages[index])
                    remaining_user_tokens -= message_tokens
                retained_user.reverse()
            replacement = [m for m in messages[:cut] if m.get("role") == "system"] + retained_user + [{
                "role": "user", "content": "[Conversation continuation summary]\n" + summary.strip() +
                "\n[Preserved task state]\n" + invariants,
            }] + messages[cut:]
            size = estimate_tokens(replacement) + prefix_tokens
            if size >= after or size > budget:
                raise ValueError("compaction summary did not fit the context budget")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.consecutive_failures += 1
            result.error = str(exc)
            return result
        self.consecutive_failures = 0
        return CompactionResult(replacement, "summary", before, size, budget)
