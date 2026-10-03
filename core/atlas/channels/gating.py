"""Access gating for inbound messages — port of OpenClaw sender/mention gates (r1 §6).

Pure decision functions, no I/O:

- :func:`gate_dm`   — ``dmPolicy``: pairing | allowlist | open | disabled.
  Per r1, ``open`` still requires an explicit ``"*"`` or an allowlist hit;
  ``allow_when_empty`` covers the OpenClaw ``allowWhenEmpty`` escape hatch.
- :func:`gate_group` — ``groupPolicy``: open | allowlist | disabled, with the
  DM allowlist as fallback when the group list is empty.
- :func:`gate_mention` — port of ``resolveInboundMentionDecision`` (explicit
  mention, implicit kinds like reply-to-bot, text-command bypass).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GateDecision:
    allowed: bool
    reason: str = "allowed"
    detail: str = ""


@dataclass(slots=True)
class MentionDecision:
    effective_mention: bool
    should_skip: bool
    bypassed: bool = False


def _has_sender(sender_id: str, allowlist: list[Any] | None) -> bool:
    for entry in allowlist or []:
        if str(entry) == str(sender_id):
            return True
    return False


def gate_dm(
    policy: str,
    sender_id: str,
    allowlist: list[Any] | None,
    *,
    paired_ids: list[Any] | None = None,
    allow_when_empty: bool = False,
) -> GateDecision:
    """Direct-message admission under ``dmPolicy``."""
    entries = [entry for entry in (allowlist or []) if str(entry).strip()]
    if policy == "disabled":
        return GateDecision(False, "disabled")
    if policy == "pairing":
        if _has_sender(sender_id, entries) or _has_sender(sender_id, paired_ids):
            return GateDecision(True, "allowed", "pairing")
        return GateDecision(False, "pairing_required")
    if policy == "open":
        if not entries:
            if allow_when_empty:
                return GateDecision(True, "allowed", "allow_when_empty")
            return GateDecision(False, "empty_allowlist")
        if "*" in entries or _has_sender(sender_id, entries):
            return GateDecision(True, "allowed")
        return GateDecision(False, "not_allowlisted")
    if policy == "allowlist":
        if not entries:
            if allow_when_empty:
                return GateDecision(True, "allowed", "allow_when_empty")
            return GateDecision(False, "empty_allowlist")
        if "*" in entries or _has_sender(sender_id, entries):
            return GateDecision(True, "allowed")
        return GateDecision(False, "not_allowlisted")
    return GateDecision(False, "unknown_policy")


def gate_group(
    policy: str,
    sender_id: str,
    group_allowlist: list[Any] | None,
    *,
    dm_allowlist: list[Any] | None = None,
) -> GateDecision:
    """Group-message admission under ``groupPolicy`` (falls back to the DM list)."""
    entries = [entry for entry in (group_allowlist or []) if str(entry).strip()]
    if policy == "disabled":
        return GateDecision(False, "disabled")
    if policy == "open":
        return GateDecision(True, "allowed")
    if policy == "allowlist":
        if not entries:
            # r1: groupAllowFrom is independent but falls back to allowFrom.
            fallback = [entry for entry in (dm_allowlist or []) if str(entry).strip()]
            if not fallback:
                return GateDecision(True, "allowed", "empty_allowlist")
            if "*" in fallback or _has_sender(sender_id, fallback):
                return GateDecision(True, "allowed", "dm_allowlist_fallback")
            return GateDecision(False, "not_allowlisted")
        if "*" in entries or _has_sender(sender_id, entries):
            return GateDecision(True, "allowed")
        return GateDecision(False, "not_allowlisted")
    return GateDecision(False, "unknown_policy")


IMPLICIT_MENTION_KINDS = ("reply_to_bot", "quoted_bot", "bot_thread_participant", "native")


@dataclass(slots=True)
class MentionFacts:
    can_detect_mention: bool = True
    was_mentioned: bool = False
    implicit: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class MentionPolicy:
    is_group: bool = False
    require_mention: bool = False
    enabled_implicit: tuple[str, ...] = IMPLICIT_MENTION_KINDS
    allow_text_commands: bool = True


def gate_mention(
    facts: MentionFacts,
    policy: MentionPolicy,
    *,
    has_control_command: bool = False,
    command_authorized: bool = False,
) -> MentionDecision:
    """Port of ``resolveInboundMentionDecision``.

    DMs and policies without ``require_mention`` never skip. Inside a mention-
    required group: explicit or enabled-implicit mention passes; authorized
    control commands bypass; everything else is skipped.
    """
    if not policy.is_group or not policy.require_mention:
        return MentionDecision(True, False)
    if facts.was_mentioned:
        return MentionDecision(True, False)
    enabled = set(policy.enabled_implicit)
    if facts.can_detect_mention and any(kind in enabled for kind in facts.implicit):
        return MentionDecision(True, False)
    if (
        policy.allow_text_commands
        and has_control_command
        and command_authorized
    ):
        return MentionDecision(True, False, bypassed=True)
    return MentionDecision(False, True)


__all__ = [
    "GateDecision",
    "MentionDecision",
    "MentionFacts",
    "MentionPolicy",
    "IMPLICIT_MENTION_KINDS",
    "gate_dm",
    "gate_group",
    "gate_mention",
]
