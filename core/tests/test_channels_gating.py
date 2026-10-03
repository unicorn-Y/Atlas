"""Gating decision tests — dmPolicy / groupPolicy / mention (r1 §6)."""

from __future__ import annotations

from atlas.channels.gating import (
    MentionFacts,
    MentionPolicy,
    gate_dm,
    gate_group,
    gate_mention,
)

# --- dmPolicy ------------------------------------------------------------------


def test_dm_disabled_blocks_everyone():
    assert gate_dm("disabled", "42", ["*"]).allowed is False


def test_dm_open_requires_explicit_star_or_hit():
    # r1: open still demands an explicit "*" or an allowlist hit.
    assert gate_dm("open", "42", ["*"]).allowed is True
    assert gate_dm("open", "42", ["42", "7"]).allowed is True
    assert gate_dm("open", "99", ["42"]).allowed is False
    assert gate_dm("open", "42", []).allowed is False
    assert gate_dm("open", "42", [], allow_when_empty=True).allowed is True


def test_dm_allowlist_matches_and_wildcards():
    assert gate_dm("allowlist", "42", ["42"]).allowed is True
    assert gate_dm("allowlist", "99", ["42"]).allowed is False
    assert gate_dm("allowlist", "anyone", ["*"]).allowed is True
    assert gate_dm("allowlist", "anyone", []).allowed is False
    # integer ids compare by string form
    assert gate_dm("allowlist", "42", [42]).allowed is True


def test_dm_pairing_uses_paired_ids():
    assert gate_dm("pairing", "42", [], paired_ids=["42"]).allowed is True
    assert gate_dm("pairing", "99", [], paired_ids=["42"]).reason == "pairing_required"
    assert gate_dm("pairing", "42", ["42"]).allowed is True


def test_dm_unknown_policy_fails_closed():
    assert gate_dm("weird", "42", ["*"]).allowed is False


# --- groupPolicy -----------------------------------------------------------------


def test_group_open_allows_disabled_blocks():
    assert gate_group("open", "1", []).allowed is True
    assert gate_group("disabled", "1", ["*"]).allowed is False


def test_group_allowlist_with_fallback_to_dm_list():
    assert gate_group("allowlist", "42", ["42"]).allowed is True
    assert gate_group("allowlist", "99", ["42"]).allowed is False
    # empty group list falls back to the DM allowlist (r1 resolveGroupAllowFromSources)
    assert gate_group("allowlist", "42", [], dm_allowlist=["42"]).allowed is True
    assert gate_group("allowlist", "99", [], dm_allowlist=["42"]).reason == "not_allowlisted"
    # both empty = open group world
    assert gate_group("allowlist", "anyone", [], dm_allowlist=[]).allowed is True


# --- mention gating -----------------------------------------------------------------


def test_dm_and_unrequired_groups_never_skip():
    facts = MentionFacts(was_mentioned=False)
    policy = MentionPolicy(is_group=False, require_mention=False)
    assert gate_mention(facts, policy).should_skip is False
    group_policy = MentionPolicy(is_group=True, require_mention=False)
    assert gate_mention(facts, group_policy).should_skip is False


def test_group_requires_mention_when_configured():
    facts = MentionFacts(was_mentioned=False)
    policy = MentionPolicy(is_group=True, require_mention=True)
    decision = gate_mention(facts, policy)
    assert decision.should_skip is True and decision.effective_mention is False
    mentioned = MentionFacts(was_mentioned=True)
    assert gate_mention(mentioned, policy).should_skip is False


def test_implicit_mention_kinds_honoured_and_configurable():
    policy = MentionPolicy(is_group=True, require_mention=True)
    reply_facts = MentionFacts(was_mentioned=False, implicit=("reply_to_bot",))
    assert gate_mention(reply_facts, policy).should_skip is False
    restricted = MentionPolicy(is_group=True, require_mention=True, enabled_implicit=("native",))
    assert gate_mention(reply_facts, restricted).should_skip is True


def test_control_command_bypasses_mention_when_authorized():
    policy = MentionPolicy(is_group=True, require_mention=True)
    facts = MentionFacts(was_mentioned=False)
    decision = gate_mention(facts, policy, has_control_command=True, command_authorized=True)
    assert decision.bypassed is True and decision.should_skip is False
    unauthorized = gate_mention(facts, policy, has_control_command=True, command_authorized=False)
    assert unauthorized.should_skip is True
