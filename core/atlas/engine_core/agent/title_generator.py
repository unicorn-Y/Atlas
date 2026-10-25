# ported from hermes-agent@c9e076b agent/title_generator.py (MIT)
"""Small, provider-neutral conversation title prompts and parsing."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import threading
import time
import weakref
from collections.abc import Callable
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)

MAX_TITLE_INPUT_CHARS = 1000
MAX_DERIVED_TITLE_CHARS = 48
TITLE_MAX_TOKENS = 128
_ATTACHMENT_REF_RE = re.compile(r"@(?:file|folder):\S+")
_CONTEXT_FOOTER_RE = re.compile(r"\n+--- (?:Context Warnings|Attached Context) ---\n.*", re.DOTALL)
_PASTE_PREVIEW_LABEL = "\n\nPasted content:\n"
_MACHINE_PREFIXES = (
    "[CONTEXT COMPACTION", "[CONTEXT SUMMARY]:", "[Runtime note:", "[System note:", "[SYSTEM]",
    "[System: The active model for this chat has changed to ",
)
_CONTROL_WRAPPERS = tuple(
    (f"<{tag}>", f"</{tag}>")
    for tag in (
        "command-message", "command-name", "command-args", "local-command-caveat",
        "local-command-stderr", "local-command-stdout", "task-notification", "system-reminder",
        "ide_opened_file", "ide_selection",
    )
)
_PROMPT = (
    "You name chat sessions. Given the user's opening message, write a title that lets them find "
    "this conversation again in a list.\n\nRules:\n"
    "- 3 to 7 words, sentence case (capitalize only the first word and proper nouns).\n"
    "- Name what the user wants DONE, not that they asked a question.\n"
    "- Keep technical terms, filenames, numbers, and error codes exact.\n"
    "- Drop filler words: the, this, my, a, an.\n"
    "- No trailing punctuation, no quotes, no tool names, no 'Title:' prefix.\n"
    "- Never answer the message. Name it.\n"
    "- Always produce something, even for a bare greeting.\n"
    "- Write in the same language as the user's message.\n"
    'Good: {"title": "Fix login button on mobile"}\n'
    'Good: {"title": "Postgres connection pool exhaustion"}\n'
    'Good: {"title": "Friendly greeting"}\n'
    'Reply with JSON only: {"title": "..."}'
)
_UPGRADE_THREADS: weakref.WeakSet[threading.Thread] = weakref.WeakSet()


def wait_for_title_upgrades(timeout: float = 10.0) -> None:
    """Join outstanding title workers up to a bounded timeout."""
    deadline = time.monotonic() + timeout
    for thread in list(_UPGRADE_THREADS):
        thread.join(max(0.0, deadline - time.monotonic()))


def strip_control_wrappers(text: str) -> str:
    value = text or ""
    for opening, closing in _CONTROL_WRAPPERS:
        value = re.sub(re.escape(opening) + r".*?" + re.escape(closing), "", value, flags=re.DOTALL)
    return value.strip()


def _attachment_only_opener(message: str) -> bool:
    return bool(re.match(r"^\s*(?:@(?:file|folder):\S+\s*)+$", message or ""))


def _summarize_user_message(user_message: str) -> str:
    message = strip_control_wrappers(user_message)
    return _CONTEXT_FOOTER_RE.sub("", message).strip()


def build_title_input(user_message: str, title_preview: str | None = None) -> str:
    message = _summarize_user_message(user_message)
    preview = title_preview.strip() if isinstance(title_preview, str) else ""
    if not preview:
        return message[:MAX_TITLE_INPUT_CHARS]
    message = _CONTEXT_FOOTER_RE.sub("", message).strip()
    if not _ATTACHMENT_REF_RE.sub("", message).strip():
        return preview[:MAX_TITLE_INPUT_CHARS]
    message_budget = min(len(message), MAX_TITLE_INPUT_CHARS // 2)
    preview_budget = MAX_TITLE_INPUT_CHARS - message_budget - len(_PASTE_PREVIEW_LABEL)
    if preview_budget <= 0:
        return message[:MAX_TITLE_INPUT_CHARS]
    return message[:message_budget] + _PASTE_PREVIEW_LABEL + preview[:preview_budget]


def is_titleable_user_message(user_message: str) -> bool:
    return (
        isinstance(user_message, str) and bool(user_message.strip())
        and not user_message.lstrip().startswith(_MACHINE_PREFIXES)
        and bool(_summarize_user_message(user_message).strip())
        and not _attachment_only_opener(user_message)
    )


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def derive_title(user_message: str, title_preview: str | None = None) -> str | None:
    if not title_preview and _attachment_only_opener(user_message):
        return None
    line = " ".join(_first_line(build_title_input(user_message, title_preview)).split())
    if len(line) > MAX_DERIVED_TITLE_CHARS:
        cut = line[:MAX_DERIVED_TITLE_CHARS]
        space = cut.rfind(" ")
        line = (cut[:space] if space > MAX_DERIVED_TITLE_CHARS // 2 else cut).rstrip(" ,.;:—-") + "…"
    return line or None


def _extract_json_title(raw: str) -> str | None:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("title"), str):
            return parsed["title"].strip()
    except (ValueError, TypeError):
        pass
    match = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if match:
        with suppress(ValueError):
            return json.loads(f'"{match.group(1)}"').strip()
        return match.group(1).strip()
    return None


def _extract_title_text(content: str) -> str:
    raw = (content or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    title = _extract_json_title(raw)
    if title is not None:
        return title
    if raw.startswith(('"{', '["', "[{")) or (raw.startswith("```") and raw.count("```") % 2):
        return ""
    if not raw:
        return ""
    return re.sub(r"^Title:\s*", "", _first_line(raw), flags=re.IGNORECASE).strip("\"'").strip()


def _clean_title(text: str) -> str | None:
    title = " ".join((text or "").split()).strip("\"'").rstrip(".!,;:")
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return title or None


def _title_config() -> dict[str, Any]:
    """Read the optional Atlas title settings without triggering migrations or setup probes."""
    from atlas.engine_core.config import cfg_get

    value = cfg_get("title_generation", default={})
    return value if isinstance(value, dict) else {}


def _auto_title_enabled() -> bool:
    return _title_config().get("enabled", True) is not False


def _model_title_upgrade_enabled() -> bool:
    # The deterministic title is available as soon as the user prompt arrives.
    # A second, non-user-facing provider call adds latency and competes with the
    # first response for a simple turn, so an LLM rewrite is explicitly opt-in.
    return _title_config().get("model_upgrade_enabled", False) is True


def generate_title(
    user_message: str,
    timeout: float | None = None,
    failure_callback: Callable[[str, BaseException], None] | None = None,
    main_runtime: dict[str, Any] | None = None,
    runtime_validator: Callable[[], bool] | None = None,
    title_preview: str | None = None,
    *,
    model_call: Callable[[str], Any] | None = None,
) -> str | None:
    """Generate a title with an injected Atlas model call; no provider probing or fallback client."""
    if not _auto_title_enabled() or not is_titleable_user_message(user_message):
        return None
    if model_call is None:
        return derive_title(user_message, title_preview)
    try:
        if runtime_validator is not None and not runtime_validator():
            return None
        prompt = _PROMPT + "\n\nUser message:\n" + build_title_input(user_message, title_preview)
        response = model_call(prompt)
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        if isinstance(response, dict):
            response = response.get("content") or response.get("text") or response
        title = _clean_title(_extract_title_text(str(response)))
        return title or derive_title(user_message, title_preview)
    except Exception as exc:
        logger.debug("Atlas title generation failed", exc_info=True)
        if failure_callback is not None:
            with suppress(Exception):
                failure_callback("title_generation", exc)
        return derive_title(user_message, title_preview)


def _write_session_title(session_db: Any, session_id: str, title: str, source: str) -> str | None:
    try:
        current_source = str(session_db.get_session_title_source(session_id) or "")
        if current_source == "user" or not title.strip():
            return None
        if not session_db.set_session_title(session_id, title.strip()):
            return None
        setter = getattr(session_db, "set_session_title_source", None)
        if callable(setter):
            setter(session_id, source)
        return title.strip()
    except Exception:
        logger.debug("Could not persist Atlas session title", exc_info=True)
        return None


def apply_instant_title(
    session_db: Any, session_id: str, user_message: str,
    title_callback: Callable[[str, str], Any] | None = None,
    title_preview: str | None = None,
) -> str | None:
    title = derive_title(user_message, title_preview) if is_titleable_user_message(user_message) else None
    persisted = _write_session_title(session_db, session_id, title, "derived") if title else None
    if persisted and title_callback is not None:
        with suppress(Exception):
            title_callback(persisted, "derived")
    return persisted


def auto_title_session(
    session_db: Any, session_id: str, user_message: str,
    failure_callback: Callable[[str, BaseException], None] | None = None,
    main_runtime: dict[str, Any] | None = None,
    title_callback: Callable[[str, str], Any] | None = None,
    runtime_validator: Callable[[], bool] | None = None,
    title_preview: str | None = None,
    *, model_call: Callable[[str], Any] | None = None,
) -> None:
    if not session_db or not session_id or not is_titleable_user_message(user_message):
        return
    try:
        if str(session_db.get_session_title_source(session_id) or "") == "user":
            return
        title = generate_title(
            user_message, failure_callback=failure_callback, main_runtime=main_runtime,
            runtime_validator=runtime_validator, title_preview=title_preview, model_call=model_call,
        )
        source = "llm" if model_call is not None and title else "derived"
        if title and (_write_session_title(session_db, session_id, title, source) is not None):
            if title_callback is not None:
                title_callback(title, source)
    except Exception:
        logger.warning("Atlas automatic title failed", exc_info=True)



