"""Persistent agents: profiles that can run unattended on a schedule/channel.

The service layer sits on the shared profile store (``data/profiles/*.toml``);
see ``store.py`` for the record shape. This package is the single home of the
``session_key`` lineage grammar shared by channels, heartbeat and groups.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from atlas.config import get_config
from atlas.persistent_agents.store import (
    AGENT_FIELDS,
    AGENT_KINDS,
    AGENT_STATUSES,
    BUILTIN_ROLE_IDS,
    HEARTBEAT_FIELDS,
    PERSISTENT_AGENT_FIELDS,
    PROFILE_FIELDS,
    PersistentAgentStore,
    default_agent_table,
    default_heartbeat_table,
    validate_heartbeat_table,
    validate_profile_record,
)

__all__ = [
    "AGENT_FIELDS",
    "AGENT_KINDS",
    "AGENT_STATUSES",
    "BUILTIN_ROLE_IDS",
    "HEARTBEAT_FIELDS",
    "PERSISTENT_AGENT_FIELDS",
    "PROFILE_FIELDS",
    "PersistentAgentService",
    "PersistentAgentStore",
    "default_agent_table",
    "default_heartbeat_table",
    "session_key",
    "validate_heartbeat_table",
    "validate_profile_record",
]


def _clean_component(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"session_key {name} must be a non-empty string")
    if ":" in value or value.strip() != value:
        raise ValueError(f"session_key {name} must not contain ':' or whitespace padding")
    return value


def session_key(
    agent_id: str, channel: str = "", account: str = "", peer: str = "", group: bool = False,
) -> str:
    """Build the Hermes session lineage key for one agent conversation.

    Grammar (ported from OpenClaw ``buildAgentPeerSessionKey``): ``agent:<id>:
    [channel:[account]:]kind:peer``. Scope follows r1 §1.4 — with no peer the
    agent's main session is addressed; dm scope widens main → per-peer →
    per-channel-peer → per-account-channel-peer as channel/account appear.
    Group sessions always carry ``group:<peer>`` (the room id).
    """
    parts = ["agent", _clean_component("agent_id", agent_id)]
    if group and not peer:
        raise ValueError("session_key group sessions require a peer (room id)")
    if channel:
        parts.append(_clean_component("channel", channel))
        if account:
            parts.append(_clean_component("account", account))
    elif account:
        raise ValueError("session_key account requires channel")
    if peer:
        parts.append("group" if group else "direct")
        parts.append(_clean_component("peer", peer))
    else:
        parts.append("main")
    return ":".join(parts)


def _now_stamp() -> str:
    return datetime.now(UTC).isoformat()


def _default_store() -> PersistentAgentStore:
    return PersistentAgentStore(get_config().db_path.parent)


class PersistentAgentService:
    """CRUD + runtime projection for persistent agents (and the shared roles)."""

    def __init__(self, store: PersistentAgentStore | None = None) -> None:
        self._store = store if store is not None else _default_store()
        self._store.ensure_seeded()
        # In-memory runtime overlay; durable projection is agent.last_status etc.
        self._runtime_status: dict[str, dict[str, str]] = {}

    # -- registry -----------------------------------------------------------

    def list_agents(self, include_roles: bool = False) -> list[dict[str, Any]]:
        records = [self._normalize(record) for record in self._store.list()]
        if include_roles:
            return records
        return [record for record in records if record.get("kind") == "persistent"]

    def get(self, agent_id: str) -> dict[str, Any] | None:
        record = self._store.get(agent_id)
        return self._normalize(record) if record is not None else None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        data.setdefault("kind", "persistent")
        return self._store.put(data)

    def update(self, agent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        old = self._require(agent_id)
        if agent_id in BUILTIN_ROLE_IDS and (patch.get("kind") == "persistent" or "agent" in patch):
            raise ValueError("built-in profiles cannot become persistent agents")
        merged = {**old, **patch, "id": agent_id, "created_at": old["created_at"]}
        if "agent" in patch or "agent" in old:
            merged["agent"] = _merge_agent_table(old.get("agent"), patch.get("agent"))
        return self._store.put(merged)

    def delete(self, agent_id: str) -> None:
        if agent_id in BUILTIN_ROLE_IDS:
            raise ValueError("built-in profiles cannot be deleted")
        if not self._store.delete(agent_id):
            raise KeyError(f"agent not found: {agent_id}")
        self._runtime_status.pop(agent_id, None)

    def set_enabled(self, agent_id: str, enabled: bool) -> dict[str, Any]:
        record = self._require_persistent(agent_id)
        agent = {**record["agent"], "enabled": bool(enabled)}
        if not enabled:
            # A disabled agent cannot hold a live status; project it offline.
            agent["last_status"] = "offline"
            self._runtime_status[agent_id] = {
                "status": "offline",
                "error": agent.get("last_error", ""),
                "updated_at": _now_stamp(),
            }
        return self._store.put({**record, "agent": agent})

    # -- runtime status projection -------------------------------------------

    def get_status(self, agent_id: str) -> dict[str, Any]:
        record = self._require_persistent(agent_id)
        agent = record["agent"]
        overlay = self._runtime_status.get(agent_id)
        return {
            "agent_id": agent_id,
            "status": (overlay or {}).get("status") or agent.get("last_status") or "offline",
            "error": (overlay or {}).get("error") or agent.get("last_error", ""),
            "last_activity_at": agent.get("last_activity_at", ""),
            "enabled": agent.get("enabled", True),
        }

    def set_status(self, agent_id: str, status: str, error: str | None = None) -> dict[str, Any]:
        record = self._require_persistent(agent_id)
        if status not in AGENT_STATUSES:
            raise ValueError("status must be idle, working, waiting_user or offline")
        message = error or ""
        self._runtime_status[agent_id] = {
            "status": status, "error": message, "updated_at": _now_stamp(),
        }
        agent = self._apply_status(record["agent"], status, message)
        return self._store.put({**record, "agent": agent})

    # -- run config ----------------------------------------------------------

    def resolve_agent_run_config(self, agent_id: str) -> dict[str, Any]:
        """Merge agent fields into the run.start config shape (server.py:6550)."""
        record = self._require_persistent(agent_id)
        tools = record.get("tools") or {}
        return {
            "profile_id": record["id"],
            "model": record.get("model"),
            "reasoning_effort": record.get("reasoning_effort"),
            "instructions": record.get("instructions", ""),
            "active_skills": list(record.get("active_skills", [])),
            "tools": {"allow": tools.get("allow"), "deny": list(tools.get("deny", []))},
            "mode": record.get("mode", "act"),
            "workspace": record["agent"].get("workspace") or None,
        }

    # -- heartbeat -----------------------------------------------------------

    def get_heartbeat(self, agent_id: str) -> dict[str, Any]:
        return dict(self._require_persistent(agent_id)["agent"]["heartbeat"])

    def set_heartbeat(self, agent_id: str, config: dict[str, Any]) -> dict[str, Any]:
        record = self._require_persistent(agent_id)
        merged = {**record["agent"]["heartbeat"], **(config or {})}
        heartbeat = validate_heartbeat_table(merged)
        agent = {**record["agent"], "heartbeat": heartbeat}
        return self._store.put({**record, "agent": agent})

    # -- channel bindings ----------------------------------------------------

    def list_channels(self, agent_id: str) -> list[dict[str, str]]:
        return [dict(row) for row in self._require_persistent(agent_id)["agent"]["channels"]]

    def add_channel(
        self, agent_id: str, channel: str, target: str, account: str = "",
        permission_mode: str | None = None, mention_names: list[str] | None = None,
    ) -> list[dict[str, str]]:
        record = self._require_persistent(agent_id)
        bindings = [dict(row) for row in record["agent"]["channels"]]
        binding = {"channel": channel, "target": target, "account": account}
        if permission_mode is not None:
            binding["permission_mode"] = permission_mode
        names = list(dict.fromkeys(str(name).strip().lstrip("@") for name in (mention_names or []) if str(name).strip().lstrip("@")))
        if names:
            binding["mention_names"] = names
        bindings.append(binding)
        agent = {**record["agent"], "channels": bindings}
        updated = self._store.put({**record, "agent": agent})
        return [dict(row) for row in updated["agent"]["channels"]]

    def remove_channel(
        self, agent_id: str, channel: str, target: str, account: str | None = None,
    ) -> list[dict[str, str]]:
        record = self._require_persistent(agent_id)
        kept = [
            dict(row) for row in record["agent"]["channels"]
            if not (row["channel"] == channel and row["target"] == target
                    and (account is None or row["account"] == account))
        ]
        if len(kept) == len(record["agent"]["channels"]):
            raise KeyError(f"channel binding not found: {channel}:{target}")
        agent = {**record["agent"], "channels": kept}
        updated = self._store.put({**record, "agent": agent})
        return [dict(row) for row in updated["agent"]["channels"]]

    # -- internals -----------------------------------------------------------

    def _require(self, agent_id: str) -> dict[str, Any]:
        record = self.get(agent_id)
        if record is None:
            raise KeyError(f"agent not found: {agent_id}")
        return record

    def _require_persistent(self, agent_id: str) -> dict[str, Any]:
        record = self._require(agent_id)
        if record.get("kind") != "persistent":
            raise KeyError(f"not a persistent agent: {agent_id}")
        return record

    @staticmethod
    def _normalize(record: dict[str, Any]) -> dict[str, Any]:
        # Records written through the legacy /api/profiles whitelist carry no kind.
        normalized = {**record, "kind": record.get("kind") or "role"}
        if normalized["kind"] == "persistent":
            normalized.setdefault("agent", default_agent_table())
        else:
            normalized.pop("agent", None)
        return normalized

    @staticmethod
    def _apply_status(agent: dict[str, Any], status: str, error: str) -> dict[str, Any]:
        return {
            **agent,
            "last_status": status,
            "last_error": error,
            "last_activity_at": _now_stamp(),
        }


def _merge_agent_table(
    old: dict[str, Any] | None, patch: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deep-merge the agent table so partial PATCHes never erase siblings."""
    base = dict(old or default_agent_table())
    if not patch:
        return base
    merged = {**base, **patch}
    if "heartbeat" in patch or "heartbeat" in base:
        merged["heartbeat"] = {**(base.get("heartbeat") or {}), **(patch.get("heartbeat") or {})}
    return merged
