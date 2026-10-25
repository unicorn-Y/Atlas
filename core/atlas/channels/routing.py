"""Inbound route resolution — port of OpenClaw ``resolveAgentRoute`` (r1 §1.3/§3).

Pure functions: a binding list plus one normalized :class:`MessageEvent` yield an
``agent_id`` (or ``None`` = fail closed). Priority ladder, first match wins
within each layer, binding order breaks ties:

    peer → parentPeer → wildcard(kind) → account → channel → unique-agent fallback

Binding shape (dict, tolerant of the ``agentId``/``match`` OpenClaw spelling)::

    {
      "agent_id": "ops",            # or "agentId"
      "channel": "telegram",        # required
      "account": "" | "work" | "*",  # "" = default account, "*" = any
      "peer_kind": "" | "direct" | "group" | "channel",
      "peer_id": "",                 # "" + peer_kind set = kind-level wildcard
      "parent_peer_id": "",          # thread parent peer id
    }
"""

from __future__ import annotations

import re
from typing import Any

from atlas.channels.contract import MessageEvent


def _binding_agent(binding: dict[str, Any]) -> str:
    return str(binding.get("agent_id") or binding.get("agentId") or "")


def _binding_match(binding: dict[str, Any]) -> dict[str, Any]:
    match = binding.get("match")
    return match if isinstance(match, dict) else binding


def _normalized_names(values: Any) -> set[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(value).strip().lstrip("@").casefold() for value in values if str(value).strip()}


def _peer_id(match: dict[str, Any]) -> str:
    """Exact peer id (OpenClaw ``peer.id`` / Atlas agent-profile ``target``)."""
    return str(match.get("peer_id") or match.get("target") or "")


def _has_peer_scope(match: dict[str, Any]) -> bool:
    return bool(_peer_id(match) or match.get("parent_peer_id") or match.get("peer_kind"))


def _match_channel(match: dict[str, Any], event: MessageEvent) -> bool:
    channel = str(match.get("channel", "") or "")
    return channel in ("", "*") or channel == event.channel


def _match_account(match: dict[str, Any], event: MessageEvent) -> bool:
    """``""`` binds the default account, ``"*"`` binds every account."""
    account = str(match.get("account", match.get("accountId", "")) or "")
    if account == "*":
        return True
    if account == "":
        return event.account == ""
    return account == event.account


def _event_peer_kind(event: MessageEvent) -> str:
    if event.is_group:
        return "group"
    return "direct"


def _match_peer_kind(match: dict[str, Any], event: MessageEvent) -> bool:
    kind = str(match.get("peer_kind", "") or "")
    if not kind:
        return True
    if kind == "*":
        return True
    return kind == _event_peer_kind(event)


def _match_peer_id(match: dict[str, Any], event: MessageEvent) -> bool:
    peer_id = _peer_id(match)
    return bool(peer_id) and peer_id == event.chat_id


def _match_parent_peer(match: dict[str, Any], event: MessageEvent) -> bool:
    """Message lives inside a thread whose parent peer is bound."""
    parent = str(match.get("parent_peer_id", "") or "")
    if not parent:
        return False
    if event.thread_id and event.thread_id == parent:
        return True
    # Reply-to-a-bound-message: OpenClaw treats the quoted peer as the parent.
    return bool(event.reply_to_event_id) and parent == event.chat_id


PERMISSION_MODES = frozenset({
    "full_access", "ask_each", "ask_writes", "auto_file", "plan", "read_only",
})


def validate_permission_mode(value: Any) -> str:
    if value not in PERMISSION_MODES:
        raise ValueError("invalid channel permission_mode")
    return str(value)


def _layer_bindings(bindings: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    for binding in bindings:
        agent = _binding_agent(binding)
        if not agent:
            continue
        if predicate(_binding_match(binding)):
            return binding
    return None


def resolve_binding(
    bindings: list[dict[str, Any]],
    event: MessageEvent,
    *,
    agent_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """Resolve the agent for one inbound event, or ``None`` (fail closed).

    ``agent_ids`` is the full agent roster; when given and exactly one agent
    exists, it is the final fallback even without a matching binding. Without a
    roster, a unique agent among the bindings themselves is the fallback.
    """
    usable = []
    for binding in bindings or []:
        match = _binding_match(binding)
        if _match_channel(match, event):
            usable.append((binding, match))

    # External group mentions target the named bot/agent before ordinary peer
    # routing. Names are configured on each binding as mention_names (or the
    # agent's display_name/username); adapters supply normalized mention names.
    if event.is_group and event.mentions:
        mentioned = _normalized_names(event.mentions)
        for binding, match in usable:
            names = match.get("mention_names") or binding.get("mention_names") or []
            names = [*names, match.get("display_name"), match.get("username"), binding.get("display_name"), binding.get("username")]
            aliases = _normalized_names([value for value in names if value])
            peer_matches = not _has_peer_scope(match) or _match_peer_id(match, event) or _match_parent_peer(match, event)
            if aliases & mentioned and _match_account(match, event) and _match_peer_kind(match, event) and peer_matches:
                return binding
    if event.is_group:
        # Some callback protocols (notably WeCom XML events) expose only the
        # rendered text. Resolve @display-name against configured aliases.
        text_mentions = {value.casefold() for value in re.findall(r"@([^\s,，:：@]{1,80})", event.text or "")}
        if text_mentions:
            for binding, match in usable:
                names = match.get("mention_names") or binding.get("mention_names") or []
                names = [*names, match.get("display_name"), match.get("username"), binding.get("display_name"), binding.get("username")]
                aliases = _normalized_names([value for value in names if value])
                peer_matches = not _has_peer_scope(match) or _match_peer_id(match, event) or _match_parent_peer(match, event)
                if aliases & text_mentions and _match_account(match, event) and _match_peer_kind(match, event) and peer_matches:
                    return binding

    def scoped(predicate) -> dict[str, Any] | None:
        def check(match: dict[str, Any]) -> bool:
            return (
                _match_account(match, event)
                and _match_peer_kind(match, event)
                and predicate(match, event)
            )

        return _layer_bindings([b for b, _ in usable], check)

    # 1. exact peer, 2. parent peer, 3. kind-level wildcard (peer listed, id empty)
    agent = scoped(_match_peer_id) if usable else None
    if agent:
        return agent
    agent = scoped(_match_parent_peer) if usable else None
    if agent:
        return agent

    def match_wildcard(match: dict[str, Any], event: MessageEvent) -> bool:
        has_kind = bool(str(match.get("peer_kind", "") or ""))
        return has_kind and not _peer_id(match) and not match.get("parent_peer_id")

    agent = scoped(match_wildcard) if usable else None
    if agent:
        return agent

    # 4. account-level binding (no peer constraints at all)
    def match_account_level(match: dict[str, Any], event: MessageEvent) -> bool:
        # A binding that exists only to name this agent in external group
        # mentions must not capture every unmentioned group message.
        named_group_member = event.is_group and bool(match.get("mention_names"))
        return not _has_peer_scope(match) and not named_group_member

    agent = scoped(match_account_level) if usable else None
    if agent:
        return agent

    # 5. channel-level binding — the OpenClaw "{channel}" catch-all, i.e. account "*"
    for binding, match in usable:
        agent = _binding_agent(binding)
        if not agent:
            continue
        if event.is_group and match.get("mention_names"):
            continue
        account = str(match.get("account", match.get("accountId", "")) or "")
        if not _has_peer_scope(match) and account == "*":
            return binding

    # 6. unique agent fallback
    roster = list(agent_ids) if agent_ids else sorted({
        _binding_agent(b) for b, _ in usable if _binding_agent(b)
    })
    if len(roster) == 1:
        return {"agent_id": roster[0]}
    return None


def resolve_route(
    bindings: list[dict[str, Any]], event: MessageEvent, *, agent_ids: list[str] | None = None,
) -> str | None:
    binding = resolve_binding(bindings, event, agent_ids=agent_ids)
    return _binding_agent(binding) if binding else None


def resolve_group_recipients(
    members: list[dict[str, Any]], text: str, *, mentions: list[str] | None = None,
    role: str = "", topic_routes: list[dict[str, Any]] | None = None,
    default_route: list[str] | None = None, fallback: str = "broadcast",
) -> dict[str, Any]:
    """Choose deterministic group responders from mentions, topic rules or default.

    Explicit mentions win. Otherwise enabled rules match a supplied role or any
    case-insensitive keyword contained in the message. Highest priority wins;
    equal-priority rules with different targets use the configured fallback.
    This shares alias normalization with external channel routing.
    """
    member_ids = [str(member.get("id") or member.get("agent_id") or "") for member in members]
    name_to_id: dict[str, str] = {}
    for member in members:
        member_id = str(member.get("id") or member.get("agent_id") or "")
        aliases = _normalized_names([
            member_id, member.get("name"), member.get("display_name"),
            member.get("mention_names", []),
        ])
        for alias in aliases:
            name_to_id[alias] = member_id
    mentioned = _normalized_names(mentions or [])
    text_mentions = _normalized_names(re.findall(r"@([^\s,，:：@]{1,80})", text or ""))
    explicit = mentioned | text_mentions
    explicit_ids = {name_to_id[alias] for alias in explicit if alias in name_to_id}
    selected = [member_id for member_id in member_ids if member_id in explicit_ids]
    if selected:
        return {"agent_ids": selected, "matched_rule": "mention", "reason": "mention", "conflict": False}

    normalized_role = str(role or "").strip().casefold()
    lowered = (text or "").casefold()
    matches = []
    for route in topic_routes or []:
        if route.get("enabled", True) is False:
            continue
        keywords = [str(value).casefold() for value in route.get("keywords", []) if value]
        route_role = str(route.get("role") or "").casefold()
        if ((normalized_role and route_role == normalized_role)
                or (route_role and route_role in lowered)
                or any(word in lowered for word in keywords)):
            matches.append(route)
    if matches:
        highest = max(int(route.get("priority", 0)) for route in matches)
        winners = [route for route in matches if int(route.get("priority", 0)) == highest]
        target_sets = {tuple(route.get("agent_ids") or []) for route in winners}
        if len(target_sets) == 1:
            winner = winners[0]
            return {"agent_ids": [item for item in winner.get("agent_ids", []) if item in member_ids],
                    "matched_rule": str(winner.get("id") or "topic"), "reason": "topic", "conflict": False}
        if fallback == "default" and default_route:
            return {"agent_ids": [item for item in default_route if item in member_ids],
                    "matched_rule": "route-conflict-default", "reason": "conflict", "conflict": True}
        return {"agent_ids": member_ids, "matched_rule": "route-conflict-broadcast",
                "reason": "conflict", "conflict": True}
    if default_route:
        return {"agent_ids": [item for item in default_route if item in member_ids],
                "matched_rule": "default", "reason": "default", "conflict": False}
    return {"agent_ids": member_ids, "matched_rule": "broadcast", "reason": "fallback", "conflict": False}


__all__ = ["resolve_route", "resolve_binding", "resolve_group_recipients", "validate_permission_mode"]
