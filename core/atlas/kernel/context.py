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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

DEFAULT_CONTEXT_WINDOW = 200_000
OUTPUT_RESERVE_TOKENS = 21_000
BUFFER_TOKENS = 13_000
MAX_CONSECUTIVE_FAILURES = 3
COMPACT_USER_MESSAGE_MAX_TOKENS = 20_000
PRUNE_PROTECT_TOKENS = 40_000
PRUNE_MINIMUM_TOKENS = 20_000
KEEP_RECENT_TOKENS = 20_000
TOOL_SERIALIZE_MAX_CHARS = 2_000
SUMMARY_PROMPT = (
    "Write a continuation handoff for the next model. This is reference material; the latest user "
    "message is authoritative, and completed requests must not be repeated. Use the conversation's "
    "language. Include these exact sections: Goal; Constraints and preferences; Progress (completed, "
    "in progress, blocked); Key decisions; Next steps; Key context; User's exact words. Preserve all "
    "paths, commit hashes, session IDs, test names, ports, pending tool calls and their IDs. Do not "
    "invent progress, perform tools, or continue the task. End with a recovery note saying the full "
    "record remains available through session_search. Return only the handoff."
)
SUMMARY_PROMPT_ZH = (
    "请为下一个模型写一份可继续执行任务的交接摘要。这是参考资料；以最新一条用户消息为准，已完成的请求不要重做。"
    "请使用对话语言，并包含以下小节：目标；约束与偏好；进度（已完成、进行中、受阻）；关键决定；下一步；"
    "关键上下文；用户原话。逐字保留被压缩区间内用户的每条原话，以及所有路径、提交哈希、会话 ID、测试名、端口、"
    "待处理工具调用及其 ID。不要编造进度、调用工具或继续执行任务。结尾说明完整记录仍保留，可用 session_search 查原文。"
    "只返回交接摘要。"
)

_SUMMARY_SECTIONS_EN = ("Goal", "Constraints and preferences", "Progress", "Key decisions",
                        "Next steps", "Key context", "User's exact words")
_SUMMARY_SECTIONS_ZH = ("目标", "约束与偏好", "进度", "关键决定", "下一步", "关键上下文", "用户原话")
_IDENTIFIER_RE = re.compile(
    r"(?<![\w])(?:[A-Za-z]:[\\/][^\s\]\[()<>\"']+|(?:\.\.?[\\/])?"
    r"[\w.-]+(?:[\\/][\w .@+-]+)*\.[A-Za-z0-9]{1,8}|"
    r"[0-9a-f]{7,40}|(?:session|conversation)[_-]?[A-Za-z0-9-]{6,}|"
    r"(?:test_[A-Za-z0-9_]+)|(?:localhost:)?\d{2,5})(?![\w])", re.I)


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
    pruned_results: int = 0
    deduped: int = 0
    restored_files: list[str] = field(default_factory=list)
    guard_missing: list[str] = field(default_factory=list)
    ineffective_streak: int = 0
    summary_model: str | None = None
    invalidated_read_tool_call_ids: list[str] = field(default_factory=list)
    read_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)


class ContextManager:
    def __init__(self, config: Mapping[str, Any] | None = None, *, output_dir: str | Path | None = None):
        settings = dict(config or {})
        self.config = dict(settings.get("engine", settings))
        self.output_dir = Path(output_dir) if output_dir else None
        self.consecutive_failures = 0
        self.ineffective_streak = 0
        self.provider_input_tokens: int | None = None
        self.summary_fallback: Callable[[list[dict[str, Any]], str], Awaitable[str]] | None = None
        self.read_files: set[str] = set()
        self.modified_files: set[str] = set()
        self.modified_file_order: list[str] = []

    def set_provider_usage(self, input_tokens: int | None) -> None:
        """Supply the latest provider-reported input count before the next prepare()."""
        self.provider_input_tokens = max(0, int(input_tokens)) if input_tokens is not None else None

    def set_summary_fallback(
        self, summarize: Callable[[list[dict[str, Any]], str], Awaitable[str]] | None,
    ) -> None:
        """Set the primary-model fallback used if the configured summary route fails."""
        self.summary_fallback = summarize

    def _remember_files(self, read_files: Sequence[str], modified_files: Sequence[str]) -> None:
        self.read_files.update(read_files)
        for path in modified_files:
            if path in self.modified_file_order:
                self.modified_file_order.remove(path)
            self.modified_file_order.append(path)
        self.modified_files.update(modified_files)

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
        return max(0, min(int(budget_tokens * 0.55), budget_tokens - 2000))

    @staticmethod
    def _tool_index(messages: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, dict[str, Any]]]:
        calls: dict[str, tuple[str, dict[str, Any]]] = {}
        for message in messages:
            if message.get("role") != "assistant":
                continue
            for call in _calls(message):
                fn = call.get("function") or {}
                name = str(call.get("name") or fn.get("name") or "")
                args = call.get("arguments", fn.get("arguments", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (TypeError, ValueError):
                        args = {"command": args}
                calls[str(call.get("id", ""))] = (name, args if isinstance(args, dict) else {})
        return calls

    @staticmethod
    def _file_ops(messages: Sequence[Mapping[str, Any]],
                  tool_call_ids: set[str] | None = None) -> tuple[set[str], set[str]]:
        read: set[str] = set()
        modified: set[str] = set()
        for call_id, (name, arguments) in ContextManager._tool_index(messages).items():
            if tool_call_ids is not None and call_id not in tool_call_ids:
                continue
            path = arguments.get("path") or arguments.get("file_path") or arguments.get("file")
            if not isinstance(path, str) or not path.strip():
                continue
            normalized_name = name.lower()
            operation = str(arguments.get("operation") or arguments.get("action") or "").lower()
            if normalized_name in {"write_file", "edit", "patch", "apply_patch", "local_edit", "local_edit_batch"} or any(
                    marker in operation for marker in ("write", "edit", "patch")):
                modified.add(path)
            elif normalized_name in {"read_file", "local_file", "filesystem__read_text_file", "read_text_file"} or "read" in operation:
                read.add(path)
        return read, modified

    def _tool_summary(self, message: Mapping[str, Any], name: str,
                      arguments: Mapping[str, Any], ref: str) -> str:
        # Mirrors the per-tool summarizers in Hermes context_compressor.py:1683-1717,1964-1972.
        fields: list[str] = [f"{name or 'tool'} output shortened; full output: {ref}"]
        command = arguments.get("command") or arguments.get("cmd") or arguments.get("script")
        normalized_name = name.lower()
        if command and normalized_name in {"terminal", "local_shell", "local_exec", "powershell", "execute_code"}:
            command_text = str(command).strip()
            fields.append(f"command={command_text if len(command_text) <= 500 else command_text[:497] + '...'}")
        payload: dict[str, Any] = {}
        try:
            decoded = json.loads(str(message.get("content") or ""))
            if isinstance(decoded, dict):
                payload = decoded
        except (TypeError, ValueError):
            pass
        exit_code = message.get(
            "exit_code", message.get("exitCode", message.get("returncode", payload.get("exit_code"))),
        )
        if exit_code is None:
            match = re.search(r"(?i)(?:exit(?:ed)?(?: with)?(?: code)?|exit_code)\s*[=:]?\s*(-?\d+)",
                              str(message.get("content") or ""))
            exit_code = match.group(1) if match else None
        if exit_code is not None:
            fields.append(f"exit_code={exit_code}")
        path = arguments.get("path") or arguments.get("file_path") or message.get("path")
        if path is None and isinstance(arguments.get("paths"), list):
            path = ",".join(str(item) for item in arguments["paths"])
        if path:
            fields.append(f"path={path}")
        content = str(message.get("content") or "")
        line_count = int(message.get("line_count") or len(content.splitlines()))
        if line_count:
            fields.append(f"lines={line_count}")
        for label, pattern in (("lines", r"(?im)^\s*(\d+)\s+lines?\b"),
                               ("matches", r"(?im)^\s*(\d+)\s+(?:matches|hits)\b")):
            match = re.search(pattern, content)
            if match:
                value = f"{label}={match.group(1)}"
                if value not in fields:
                    fields.append(value)
        if normalized_name in {"search_files", "grep", "rg", "web_search"}:
            hits = payload.get("total_count", payload.get("match_count", payload.get("hits")))
            if hits is None:
                match = re.search(r"(?i)(\d+)\s+(?:matches|hits)\b", content)
                hits = match.group(1) if match else None
            if hits is not None:
                fields.append(f"matches={hits}")
        return "[" + "; ".join(fields) + "]"

    def _prune_and_dedupe(self, history: Sequence[Mapping[str, Any]], *, budget_tokens: int,
                          context_tokens: int) -> tuple[list[dict[str, Any]], int, int, list[str]]:
        original = copy.deepcopy(list(history))
        cfg = self.config.get("prune", {})
        if cfg.get("enabled") is False or context_tokens <= int(budget_tokens * float(cfg.get("trigger_ratio", .55))):
            return original, 0, 0, []
        messages = copy.deepcopy(original)
        calls = self._tool_index(messages)
        protected = {str(name).lower() for name in cfg.get("protected_tools", ["skill", "use_skill"])}
        eligible: list[int] = []
        recent = 0
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if message.get("role") != "tool" or not isinstance(message.get("content"), str):
                continue
            if message.get("microcompacted") or message.get("output_ref"):
                continue
            name, _ = calls.get(_call_id(message), (str(message.get("name") or ""), {}))
            if name.lower() in protected or message.get("_multimodal") or message.get("is_error") or message.get("isError"):
                continue
            size = estimate_tokens([message])
            if recent >= int(cfg.get("protect_tokens", PRUNE_PROTECT_TOKENS)):
                eligible.append(index)
            recent += size

        seen: dict[str, int] = {}
        duplicates: list[tuple[int, int]] = []
        for index, message in enumerate(messages):
            if message.get("role") != "tool" or not isinstance(message.get("content"), str):
                continue
            content = message["content"]
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest in seen and content == messages[seen[digest]].get("content"):
                duplicates.append((index, seen[digest]))
            else:
                seen[digest] = index

        prunable = set(eligible)
        recoverable = sum(estimate_tokens([messages[i]]) for i in prunable)
        if recoverable < int(cfg.get("minimum_tokens", PRUNE_MINIMUM_TOKENS)):
            prunable.clear()
        deduped = 0
        invalidated_ids: set[str] = set()
        for index, source_index in duplicates:
            if index not in eligible:
                continue
            message = messages[index]
            source = messages[source_index]
            name, arguments = calls.get(_call_id(message), (str(message.get("name") or ""), {}))
            ref = source.get("output_ref") or self._output_ref(source, str(source.get("content") or ""))
            if not ref:
                continue
            message["content"] = f"[Duplicate tool result; see {ref}]"
            message["output_ref"] = ref
            message["deduped"] = True
            deduped += 1
            if _call_id(message):
                invalidated_ids.add(_call_id(message))
        pruned = 0
        for index in sorted(prunable):
            message = messages[index]
            content = message["content"]
            name, arguments = calls.get(_call_id(message), (str(message.get("name") or ""), {}))
            ref = self._output_ref(message, content)
            if not ref:
                continue
            message["content"] = self._tool_summary(message, name, arguments, ref)
            message["output_ref"] = ref
            message["microcompacted"] = True
            pruned += 1
            if _call_id(message):
                invalidated_ids.add(_call_id(message))
        if pruned == 0 and deduped == 0:
            return original, 0, 0, []
        return messages, pruned, deduped, sorted(invalidated_ids)

    def _serialize(self, messages: Sequence[Mapping[str, Any]]) -> str:
        rows: list[str] = []
        for message in messages:
            role = str(message.get("role") or "")
            if role == "system":
                continue
            label = {"user": "User", "assistant": "Assistant", "tool": "Tool result"}.get(role, role.title())
            content = message.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, Mapping))
            content = str(content)
            if role == "tool":
                content = content[:int(self.config.get("tool_serialize_max_chars", TOOL_SERIALIZE_MAX_CHARS))]
            content = re.sub(r"(?is)<(?:thinking|analysis)>.*?</(?:thinking|analysis)>", "", content)
            if role == "assistant" and _calls(message):
                call_notes = []
                for call in _calls(message):
                    fn = call.get("function") or {}
                    name = call.get("name") or fn.get("name") or "tool"
                    arguments = call.get("arguments", fn.get("arguments", {}))
                    call_notes.append(f"{name}({arguments})")
                content = (content + "\n[Tool calls: " + "; ".join(call_notes) + "]").strip()
            rows.append(f"[{label}]: {content}")
        return "\n\n".join(rows)

    def _language(self, messages: Sequence[Mapping[str, Any]]) -> str:
        text = self._serialize(messages)
        chinese = len(re.findall(r"[\u3400-\u9fff]", text))
        latin = len(re.findall(r"[A-Za-z]", text))
        return "zh" if chinese > latin else "en"

    def _summary_missing(self, summary: str, old: Sequence[Mapping[str, Any]]) -> list[str]:
        sections = _SUMMARY_SECTIONS_ZH if self._language(old) == "zh" else _SUMMARY_SECTIONS_EN
        return [section for section in sections if section.lower() not in summary.lower()]

    @staticmethod
    def _missing_identifiers(summary: str, old: Sequence[Mapping[str, Any]]) -> list[str]:
        full_evidence = json.dumps(list(old), ensure_ascii=False, default=str)
        return [identifier for identifier in dict.fromkeys(_IDENTIFIER_RE.findall(full_evidence))
                if identifier not in summary]

    @staticmethod
    def _summary_quality_errors(summary: str) -> list[str]:
        errors: list[str] = []
        if "\ufffd" in summary or any("\ud800" <= char <= "\udfff" for char in summary):
            errors.append("invalid UTF-8 replacement character")
        if any((ord(char) < 32 and char not in "\n\r\t") or 127 <= ord(char) < 160 for char in summary):
            errors.append("control character")
        if re.search(r"(?:Ã[\x80-\xBF]|â€|ï¿½|锟斤拷)", summary):
            errors.append("mojibake")
        return errors

    def microcompact(self, history: Sequence[Mapping[str, Any]], *, budget_tokens: int,
                     prefix_tokens: int = 0) -> list[dict[str, Any]]:
        messages, _, _, _ = self._prune_and_dedupe(
            history, budget_tokens=budget_tokens, context_tokens=estimate_tokens(history) + prefix_tokens,
        )
        return messages

    async def prepare(self, history: Sequence[Mapping[str, Any]], *, model_window: int = DEFAULT_CONTEXT_WINDOW,
                      summarize: Callable[[list[dict[str, Any]], str], Awaitable[str]] | None = None,
                      preserved: Mapping[str, Any] | None = None, focus: str = "",
                      prefix_tokens: int = 0, manual: bool = False,
                      force: bool = False,
                      before_compact: Callable[[CompactionResult], Awaitable[None]] | None = None) -> CompactionResult:
        budget = self.budget(model_window)
        provider_input_tokens = self.provider_input_tokens
        self.provider_input_tokens = None
        before = (provider_input_tokens if provider_input_tokens is not None
                  else estimate_tokens(history)) + prefix_tokens
        messages, pruned_results, deduped, invalidated_ids = await asyncio.to_thread(
            self._prune_and_dedupe, history, budget_tokens=model_window, context_tokens=before,
        )
        after = estimate_tokens(messages) + prefix_tokens
        method = "prune" if messages != list(history) else "none"
        result = CompactionResult(
            messages, method, before, after, budget, pruned_results=pruned_results,
            deduped=deduped, invalidated_read_tool_call_ids=invalidated_ids,
            ineffective_streak=self.ineffective_streak,
            read_files=sorted(self.read_files), modified_files=list(self.modified_file_order),
        )
        if invalidated_ids:
            prune_reads, prune_modifications = self._file_ops(messages, set(invalidated_ids))
            self._remember_files(prune_reads, prune_modifications)
            result.read_files = sorted(self.read_files)
            result.modified_files = list(self.modified_file_order)
        if before_compact is not None and (method != "none" or after > budget or manual or force):
            await before_compact(result)
        prune_ratio = float(self.config.get("prune_trigger_ratio", .55))
        summary_ratio = float(self.config.get("summary_trigger_ratio", .70))
        if after <= int(model_window * summary_ratio) and after <= budget and not manual and not force:
            if after <= int(model_window * prune_ratio):
                self.ineffective_streak = 0
            return result
        if summarize is None:
            result.error = "context_over_budget: no summarizer available"
            return result
        if (self.ineffective_streak >= int(self.config.get("compaction_ineffective_limit", 2))
                or self.consecutive_failures >= int(self.config.get("max_compaction_failures", MAX_CONSECUTIVE_FAILURES))) and not manual:
            result.error = "compaction_circuit_breaker"
            result.ineffective_streak = self.ineffective_streak
            return result

        # Pi's cut point keeps a token-sized recent tail and lands only on a
        # user/assistant boundary, with complete tool call/result pairs intact.
        keep_recent = int(self.config.get("keep_recent_tokens", KEEP_RECENT_TOKENS))
        cut = len(messages)
        recent_tokens = 0
        for index in range(len(messages) - 1, -1, -1):
            recent_tokens += estimate_tokens([messages[index]])
            if recent_tokens >= keep_recent and messages[index].get("role") in {"user", "assistant"}:
                cut = index
                break
        pending: dict[str, int] = {}
        for index, message in enumerate(messages):
            for call in _calls(message):
                pending[str(call.get("id", ""))] = index
            if message.get("role") == "tool":
                pending.pop(_call_id(message), None)
        if pending:
            cut = min(cut, min(pending.values()))
        while cut > 0 and messages[cut].get("role") not in {"user", "assistant"}:
            cut -= 1
        while cut > 0:
            calls_before = {str(call.get("id", "")) for message in messages[:cut] for call in _calls(message)}
            if not any(message.get("role") == "tool" and _call_id(message) in calls_before
                       for message in messages[cut:]):
                break
            cut -= 1
        if cut < len(messages):
            crossing = messages[cut]
            content = crossing.get("content")
            if (crossing.get("role") in {"user", "assistant"} and isinstance(content, str)
                    and not _calls(crossing) and estimate_tokens([crossing]) > keep_recent):
                fraction = min(.95, max(.05, keep_recent / estimate_tokens([crossing])))
                split_at = max(1, min(len(content) - 1, int(len(content) * (1 - fraction))))
                original = content
                prefix = dict(crossing, content=content[:split_at])
                prefix["_compaction_split_turn"] = True
                if crossing.get("role") == "user":
                    prefix["_compaction_original_content"] = original
                messages[cut] = dict(crossing, content=content[split_at:])
                messages.insert(cut, prefix)
                cut += 1
        old = [m for m in messages[:cut] if m.get("role") != "system"]
        if not old:
            result.error = "context_over_budget: no safely compactable history"
            return result
        new_reads, new_modifications = self._file_ops(old)
        self._remember_files(new_reads, new_modifications)
        result.read_files = sorted(self.read_files)
        result.modified_files = list(self.modified_file_order)
        invariants = json.dumps(dict(preserved or {}), ensure_ascii=False, default=str)
        language = self._language(old)
        if language == "zh":
            language_instruction = ""
            summary_template = SUMMARY_PROMPT_ZH
        else:
            language_instruction = "\nUse English section headings as requested above."
            summary_template = SUMMARY_PROMPT
        prompt = summary_template + language_instruction + "\nPreserved task state:\n" + invariants
        if focus:
            prompt += "\nUser compaction focus: " + focus
        serialized = self._serialize(old)
        summary_input = [{"role": "user", "content": serialized}]
        split_index = next((index for index, message in enumerate(old)
                            if message.get("_compaction_split_turn")), None)
        summary_inputs = [summary_input]
        if split_index is not None and split_index > 0:
            summary_inputs = [
                [{"role": "user", "content": self._serialize(old[:split_index])}],
                [{"role": "user", "content": self._serialize(old[split_index:])}],
            ]
        exact_user_words = [str(message.get("_compaction_original_content", message.get("content", ""))) for message in old
                            if message.get("role") == "user" and str(message.get("content", "")).strip()]
        try:
            summary = ""
            missing: list[str] = []
            summary_error: Exception | None = None
            summary_model_used = str(self.config.get("summary_model") or "primary")
            routes = [summarize]
            if self.summary_fallback is not None and self.summary_fallback is not summarize:
                routes.append(self.summary_fallback)
            for route_index, route in enumerate(routes):
                for attempt in range(1 + max(0, int(self.config.get("summary_retry_count", 1)))):
                    attempt_prompt = prompt
                    if route_index:
                        attempt_prompt += "\nThe configured summary route failed; retry with the primary model."
                    if attempt and missing:
                        attempt_prompt += "\nRetry: restore every required heading and identifier exactly: " + ", ".join(missing)
                    try:
                        candidates = []
                        for part_index, part in enumerate(summary_inputs):
                            part_prompt = attempt_prompt
                            if len(summary_inputs) == 2:
                                part_prompt += ("\nSummarize prior history only." if part_index == 0 else
                                                "\nSummarize the split turn prefix; preserve its concrete details.")
                            candidates.append(await route(copy.deepcopy(part), part_prompt))
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        summary_error = exc
                        missing = [f"summary error: {type(exc).__name__}: {str(exc)[:200]}"]
                        continue
                    if any(not isinstance(candidate, str) or not candidate.strip() for candidate in candidates):
                        missing = ["non-empty summary"]
                        continue
                    summary = "\n\n--- Split turn context ---\n\n".join(candidate.strip() for candidate in candidates)
                    missing_quotes = [quote for quote in exact_user_words if quote not in summary]
                    if missing_quotes:
                        heading = "用户原话" if language == "zh" else "User's exact words"
                        user_block = "\n\n" + heading + ":\n" + "\n".join(f"> {line}" for quote in missing_quotes for line in quote.splitlines())
                        summary += user_block
                    missing_identifiers = self._missing_identifiers(summary, old)
                    if missing_identifiers:
                        heading = "关键上下文" if language == "zh" else "Key context"
                        summary += "\n\n" + heading + ":\n" + "\n".join(f"- {item}" for item in missing_identifiers)
                    missing = self._summary_missing(summary, old)
                    quality_errors = self._summary_quality_errors(summary)
                    if quality_errors:
                        missing.extend(quality_errors)
                    if not missing:
                        summary_error = None
                        break
                if not missing:
                    if route_index > 0:
                        summary_model_used = "primary"
                    break
            if missing:
                if summary_error is not None:
                    result.error = str(summary_error)
                else:
                    result.error = "compaction_guard_rejected: " + ", ".join(missing)
                result.guard_missing = missing
                result.method = method
                return result
            if "session_search" not in summary:
                footer = ("回查指引：完整记录仍然保留，可用 session_search 查找原文。"
                          if language == "zh" else
                          "Recovery: The full record remains available; use session_search to find the original messages.")
                summary += "\n\n" + footer
            replacement = [m for m in messages[:cut] if m.get("role") == "system"] + [{
                "role": "user", "content": "[Conversation continuation summary]\n" + summary +
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
        self.ineffective_streak = self.ineffective_streak + 1 if size > int(model_window * prune_ratio) else 0
        removed_ids = {_call_id(message) for message in messages[:cut] if message.get("role") == "tool" and _call_id(message)}
        result = CompactionResult(
            replacement, "summary", before, size, budget, pruned_results=pruned_results,
            deduped=deduped, invalidated_read_tool_call_ids=sorted(set(invalidated_ids) | removed_ids),
            guard_missing=[], ineffective_streak=self.ineffective_streak,
            summary_model=summary_model_used,
            read_files=sorted(self.read_files), modified_files=list(self.modified_file_order),
        )
        if self.ineffective_streak >= 2:
            result.error = "compaction_circuit_breaker"
        return result
