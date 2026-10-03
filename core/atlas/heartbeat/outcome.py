"""``heartbeat_respond`` structured contract + legacy text conventions.

Ported from OpenClaw (source freeze ``3e5560873a4``):

- ``src/auto-reply/heartbeat-tool-response.ts`` -> :class:`HeartbeatOutcome`
  fields, the outcome enum (``no_change|progress|done|blocked|
  needs_attention``) and normalization rules (structured output wins over the
  text fallback; scratch is a *complete replacement* for monitor prose).
- ``src/auto-reply/tokens.ts`` -> ``NO_REPLY`` (silent reply token) and
  ``HEARTBEAT_OK`` (heartbeat acknowledgement token).
- ``src/auto-reply/heartbeat.ts`` -> :func:`strip_heartbeat_token`
  (``stripHeartbeatToken``): token stripped at the start/end of the reply
  (lightweight markup tolerated); whatever remains within the 300-character
  ack budget is dropped entirely, longer remainders become a visible alert.
  A token in the middle of the text is not special.

``no_change`` outcomes (and silent legacy acks) never notify and are never
written to the outcome store (:attr:`HeartbeatOutcome.stored`).
"""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from typing import Any

# Ported constants.
HEARTBEAT_RESPONSE_TOOL_NAME = "heartbeat_respond"
HEARTBEAT_OUTCOMES = ("no_change", "progress", "done", "blocked", "needs_attention")
HEARTBEAT_PRIORITIES = ("low", "normal", "high")
SILENT_REPLY_TOKEN = "NO_REPLY"  # tokens.ts SILENT_REPLY_TOKEN
HEARTBEAT_TOKEN = "HEARTBEAT_OK"  # tokens.ts HEARTBEAT_TOKEN
DEFAULT_ACK_MAX_CHARS = 300  # heartbeat.ts DEFAULT_HEARTBEAT_ACK_MAX_CHARS

_HEARTBEAT_TRAILING_RE = re.compile(re.escape(HEARTBEAT_TOKEN) + r"[^\w]{0,4}$")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class HeartbeatOutcome:
    """Normalized heartbeat turn settlement."""

    outcome: str  # one of HEARTBEAT_OUTCOMES
    notify: bool
    summary: str = ""
    notification_text: str = ""
    reason: str = ""
    priority: str = ""  # "" | low | normal | high
    next_check: str = ""
    # Complete replacement for the agent's monitor scratch (None = unchanged).
    scratch: str | None = None
    source: str = "structured"  # structured | legacy | empty

    @property
    def is_no_change(self) -> bool:
        return self.outcome == "no_change"

    @property
    def silent(self) -> bool:
        """True when nothing may be delivered for this outcome."""
        return self.is_no_change or not self.notify

    @property
    def stored(self) -> bool:
        """Outcome-store semantics: only meaningful outcomes are persisted;
        ``no_change`` and silent acks are never stored."""
        return not self.is_no_change

    def notification_body(self) -> str:
        """User-visible text for delivery (empty when silent)."""
        if self.silent:
            return ""
        return (self.notification_text or self.summary).strip()


def silent_outcome(source: str = "empty") -> HeartbeatOutcome:
    return HeartbeatOutcome(outcome="no_change", notify=False, summary="", source=source)


def parse_outcome(turn_result: Any) -> HeartbeatOutcome:
    """Parse a model turn result into a :class:`HeartbeatOutcome`.

    Preference order mirrors OpenClaw: a structured ``heartbeat_respond``
    payload (dict, tool envelope, or a single JSON object string) wins; the
    legacy text conventions (``NO_REPLY`` / ``HEARTBEAT_OK`` / plain alert
    text) are the fallback.
    """
    if turn_result is None:
        return silent_outcome()
    if isinstance(turn_result, HeartbeatOutcome):
        return turn_result
    if isinstance(turn_result, dict):
        structured = _parse_structured(turn_result)
        if structured is not None:
            return structured
        return _parse_text(_dict_text(turn_result))
    if isinstance(turn_result, str):
        text = turn_result.strip()
        if not text:
            return silent_outcome()
        if text.startswith("{") and text.endswith("}"):
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            if isinstance(data, dict):
                structured = _parse_structured(data)
                if structured is not None:
                    return structured
        return _parse_text(text)
    return _parse_text(str(turn_result))


# ---------------------------------------------------------------------------
# Structured parsing (port of normalizeHeartbeatToolResponse)
# ---------------------------------------------------------------------------
def _parse_structured(data: dict) -> HeartbeatOutcome | None:
    payload = data
    if "outcome" not in payload:
        # Tool-call envelopes: {"name": "heartbeat_respond", "arguments": {...}}
        # or a wrapper key carrying the arguments directly.
        for key in ("arguments", "input", "params", "heartbeat_respond", "response"):
            inner = payload.get(key)
            if isinstance(inner, dict) and "outcome" in inner:
                payload = inner
                break
        else:
            return None
    outcome = str(payload.get("outcome", "")).strip().lower()
    if outcome not in HEARTBEAT_OUTCOMES:
        return None
    notify = payload.get("notify")
    if not isinstance(notify, bool):
        notify = outcome != "no_change"
    notification_text = _read_str(payload, "notificationText", "notification_text")
    summary = _read_str(payload, "summary") or notification_text
    priority = _read_str(payload, "priority").lower()
    return HeartbeatOutcome(
        outcome=outcome,
        notify=notify,
        summary=summary,
        notification_text=notification_text,
        reason=_read_str(payload, "reason"),
        priority=priority if priority in HEARTBEAT_PRIORITIES else "",
        next_check=_read_str(payload, "nextCheck", "next_check"),
        scratch=payload.get("scratch") if isinstance(payload.get("scratch"), str) else None,
        source="structured",
    )


def _read_str(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _dict_text(data: dict) -> str:
    for key in ("text", "reply", "message", "output"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    return ""


# ---------------------------------------------------------------------------
# Legacy text parsing
# ---------------------------------------------------------------------------
def _token_only_re(token: str) -> re.Pattern[str]:
    body = re.escape(token)
    return re.compile(rf"^\s*{body}(?:[\s.*`~_]+{body})*[\s.*`~_]*$", re.IGNORECASE)


def _is_token_only(text: str, token: str) -> bool:
    """Port of ``isSilentReplyText``: token-only replies, including repeated
    tokens separated by whitespace; models sometimes wrap the token in
    punctuation, so strip edge punctuation and retry."""
    trimmed = text.strip()
    if not trimmed:
        return False
    if _token_only_re(token).match(trimmed):
        return True
    stripped = trimmed.strip(string.punctuation)
    return bool(stripped) and _token_only_re(token).match(stripped) is not None


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _strip_markup(text: str) -> str:
    """Lightweight markup normalization so HEARTBEAT_OK wrapped in HTML or
    Markdown still strips (port of stripHeartbeatToken's stripMarkup)."""
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"^[*`~_]+", "", text)
    text = re.sub(r"[*`~_]+$", "", text)
    return text


def _strip_token_at_edges(text: str) -> tuple[str, bool]:
    """Strip HEARTBEAT_OK at the start and/or end of the text (including up
    to 4 trailing non-word characters). Returns collapsed text + didStrip."""
    text = text.strip()
    did_strip = False
    while True:
        current = text.strip()
        if not current:
            break
        changed = False
        if current.startswith(HEARTBEAT_TOKEN):
            text = current[len(HEARTBEAT_TOKEN) :].lstrip()
            did_strip = True
            changed = True
        if _HEARTBEAT_TRAILING_RE.search(current):
            idx = current.rfind(HEARTBEAT_TOKEN)
            before = current[:idx].rstrip()
            after = current[idx + len(HEARTBEAT_TOKEN) :].lstrip()
            text = (before + after).rstrip()
            did_strip = True
            changed = True
        if not changed:
            break
    return _collapse_ws(text), did_strip


def strip_heartbeat_token(
    raw: str, *, max_ack_chars: int = DEFAULT_ACK_MAX_CHARS
) -> str | None:
    """Port of ``stripHeartbeatToken`` (heartbeat mode).

    Returns the remaining visible text, or ``None`` when the reply should be
    skipped entirely (token-only, or remainder within the ack budget).
    """
    text = raw.strip()
    if not text:
        return None
    if HEARTBEAT_TOKEN not in text:
        return _collapse_ws(text)

    stripped_original, did_original = _strip_token_at_edges(text)
    stripped_normalized, did_normalized = _strip_token_at_edges(_strip_markup(text))
    picked = stripped_original if (did_original and stripped_original) else stripped_normalized
    if not (did_original or did_normalized):
        # Token only appears in the middle: not special, deliver as-is.
        return _collapse_ws(text)
    if not picked:
        return None
    if len(picked) <= max_ack_chars:
        return None
    return picked


def _parse_text(text: str) -> HeartbeatOutcome:
    stripped = text.strip()
    if not stripped:
        return silent_outcome(source="legacy")
    if _is_token_only(stripped, SILENT_REPLY_TOKEN):
        return silent_outcome(source="legacy")
    remaining = strip_heartbeat_token(stripped)
    if remaining is None:
        return silent_outcome(source="legacy")
    body = remaining
    return HeartbeatOutcome(
        outcome="needs_attention",
        notify=True,
        summary=body,
        notification_text=body,
        source="legacy",
    )


__all__ = [
    "DEFAULT_ACK_MAX_CHARS",
    "HEARTBEAT_OUTCOMES",
    "HEARTBEAT_PRIORITIES",
    "HEARTBEAT_RESPONSE_TOOL_NAME",
    "HEARTBEAT_TOKEN",
    "HeartbeatOutcome",
    "SILENT_REPLY_TOKEN",
    "parse_outcome",
    "silent_outcome",
    "strip_heartbeat_token",
]
