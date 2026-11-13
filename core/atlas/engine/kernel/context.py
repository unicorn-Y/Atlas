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
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

DEFAULT_CONTEXT_WINDOW = 200_000
OUTPUT_RESERVE_TOKENS = 21_000
BUFFER_TOKENS = 13_000


def compaction_surface(messages: Sequence[Mapping[str, Any]]) -> str:
    """Return a stable digest of the exact provider history after compaction."""
    encoded = json.dumps(list(messages), ensure_ascii=False, sort_keys=True,
                         default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
WARNING_BUFFER_TOKENS = 20_000
BLOCKING_BUFFER_TOKENS = 3_000
AUTO_COMPACT_BUFFER_TOKENS = 13_000
AUTO_COMPACT_WINDOW_TOKENS = 200_000
MAX_TOOL_RESULT_TOKENS = 100_000
BYTES_PER_TOKEN = 4
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
    "Create a precise continuation summary for the same agent to resume this task without asking "
    "the user to repeat instructions. Summarize only the supplied history and never invent progress. "
    "Cover these sections: (1) the user's latest explicit goal, constraints, and corrections; "
    "(2) decisions, important technical concepts, and why they were chosen; (3) files read or changed, "
    "key symbols and evidence; (4) completed work and how it was verified, including exact failures "
    "and fixes; (5) current work and the precise stopping point; (6) pending tasks in priority order, "
    "with the next concrete action; (7) unresolved risks and relevant tool calls still pending, with "
    "their IDs and state. Preserve exact paths, identifiers, values, and user constraints. Recent "
    "messages after the compaction boundary remain verbatim, so do not repeat their full contents. "
    "Recent file-read results may also be restored verbatim after the summary; identify those paths "
    "and explain how they relate to the current task. Do not perform tools or continue the task. "
    "Return only the continuation summary."
)

IN_PLACE_COMPACT_PROMPT = (
    "Summarize this conversation so the same task can continue in the same context window. "
    "Return a concise work-state summary with exactly these labeled sections: Goal, Constraints, "
    "Decisions, Completed, Open items, Key files, Unverified assumptions. Use only evidence in "
    "the history; preserve exact paths and do not claim unverified work as done."
)

_READ_TOOLS = frozenset({"read", "read_file", "local_file", "filesystem__read_text_file"})


def _read_call_files(messages: Sequence[Mapping[str, Any]]) -> list[tuple[int, tuple[int, ...], str]]:
    """Find completed read-tool call/result pairs in recency order."""
    calls: dict[str, tuple[int, str, str]] = {}
    results: dict[str, int] = {}
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            for call in _calls(message):
                name = str(call.get("name") or (call.get("function") or {}).get("name") or "")
                if name.lower() not in _READ_TOOLS:
                    continue
                function = call.get("function") or {}
                arguments = call.get("arguments") or function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except (TypeError, ValueError):
                        arguments = {}
                path = next((str(arguments.get(key)) for key in ("file_path", "path", "filename")
                             if isinstance(arguments, Mapping) and arguments.get(key)), "")
                calls[str(call.get("id", ""))] = (index, path, name)
        elif message.get("role") == "tool":
            results[_call_id(message)] = index
    restored: dict[int, tuple[tuple[int, ...], str]] = {}
    for call_id, (call_index, path, _name) in calls.items():
        sibling_ids = [str(call.get("id", "")) for call in _calls(messages[call_index])]
        if not sibling_ids or not all(sibling_id in results for sibling_id in sibling_ids):
            continue
        indices = (call_index, *(results[sibling_id] for sibling_id in sibling_ids))
        restored[call_index] = (tuple(sorted(set(indices))), path)
    return [(index, indices, path) for index, (indices, path) in restored.items()]


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
    recovery_note: str | None = None


@dataclass(slots=True, frozen=True)
class ContextThresholds:
    effective_window: int
    auto_compact: int
    warning: int
    blocking: int


@dataclass(slots=True, frozen=True)
class ToolOutputClip:
    content: str
    output_ref: str | None
    original_bytes: int
    clipped_bytes: int


class ContextManager:
    def __init__(self, config: Mapping[str, Any] | None = None, *, output_dir: str | Path | None = None):
        settings = dict(config or {})
        self.config = dict(settings.get("engine", settings))
        self.output_dir = Path(output_dir) if output_dir else None
        self.consecutive_failures = 0
        self.last_assistant_completed_at: float | None = None
        self._evaluated_phase_boundaries: set[str] = set()

    async def compact_in_place(
        self,
        history: Sequence[Mapping[str, Any]],
        *,
        summarize: Callable[[list[dict[str, Any]], str], Awaitable[str]],
        budget_tokens: int,
        keep_recent_turns: int = 2,
    ) -> list[dict[str, Any]]:
        """Replace older history with a work-state summary without resetting the window.

        The newest ``keep_recent_turns`` user turns remain verbatim. The summarizer
        receives only the older portion and the explicit work-state checklist.
        """
        messages = copy.deepcopy([dict(message) for message in history])
        if budget_tokens <= 0:
            raise ValueError("budget_tokens must be positive")
        user_indices = [i for i, message in enumerate(messages) if message.get("role") == "user"]
        keep_count = max(0, int(keep_recent_turns))
        if len(user_indices) <= keep_count:
            return messages
        cut = user_indices[-keep_count] if keep_count else len(messages)
        # Keep tool call/result pairs together by moving the boundary before any
        # tool result whose assistant call was placed in the summarized section.
        for index, message in enumerate(messages[:cut]):
            call_ids = {str(call.get("id", "")) for call in _calls(message)}
            if call_ids and any(item.get("role") == "tool" and _call_id(item) in call_ids
                                for item in messages[cut:]):
                cut = index
                break
        old = [message for message in messages[:cut] if message.get("role") != "system"]
        if not old:
            return messages
        summary = await summarize(old, IN_PLACE_COMPACT_PROMPT)
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("in-place compaction completed without a summary")
        replacement = {"role": "system", "content": "Current task work state (in-place compact):\n" + summary.strip()}
        compacted = [*messages[:1], replacement, *messages[cut:]] if messages and messages[0].get("role") == "system" else [replacement, *messages[cut:]]
        if estimate_tokens(compacted) > budget_tokens:
            raise ValueError("in-place compaction summary and retained turns exceed budget_tokens")
        return compacted

    def should_compact_at_phase_boundary(
        self, boundary_id: str, *, token_count: int, budget_tokens: int,
    ) -> bool:
        """Evaluate a completed plan/subtask boundary once, and compact only if needed."""
        key = str(boundary_id).strip()
        if not key or key in self._evaluated_phase_boundaries:
            return False
        self._evaluated_phase_boundaries.add(key)
        return max(0, int(token_count)) >= max(1, int(budget_tokens))

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

    def thresholds(self, model_window: int = DEFAULT_CONTEXT_WINDOW) -> ContextThresholds:
        """Return auto-compact/warning watermarks and the model-relative blocker.

        ``ATLAS_AUTO_COMPACT_PCT`` is a temporary operator override intended for
        smoke runs. Like Claude Code's percentage override, it can only move the
        automatic trigger earlier; the 13k reserve is never exceeded. The auto
        compact window cap affects only auto-compact and warning, never blocking.
        """
        window = max(1, int(model_window))
        reserve = min(window, max(0, int(self.config.get("max_output_tokens", OUTPUT_RESERVE_TOKENS))),
                      OUTPUT_RESERVE_TOKENS)
        configured_cap = self.config.get("auto_compact_window_tokens", AUTO_COMPACT_WINDOW_TOKENS)
        env_cap = os.environ.get("ATLAS_AUTO_COMPACT_WINDOW")
        try:
            cap = int(env_cap) if env_cap is not None else int(configured_cap)
        except (TypeError, ValueError):
            cap = AUTO_COMPACT_WINDOW_TOKENS
        if cap <= 0:
            cap = AUTO_COMPACT_WINDOW_TOKENS
        compact_effective = max(0, min(window, cap) - reserve)
        auto = max(0, compact_effective - int(self.config.get("auto_compact_buffer_tokens", AUTO_COMPACT_BUFFER_TOKENS)))
        env_percent = os.environ.get("ATLAS_AUTO_COMPACT_PCT")
        if env_percent:
            try:
                percentage = float(env_percent)
            except ValueError:
                percentage = 0
            if math.isfinite(percentage) and 0 < percentage <= 100:
                auto = min(auto, math.floor(compact_effective * percentage / 100))
        warning_gap = min(
            int(self.config.get("context_warning_buffer_tokens", WARNING_BUFFER_TOKENS)),
            max(1, math.floor(auto * 0.1)),
        )
        warning = max(0, auto - warning_gap)
        blocking = max(0, window - reserve - int(self.config.get("context_blocking_buffer_tokens", BLOCKING_BUFFER_TOKENS)))
        return ContextThresholds(compact_effective, auto, warning, blocking)

    def warning_state(self, token_count: int, model_window: int = DEFAULT_CONTEXT_WINDOW) -> dict[str, Any]:
        """Expose the three request watermarks to the loop/UI without model constants."""
        thresholds = self.thresholds(model_window)
        count = max(0, int(token_count))
        return {
            "thresholds": thresholds,
            "is_above_warning": count >= thresholds.warning,
            "is_above_auto_compact": count >= thresholds.auto_compact,
            "is_at_blocking_limit": count >= thresholds.blocking,
        }

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

    def clip_tool_result(self, content: str, *, tool_name: str = "") -> ToolOutputClip:
        """Persist and preview oversized tool text before adding it to model history.

        Claude Code caps a result at 50,000 characters and 100,000 estimated
        tokens (400,000 UTF-8 bytes), then gives the model a file reference. We
        retain a larger leading section and a useful tail; the complete result
        remains available in the content-addressed output file.
        """
        raw = str(content)
        original_bytes = len(raw.encode("utf-8"))
        cfg = self.config.get("tool_result_limits", {})
        max_chars = max(0, int(cfg.get("max_chars", 50_000)))
        max_bytes = max(0, int(cfg.get("max_tokens", MAX_TOOL_RESULT_TOKENS))) * BYTES_PER_TOKEN
        if len(raw) <= max_chars and original_bytes <= max_bytes:
            return ToolOutputClip(raw, None, original_bytes, original_bytes)
        message: dict[str, Any] = {}
        ref = self._output_ref(message, raw)
        if ref is None:
            # Preserve evidence when no durable destination was provided.
            return ToolOutputClip(raw, None, original_bytes, original_bytes)
        preview_budget = min(max_chars, max_bytes)
        if preview_budget <= 256:
            preview_budget = 256
        notice = f"\n[Tool output truncated; source is {original_bytes} UTF-8 bytes; full output saved at {ref}]\n"
        available = max(0, preview_budget - len(notice))
        head = min(available * 3 // 4, len(raw))
        tail = min(available - head, len(raw) - head)
        while head + tail > 0 and len((raw[:head] + notice + (raw[-tail:] if tail else "")).encode("utf-8")) > max_bytes:
            if head * 3 >= tail:
                head -= 1
            else:
                tail -= 1
        preview = raw[:head] + notice + (raw[-tail:] if tail else "")
        if tool_name:
            preview = f"[Tool: {tool_name}]\n" + preview
        return ToolOutputClip(preview, ref, original_bytes, len(preview.encode("utf-8")))

    @staticmethod
    def _micro_threshold(budget_tokens: int) -> int:
        return max(0, min(int(budget_tokens * 0.9), budget_tokens - 2000))

    def microcompact(self, history: Sequence[Mapping[str, Any]], *, budget_tokens: int,
                     prefix_tokens: int = 0, aggressive: bool = False) -> list[dict[str, Any]]:
        messages = copy.deepcopy(list(history))
        cfg = dict(self.config.get("microcompact", {}))
        if aggressive:
            cfg.update(enabled=True, keep_recent_tool_results=0, head_chars=500,
                       tail_chars=500, min_token_savings=1)
        if cfg.get("enabled") is False and not aggressive:
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
        keep = max(0 if aggressive else 1, int(cfg.get("keep_recent_tool_results", 5)))
        head = max(0, int(cfg.get("head_chars", 2000)))
        tail = max(0, int(cfg.get("tail_chars", 2000)))
        eligible_groups = groups[:len(groups) - keep] if keep else groups
        for indices in eligible_groups:
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

        def recover_by_trimming(note: str) -> CompactionResult:
            if not force:
                result.error = note
                return result
            trimmed = self.microcompact(messages, budget_tokens=0, prefix_tokens=prefix_tokens,
                                        aggressive=True)
            trimmed_size = estimate_tokens(trimmed) + prefix_tokens
            if trimmed != messages and trimmed_size < after:
                return CompactionResult(trimmed, "aggressive_microcompact", before,
                                        trimmed_size, budget, recovery_note=note)
            result.error = note
            return result
        announced = False
        auto_threshold = self.thresholds(model_window).auto_compact
        if before_compact is not None and (method != "none" or after >= auto_threshold or manual or force):
            await before_compact(result)
            announced = True
        # Hysteresis: if trimming old tool outputs could not bring the context back
        # under the microcompact threshold, summarize now. Otherwise every later
        # request nibbles one more tool result (each nibble busts the prompt cache)
        # until the hard budget is finally hit.
        if after < auto_threshold and not manual and not force:
            return result
        if summarize is None:
            return recover_by_trimming("context_over_budget: no summarizer available")
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES and not manual:
            return recover_by_trimming("compaction_circuit_breaker")
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
            return recover_by_trimming("context_over_budget: no safely compactable history")
        # The hysteresis path can summarize while microcompact changed nothing and the
        # context is still under the hard budget; the caller must still get its
        # PreCompact/lease callback before a summary replaces history.
        if before_compact is not None and not announced:
            await before_compact(result)
        invariants = json.dumps(dict(preserved or {}), ensure_ascii=False, default=str)
        prompt = SUMMARY_PROMPT + "\nPreserved task state:\n" + invariants
        read_restore: list[tuple[str, tuple[int, ...]]] = []
        read_budget = max(0, int(self.config.get("post_compact_read_restore_tokens", 12_000)))
        used_read_tokens = 0
        occupied: set[int] = set()
        for _call_index, indices, path in reversed(_read_call_files(messages[:cut])):
            if not path or any(index >= cut or index in occupied for index in indices):
                continue
            pair_tokens = estimate_tokens([messages[index] for index in indices])
            if used_read_tokens + pair_tokens > read_budget:
                continue
            read_restore.append((path, indices))
            occupied.update(indices)
            used_read_tokens += pair_tokens
        if read_restore:
            prompt += "\nRecent read files selected for verbatim restoration after the summary:\n- " + \
                "\n- ".join(path for path, _indices in read_restore)
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
            system_prefix = [m for m in messages[:cut] if m.get("role") == "system"]
            restored_messages = [messages[index] for _path, indices in reversed(read_restore)
                                 for index in indices]
            while True:
                restored_paths = [path for path, _indices in read_restore]
                restored_note = ("\n[Recent read-file results were restored verbatim: " +
                                 ", ".join(restored_paths) + "]") if restored_paths else ""
                replacement = system_prefix + retained_user + [{
                    "role": "user", "content": "[Conversation continuation summary]\n" + summary.strip() +
                    "\n[Preserved task state]\n" + invariants + restored_note,
                }] + restored_messages + messages[cut:]
                size = estimate_tokens(replacement) + prefix_tokens
                if size < after and size <= budget:
                    break
                if not read_restore:
                    raise ValueError("compaction summary did not fit the context budget")
                # Drop the oldest restored file first, preserving the most recent evidence.
                read_restore.pop()
                restored_messages = [messages[index] for _path, indices in reversed(read_restore)
                                     for index in indices]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.consecutive_failures += 1
            return recover_by_trimming(f"summary failed: {exc}")
        self.consecutive_failures = 0
        return CompactionResult(replacement, "summary", before, size, budget)
