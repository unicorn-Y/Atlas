"""Routing resolution tests — OpenClaw priority ladder (r1 §1.3)."""

from __future__ import annotations

from atlas.channels.contract import MessageEvent
from atlas.channels.routing import resolve_route


def make_event(
    chat_id: str = "100",
    *,
    channel: str = "telegram",
    account: str = "",
    is_group: bool = False,
    thread_id: str = "",
    reply_to: str = "",
    mentions: list[str] | None = None,
    text: str = "",
) -> MessageEvent:
    return MessageEvent(
        channel=channel,
        account=account,
        event_id=f"evt-{chat_id}-{thread_id}",
        chat_id=chat_id,
        sender_id="42",
        is_group=is_group,
        thread_id=thread_id,
        reply_to_event_id=reply_to,
        mentions=mentions or [],
        text=text,
    )


def test_peer_binding_wins_over_everything():
    bindings = [
        {"agent_id": "peer-agent", "channel": "telegram", "account": "*", "peer_id": "100"},
        {"agent_id": "channel-agent", "channel": "telegram", "account": ""},
    ]
    assert resolve_route(bindings, make_event("100")) == "peer-agent"


def test_parent_peer_binding_catches_thread_replies():
    bindings = [
        {
            "agent_id": "thread-agent",
            "channel": "telegram",
            "account": "*",
            "parent_peer_id": "200",
        },
    ]
    event = make_event("300", thread_id="200")
    assert resolve_route(bindings, event) == "thread-agent"


def test_wildcard_kind_binding_before_account_and_channel():
    bindings = [
        {"agent_id": "group-agent", "channel": "telegram", "account": "*", "peer_kind": "group"},
        {"agent_id": "acct-agent", "channel": "telegram", "account": "work"},
        {"agent_id": "channel-agent", "channel": "telegram", "account": ""},
    ]
    group_event = make_event("400", account="work", is_group=True)
    assert resolve_route(bindings, group_event) == "group-agent"
    direct_event = make_event("500", account="work")
    assert resolve_route(bindings, direct_event) == "acct-agent"
    default_event = make_event("600")
    assert resolve_route(bindings, default_event) == "channel-agent"


def test_account_level_beats_channel_level():
    bindings = [
        {"agent_id": "acct-agent", "channel": "telegram", "account": "work"},
        {"agent_id": "channel-agent", "channel": "telegram", "account": "*"},
    ]
    assert resolve_route(bindings, make_event("700", account="work")) == "acct-agent"
    assert resolve_route(bindings, make_event("701", account="play")) == "channel-agent"


def test_channel_binding_default_account_only_matches_default():
    bindings = [{"agent_id": "channel-agent", "channel": "telegram", "account": ""}]
    assert resolve_route(bindings, make_event("800", account="")) == "channel-agent"
    # named account misses the channel layer; the unique-agent fallback picks it up
    assert resolve_route(bindings, make_event("801", account="work")) == "channel-agent"
    # with a real roster the miss fails closed
    assert resolve_route(
        bindings, make_event("801", account="work"), agent_ids=["channel-agent", "other"]
    ) is None


def test_star_channel_matches_any_channel():
    bindings = [{"agent_id": "catch-all", "channel": "*", "account": "*"}]
    assert resolve_route(bindings, make_event("900", channel="email")) == "catch-all"


def test_kind_mismatch_does_not_match_wildcard():
    bindings = [{"agent_id": "group-agent", "channel": "telegram", "peer_kind": "group"}]
    roster = ["group-agent", "someone-else"]
    assert resolve_route(bindings, make_event("910", is_group=False), agent_ids=roster) is None
    matched = resolve_route(bindings, make_event("911", is_group=True), agent_ids=roster)
    assert matched == "group-agent"


def test_first_match_within_layer_wins():
    bindings = [
        {"agent_id": "first", "channel": "telegram", "account": "*", "peer_id": "100"},
        {"agent_id": "second", "channel": "telegram", "account": "*", "peer_id": "100"},
    ]
    assert resolve_route(bindings, make_event("100")) == "first"


def test_unique_agent_roster_fallback():
    assert resolve_route([], make_event("1000"), agent_ids=["solo"]) == "solo"
    bindings = [{"agent_id": "only-one", "channel": "discord"}]
    assert resolve_route(bindings, make_event("1001", channel="discord", account="x")) == "only-one"


def test_multi_agent_without_match_fails_closed():
    bindings = [
        {"agent_id": "a", "channel": "telegram", "peer_id": "1"},
        {"agent_id": "b", "channel": "telegram", "peer_id": "2"},
    ]
    assert resolve_route(bindings, make_event("3"), agent_ids=["a", "b"]) is None
    assert resolve_route(bindings, make_event("3")) is None


def test_openclaw_nested_match_spelling_supported():
    bindings = [
        {
            "agentId": "nested",
            "match": {"channel": "telegram", "accountId": "work", "target": "55"},
        },
    ]
    assert resolve_route(bindings, make_event("55", account="work")) == "nested"
    assert resolve_route(
        bindings, make_event("55", account=""), agent_ids=["nested", "other"]
    ) is None


def test_atlas_target_alias_supported():
    bindings = [{"agent_id": "ops", "channel": "telegram", "target": "77"}]
    assert resolve_route(bindings, make_event("77")) == "ops"


def test_empty_bindings_without_roster_returns_none():
    assert resolve_route([], make_event("1")) is None


def test_channel_mismatch_never_routes():
    bindings = [{"agent_id": "x", "channel": "telegram", "account": "*"}]
    assert resolve_route(bindings, make_event("1", channel="slack")) is None


def test_group_mention_routes_to_named_agent_before_group_default():
    bindings = [
        {"agent_id": "general", "channel": "telegram", "account": "*", "peer_kind": "group"},
        {"agent_id": "reviewer", "channel": "telegram", "account": "*", "mention_names": ["review", "reviewer"]},
    ]
    event = make_event("42", account="work", is_group=True, mentions=["reviewer"])
    assert resolve_route(bindings, event) == "reviewer"
    # Unknown names fall through to ordinary group policy exactly once.
    assert resolve_route(bindings, make_event("42", account="work", is_group=True, mentions=["missing"])) == "general"


def test_wecom_rendered_text_at_name_routes_to_agent():
    bindings = [
        {"agent_id": "general", "channel": "wecom", "account": "*", "peer_kind": "group"},
        {"agent_id": "reviewer", "channel": "wecom", "account": "*", "mention_names": ["代码助手"]},
    ]
    event = make_event("wr_group", channel="wecom", account="main", is_group=True,
                       text="@代码助手 请检查")
    assert resolve_route(bindings, event) == "reviewer"


def test_group_mention_respects_binding_scope_and_ignores_direct_messages():
    bindings = [{"agent_id": "ops", "channel": "telegram", "account": "work", "peer_id": "100", "mention_names": ["ops"]}]
    roster = ["ops", "other"]
    assert resolve_route(bindings, make_event("200", account="work", is_group=True, mentions=["ops"]), agent_ids=roster) is None
    assert resolve_route(bindings, make_event("100", account="work", is_group=True, mentions=["ops"]), agent_ids=roster) == "ops"
    # Mentions are ignored for direct messages, which still follow their normal exact-peer binding.
    assert resolve_route(bindings, make_event("100", account="work", mentions=["ops"]), agent_ids=roster) == "ops"
