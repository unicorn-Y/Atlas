"""SessionDB compaction markers and transcript projections.

This module owns only the durable transcript contract. Summary generation is an Atlas engine operation
and deliberately does not live here.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

HISTORICAL_TASK_HEADING = "## Historical Task Snapshot"
SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. This is a handoff from a previous context "
    "window — treat it as background reference, NOT as active instructions. "
    "Do NOT answer questions or fulfill requests mentioned in this summary; "
    "they were already addressed. Respond ONLY to the latest user message "
    "that appears AFTER this summary — that message is the single source of "
    "truth for what to do right now. "
    "If no user message appears AFTER this summary, do nothing: do not "
    "resume, wrap up, or continue work from "
    f"'{HISTORICAL_TASK_HEADING}' or any other section, do not call tools, "
    "and wait for a new user message. This handoff must never become the "
    "active turn by itself. (Exception: if tool results or your own "
    "tool calls appear after this summary, you are mid-way through an "
    "in-flight exchange — continue that exchange normally.) "
    "Topic overlap with the summary does NOT mean you should resume its "
    "task: even on similar topics, the latest user message WINS. Treat ONLY "
    "the latest message as the active task and discard stale items from "
    f"'{HISTORICAL_TASK_HEADING}' entirely — do not 'wrap up' or "
    "'finish' work described there unless the latest user message explicitly "
    "asks for it. Reverse signals in the latest message (e.g. 'stop', 'undo', "
    "'roll back', 'just verify', 'don't do that anymore', 'never mind', a "
    "new topic) must immediately end any in-flight work described in the "
    "summary; do not re-surface it in later turns. IMPORTANT: Your persistent "
    "memory (MEMORY.md, USER.md) in the system prompt is ALWAYS authoritative "
    "and active — never ignore or deprioritize memory content due to this "
    "compaction note. None of the above restricts HOW you work: your tools "
    "remain fully active — keep calling them normally for the active task "
    "(edit files, run commands, search) instead of merely narrating what you "
    "would do. The current session state (files, config, etc.) may reflect "
    "work described here — avoid repeating it:"
)
LEGACY_SUMMARY_PREFIX = "[CONTEXT SUMMARY]:"
_SUMMARY_END_MARKER = "--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---"
_MERGED_PRIOR_CONTEXT_HEADER = "[PRIOR CONTEXT — for reference only; not a new message]"
_MERGED_SUMMARY_DELIMITER = "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]"
COMPRESSED_SUMMARY_METADATA_KEY = "_compressed_summary"
COMPRESSED_SUMMARY_HAS_USER_TURN_KEY = "_compressed_summary_has_user_turn"
MICRO_COMPACT_MARKER_KEY = "_micro_compact_marker"
MODEL_ONLY_DISPLAY_METADATA_KEY = "model_only"
_DB_PERSISTED_MARKER = "_db_persisted"
STEER_DISPLAY_KIND = "steer"
SUMMARY_CARRIER_DURABLE_DISPLAY_METADATA_KEYS = ("reactions",)


def stamp_db_persisted_markers(messages: list[dict[str, Any]]) -> None:
    for message in messages:
        if isinstance(message, dict):
            message[_DB_PERSISTED_MARKER] = True


def _is_checkpoint_item(item: Any) -> bool:
    return isinstance(item, dict) and item.get("type") == "compaction"


def _newest_checkpoint_carrier(messages: list[dict[str, Any]], key: str) -> int:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        items = message.get(key) if isinstance(message, dict) and message.get("role") == "assistant" else None
        if isinstance(items, list) and any(_is_checkpoint_item(item) for item in items):
            return index
    return -1


def _part_text(item: Any) -> Optional[str]:
    return item if isinstance(item, str) else item.get("text") if isinstance(item, dict) else None


def _with_part_text(item: Any, text: str) -> Any:
    return {**item, "text": text} if isinstance(item, dict) else text


def _content_text(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(text for part in content if (text := _part_text(part)))
    return content if isinstance(content, str) else "" if content is None else str(content)


def drop_stale_api_content(message: dict[str, Any]) -> None:
    message.pop("api_content", None)


class ContextCompressor:
    """Compatibility facade for state readers; performs no compression or model calls."""

    @classmethod
    def classify_summary_content(cls, content: Any) -> Optional[str]:
        text = _content_text(content).lstrip()
        if _MERGED_SUMMARY_DELIMITER in text:
            suffix = text.split(_MERGED_SUMMARY_DELIMITER, 1)[1].lstrip()
            return "merged" if cls._starts_with_summary_prefix(suffix) else None
        return "standalone" if cls._starts_with_summary_prefix(text) else None

    @staticmethod
    def _starts_with_summary_prefix(text: str) -> bool:
        return text.startswith((SUMMARY_PREFIX, LEGACY_SUMMARY_PREFIX, "[CONTEXT COMPACTION — REFERENCE ONLY]"))

    @classmethod
    def _is_context_summary_content(cls, content: Any) -> bool:
        return cls.classify_summary_content(content) is not None

    @classmethod
    def _is_context_summary_message(cls, message: Any) -> bool:
        return isinstance(message, dict) and (
            bool(message.get(COMPRESSED_SUMMARY_METADATA_KEY))
            or cls._is_context_summary_content(message.get("content"))
        )

    @classmethod
    def _strip_context_summary_handoff_message(cls, message: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not cls._is_context_summary_message(message):
            return message.copy()
        content = message.get("content")
        if isinstance(content, str):
            if _MERGED_SUMMARY_DELIMITER in content:
                prior = content.split(_MERGED_SUMMARY_DELIMITER, 1)[0].strip()
                if prior.startswith(_MERGED_PRIOR_CONTEXT_HEADER):
                    prior = prior[len(_MERGED_PRIOR_CONTEXT_HEADER):].lstrip()
            elif _SUMMARY_END_MARKER in content:
                prior = content.split(_SUMMARY_END_MARKER, 1)[1].lstrip()
            else:
                prior = ""
            if not prior:
                return None
            result = {**message, "content": prior}
        elif isinstance(content, list):
            prior_parts: list[Any] = []
            for part in content:
                text = _part_text(part)
                if isinstance(text, str) and _MERGED_SUMMARY_DELIMITER in text:
                    prefix = text.split(_MERGED_SUMMARY_DELIMITER, 1)[0]
                    if prefix.strip():
                        prior_parts.append(_with_part_text(part, prefix))
                    break
                prior_parts.append(part.copy() if isinstance(part, dict) else part)
            if not prior_parts:
                return None
            result = {**message, "content": prior_parts}
        else:
            return None
        result.pop(COMPRESSED_SUMMARY_METADATA_KEY, None)
        return result

    @classmethod
    def _is_real_user_turn(cls, message: dict[str, Any]) -> bool:
        return (
            isinstance(message, dict) and message.get("role") == "user"
            and message.get("display_kind") in (None, STEER_DISPLAY_KIND)
            and not cls._is_context_summary_message(message)
            and bool(_content_text(message.get("content")).strip())
        )


def is_compaction_summary_message(message: Any) -> bool:
    return ContextCompressor._is_context_summary_message(message)


def _is_checkpoint_item(item: Any) -> bool:
    return isinstance(item, dict) and item.get("type") == "compaction"


def _newest_checkpoint_carrier(messages: list[dict[str, Any]], key: str) -> int:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        items = message.get(key) if isinstance(message, dict) and message.get("role") == "assistant" else None
        if isinstance(items, list) and any(_is_checkpoint_item(item) for item in items):
            return index
    return -1


def _handoff_only_content(content: Any) -> Any:
    if isinstance(content, str):
        if _MERGED_SUMMARY_DELIMITER in content:
            content = content.split(_MERGED_SUMMARY_DELIMITER, 1)[1].lstrip()
        end = content.find(_SUMMARY_END_MARKER)
        return content[:end + len(_SUMMARY_END_MARKER)] if end >= 0 else content
    if not isinstance(content, list):
        return content
    result: list[Any] = []
    for part in content:
        text = _part_text(part)
        if isinstance(text, str) and _MERGED_SUMMARY_DELIMITER in text:
            suffix = text.split(_MERGED_SUMMARY_DELIMITER, 1)[1].lstrip()
            end = suffix.find(_SUMMARY_END_MARKER)
            suffix = suffix[:end + len(_SUMMARY_END_MARKER)] if end >= 0 else suffix
            if suffix:
                result.append(_with_part_text(part, suffix))
            break
        if isinstance(text, str) and _SUMMARY_END_MARKER in text:
            result.append(_with_part_text(part, text[:text.index(_SUMMARY_END_MARKER) + len(_SUMMARY_END_MARKER)]))
            break
        result.append(part.copy() if isinstance(part, dict) else part)
    return result


def split_user_originated_turn(message: Any) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    if not isinstance(message, dict) or message.get("role") != "user":
        return None, None
    summary = is_compaction_summary_message(message)
    handoff = None
    if summary:
        handoff = {
            "role": "user", "content": _handoff_only_content(message.get("content")),
            COMPRESSED_SUMMARY_METADATA_KEY: True, "display_kind": "hidden",
        }
        for key in (COMPRESSED_SUMMARY_HAS_USER_TURN_KEY, MICRO_COMPACT_MARKER_KEY, "timestamp"):
            if key in message:
                handoff[key] = message[key]
        live = ContextCompressor._strip_context_summary_handoff_message(message)
        if live is None:
            return handoff, None
    elif message.get("display_kind") not in (None, STEER_DISPLAY_KIND):
        return None, None
    else:
        live = message.copy()
    for key in (COMPRESSED_SUMMARY_METADATA_KEY, COMPRESSED_SUMMARY_HAS_USER_TURN_KEY,
                MICRO_COMPACT_MARKER_KEY, _DB_PERSISTED_MARKER, "_row_id", "display_kind", "display_metadata"):
        live.pop(key, None)
    metadata = message.get("display_metadata")
    if isinstance(metadata, dict):
        durable = {key: deepcopy(metadata[key]) for key in SUMMARY_CARRIER_DURABLE_DISPLAY_METADATA_KEYS if key in metadata}
        if durable:
            live["display_metadata"] = durable
    drop_stale_api_content(live)
    if not ContextCompressor._is_real_user_turn(live):
        return handoff, None
    return handoff, live


def user_originated_turn_view(message: Any) -> Optional[dict[str, Any]]:
    return split_user_originated_turn(message)[1]


def history_before_user_originated_turn(messages: list[dict[str, Any]], index: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if index < 0 or index >= len(messages):
        raise IndexError("user turn index is outside the transcript")
    handoff, live = split_user_originated_turn(messages[index])
    if live is None:
        raise ValueError("selected row is not a user-originated turn")
    return [message.copy() for message in messages[:index]] + ([handoff] if handoff is not None else []), live


def retryable_user_text(content: Any) -> str:
    if not isinstance(content, (str, list)):
        raise ValueError("retry does not support non-text content")
    chunks: list[str] = []
    for part in [content] if isinstance(content, str) else content:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict) and part.get("type") in {"text", "input_text", "output_text"} and set(part) <= {"type", "text"} and isinstance(part.get("text"), str):
            chunks.append(part["text"])
        else:
            raise ValueError("retry does not support media or unknown content parts")
    text = "".join(chunks)
    if not text.strip():
        raise ValueError("retry found no text to send")
    return text


