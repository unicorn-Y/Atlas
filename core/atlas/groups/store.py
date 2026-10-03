"""Group definitions persisted under ``data/groups/*.toml``.

One file per group (TomlRecordStore pattern, integration-map §2): id, name,
member_agent_ids, enabled, delivery and the round_caps state-machine limits.
Membership is validated against a :class:`MemberLookup` seam — the router /
integration binds it to :class:`atlas.persistent_agents.PersistentAgentService`
(``get``), tests bind a fake. The room log itself lives with the orchestrator,
appended at ``<group_id>/log.jsonl`` next to these files (integration-map
§7.2: ``data/groups/<roomId>/log.jsonl``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

from atlas.task_artifacts import TomlRecordStore

GROUP_FIELDS: frozenset[str] = frozenset({
    "id", "name", "member_agent_ids", "enabled", "delivery", "round_caps",
    "created_at", "updated_at",
})

ROUND_CAP_FIELDS: frozenset[str] = frozenset({
    "max_rounds", "max_messages", "max_continuations",
})

# Hermes group-round hard caps (r4 §3.3): rounds per drive, total messages per
# drive, and @mention-handoff continuations — each capped independently.
DEFAULT_ROUND_CAPS: dict[str, int] = {
    "max_rounds": 4,
    "max_messages": 24,
    "max_continuations": 3,
}

DELIVERY_MODES: frozenset[str] = frozenset({"origin", "owner", "none"})

_DELIVERY_RE = re.compile(r"^[^:\s]+:[^:\s]+$")


class MemberLookup(Protocol):
    """Membership validation seam; bound to PersistentAgentService by the router.

    Only ``get`` is required — the persistent-agent service already implements it.
    """

    def get(self, agent_id: str) -> dict[str, Any] | None: ...


def default_round_caps() -> dict[str, int]:
    return dict(DEFAULT_ROUND_CAPS)


class GroupStore(TomlRecordStore):
    """Group-definition store validating the whitelisted record shape."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, "groups")

    def put(self, value: dict[str, Any]) -> dict[str, Any]:  # noqa: D102
        return super().put(validate_group_record(value))


def validate_group_record(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize a group record; raises ValueError on unknown/invalid fields."""
    unknown = set(value) - GROUP_FIELDS
    if unknown:
        raise ValueError(f"group contains unsupported fields: {sorted(unknown)}")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required")
    members = value.get("member_agent_ids", [])
    if not isinstance(members, list) or any(
        not isinstance(item, str) or not item.strip() for item in members
    ):
        raise ValueError("member_agent_ids must be a list of agent ids")
    if len(set(members)) != len(members):
        raise ValueError("member_agent_ids must not contain duplicates")
    if not members:
        raise ValueError("a group needs at least one member")
    enabled = value.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    delivery = value.get("delivery", "origin")
    if not isinstance(delivery, str) or not (
        delivery in DELIVERY_MODES or _DELIVERY_RE.fullmatch(delivery)
    ):
        raise ValueError("delivery must be 'origin', 'owner', 'none' or '<channel:target>'")
    return {
        **value,
        "name": name,
        "member_agent_ids": list(members),
        "enabled": enabled,
        "delivery": delivery,
        "round_caps": validate_round_caps(value.get("round_caps") or {}),
    }


def validate_round_caps(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("round_caps must be a table")
    unknown = set(value) - ROUND_CAP_FIELDS
    if unknown:
        raise ValueError(f"round_caps contains unsupported fields: {sorted(unknown)}")
    caps = default_round_caps()
    for key in ROUND_CAP_FIELDS:
        if key not in value:
            continue
        raw = value[key]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise ValueError(f"round_caps.{key} must be a positive integer")
        caps[key] = raw
    return caps


class GroupService:
    """CRUD over group definitions; membership validated via MemberLookup."""

    def __init__(self, store: GroupStore, lookup: MemberLookup | None = None) -> None:
        self._store = store
        self._lookup = lookup

    @property
    def store(self) -> GroupStore:
        """Backing store; the orchestrator derives its room-log root from ``store.root``."""
        return self._store

    @property
    def lookup(self) -> MemberLookup | None:
        """The bound membership validator (``PersistentAgentService`` at integration)."""
        return self._lookup

    def list_groups(self) -> list[dict[str, Any]]:
        return self._store.list()

    def get(self, group_id: str) -> dict[str, Any] | None:
        return self._store.get(group_id)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        data.setdefault("enabled", True)
        data.setdefault("delivery", "origin")
        data.setdefault("round_caps", default_round_caps())
        self.validate_members(data.get("member_agent_ids", []))
        return self._store.put(data)

    def update(self, group_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        old = self._require(group_id)
        merged = {**old, **patch, "id": group_id, "created_at": old["created_at"]}
        if "round_caps" in patch:
            # A partial caps PATCH merges over the stored caps instead of resetting
            # the sibling limits back to defaults (same rule as agent tables).
            merged["round_caps"] = {**old.get("round_caps", {}), **(patch.get("round_caps") or {})}
        self.validate_members(merged.get("member_agent_ids", []))
        return self._store.put(merged)

    def delete(self, group_id: str) -> None:
        if not self._store.delete(group_id):
            raise KeyError(f"group not found: {group_id}")

    def add_member(self, group_id: str, agent_id: str) -> list[str]:
        group = self._require(group_id)
        if agent_id in group["member_agent_ids"]:
            raise ValueError(f"already a member: {agent_id}")
        self.validate_members([agent_id])
        updated = self._store.put({
            **group,
            "member_agent_ids": [*group["member_agent_ids"], agent_id],
        })
        return updated["member_agent_ids"]

    def remove_member(self, group_id: str, agent_id: str) -> list[str]:
        group = self._require(group_id)
        if agent_id not in group["member_agent_ids"]:
            raise KeyError(f"not a member: {agent_id}")
        remaining = [item for item in group["member_agent_ids"] if item != agent_id]
        if not remaining:
            raise ValueError("a group needs at least one member")
        updated = self._store.put({**group, "member_agent_ids": remaining})
        return updated["member_agent_ids"]

    def validate_members(self, agent_ids: list[str]) -> None:
        """Every member must exist and be kind=persistent (r4 §1: real bots only)."""
        for agent_id in agent_ids:
            if self._lookup is None:
                continue
            record = self._lookup.get(str(agent_id))
            if record is None:
                raise KeyError(f"agent not found: {agent_id}")
            if record.get("kind") != "persistent":
                raise ValueError(f"group members must be persistent agents: {agent_id}")

    def _require(self, group_id: str) -> dict[str, Any]:
        record = self.get(group_id)
        if record is None:
            raise KeyError(f"group not found: {group_id}")
        return record
