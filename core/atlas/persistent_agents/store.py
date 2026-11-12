"""Persistent-agent profile records on top of the existing profile store.

Persistent agents are AgentProfile records (``data/profiles/*.toml``) extended
with a ``kind`` discriminator and an ``agent`` sub-table. There is exactly one
storage location for agents: the TomlRecordStore the server already seeds with
the built-in roles. This module owns the extended field whitelist and record
validation; the server profile whitelist will be pointed at
``PERSISTENT_AGENT_FIELDS`` during integration.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from atlas.task_artifacts import TomlRecordStore, seed_profiles

# Top-level profile fields kept from the existing server whitelist.
PROFILE_FIELDS: frozenset[str] = frozenset({
    "id", "name", "description", "model", "reasoning_effort", "instructions",
    "active_skills", "tools", "mode", "created_at", "updated_at",
})

# Fields of the agent sub-table (persistent runtime configuration + projections).
AGENT_FIELDS: frozenset[str] = frozenset({
    "enabled", "workspace", "heartbeat", "channels", "automations",
    "device_preference", "browser_profile", "last_status", "last_activity_at", "last_error",
    "permission_mode",
})

HEARTBEAT_FIELDS: frozenset[str] = frozenset({
    "enabled", "interval_minutes", "active_hours", "prompt", "delivery", "isolated_session",
})

# Full whitelist for profile records: legacy fields + persistent-agent extension.
PERSISTENT_AGENT_FIELDS: frozenset[str] = PROFILE_FIELDS | {"kind", "agent"}

AGENT_KINDS: frozenset[str] = frozenset({"role", "persistent"})
AGENT_STATUSES: frozenset[str] = frozenset({"idle", "working", "waiting_user", "offline"})

BUILTIN_ROLE_IDS: frozenset[str] = frozenset({"default", "architect", "reviewer"})

_CHANNEL_BINDING_KEYS: frozenset[str] = frozenset({
    "channel", "target", "account", "permission_mode",
})

_ACTIVE_HOURS_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")
_DELIVERY_RE = re.compile(r"^[^:\s]+:[^:\s]+$")


class PersistentAgentStore(TomlRecordStore):
    """Profile store that validates the extended persistent-agent record shape."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, "profiles")

    def put(self, value: dict[str, Any]) -> dict[str, Any]:  # noqa: D102
        return super().put(validate_profile_record(value))

    def ensure_seeded(self) -> None:
        seed_profiles(self)


def default_agent_table() -> dict[str, Any]:
    return {
        "enabled": True,
        "workspace": "",
        "heartbeat": default_heartbeat_table(),
        "channels": [],
        "automations": [],
        "device_preference": "",
        "browser_profile": "",
        "last_status": "offline",
        "last_activity_at": "",
        "last_error": "",
    }


def default_heartbeat_table() -> dict[str, Any]:
    return {
        "enabled": False,
        "interval_minutes": 30,
        "active_hours": "",
        "prompt": "",
        "delivery": "owner",
        "isolated_session": True,
    }


def validate_profile_record(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize a profile record; raises ValueError on unknown/invalid fields.

    Built-in roles are forced to ``kind="role"`` and never carry an agent table.
    """
    unknown = set(value) - PERSISTENT_AGENT_FIELDS
    if unknown:
        raise ValueError(f"profile contains unsupported fields: {sorted(unknown)}")
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        raise ValueError("name is required")
    if value.get("mode", "act") not in {"act", "plan"}:
        raise ValueError("mode must be 'act' or 'plan'")
    if value.get("reasoning_effort") not in {None, "off", "minimal", "low", "medium", "high"}:
        raise ValueError("invalid reasoning_effort")
    tools = value.get("tools", {"allow": None, "deny": []})
    tools_ok = isinstance(tools, dict) and (
        tools.get("allow") is None or isinstance(tools.get("allow"), list)
    )
    if not tools_ok:
        raise ValueError("tools.allow must be a list or null")
    if not isinstance(tools.get("deny", []), list):
        raise ValueError("tools.deny must be a list")
    tools = {"allow": tools.get("allow"), "deny": tools.get("deny", [])}
    if any(not isinstance(item, str) for item in (tools["allow"] or []) + tools["deny"]):
        raise ValueError("tool names must be strings")
    if not isinstance(value.get("active_skills", []), list) or any(
        not isinstance(item, str) for item in value.get("active_skills", [])
    ):
        raise ValueError("active_skills must be a list of strings")
    if value.get("model") is not None and not isinstance(value.get("model"), str):
        raise ValueError("model must be a string")
    strings_ok = (
        isinstance(value.get("description", ""), str)
        and isinstance(value.get("instructions", ""), str)
    )
    if not strings_ok:
        raise ValueError("description and instructions must be strings")

    kind = value.get("kind") or "role"
    if kind not in AGENT_KINDS:
        raise ValueError("kind must be 'role' or 'persistent'")
    record_id = str(value.get("id", ""))
    if record_id in BUILTIN_ROLE_IDS:
        kind = "role"
    agent: dict[str, Any] | None = None
    if kind == "persistent":
        agent = _validate_agent_table(value.get("agent") or {})

    record: dict[str, Any] = {
        **value,
        "description": value.get("description", ""),
        "instructions": value.get("instructions", ""),
        "active_skills": list(value.get("active_skills", [])),
        "tools": tools,
        "mode": value.get("mode", "act"),
        "kind": kind,
    }
    if agent is not None:
        record["agent"] = agent
    else:
        record.pop("agent", None)
    return record


def _validate_agent_table(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("agent must be a table")
    unknown = set(value) - AGENT_FIELDS
    if unknown:
        raise ValueError(f"agent contains unsupported fields: {sorted(unknown)}")
    defaults = default_agent_table()
    if "enabled" in value and not isinstance(value["enabled"], bool):
        raise ValueError("agent.enabled must be a boolean")
    for key in ("workspace", "device_preference", "browser_profile"):
        if key in value and not isinstance(value[key], str):
            raise ValueError(f"agent.{key} must be a string")
    if "last_status" in value and value["last_status"] not in AGENT_STATUSES:
        raise ValueError("agent.last_status must be idle, working, waiting_user or offline")
    for key in ("last_activity_at", "last_error"):
        if key in value and not isinstance(value[key], str):
            raise ValueError(f"agent.{key} must be a string")
    if "automations" in value and (
        not isinstance(value["automations"], list)
        or any(not isinstance(item, str) for item in value["automations"])
    ):
        raise ValueError("agent.automations must be a list of strings")
    agent = {
        **defaults,
        "enabled": value.get("enabled", defaults["enabled"]),
        "workspace": value.get("workspace", defaults["workspace"]),
        "device_preference": value.get("device_preference", defaults["device_preference"]),
        "browser_profile": value.get("browser_profile", defaults["browser_profile"]),
        "last_status": value.get("last_status", defaults["last_status"]),
        "last_activity_at": value.get("last_activity_at", defaults["last_activity_at"]),
        "last_error": value.get("last_error", defaults["last_error"]),
        "automations": list(value.get("automations", [])),
        "heartbeat": validate_heartbeat_table(value.get("heartbeat") or {}),
        "channels": _validate_channels(value.get("channels", [])),
    }
    if "permission_mode" in value:
        from atlas.channels.routing import validate_permission_mode

        agent["permission_mode"] = validate_permission_mode(value["permission_mode"])
    return agent


def validate_heartbeat_table(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("agent.heartbeat must be a table")
    unknown = set(value) - HEARTBEAT_FIELDS
    if unknown:
        raise ValueError(f"agent.heartbeat contains unsupported fields: {sorted(unknown)}")
    defaults = default_heartbeat_table()
    if "enabled" in value and not isinstance(value["enabled"], bool):
        raise ValueError("agent.heartbeat.enabled must be a boolean")
    if "isolated_session" in value and not isinstance(value["isolated_session"], bool):
        raise ValueError("agent.heartbeat.isolated_session must be a boolean")
    interval = value.get("interval_minutes", defaults["interval_minutes"])
    if not isinstance(interval, int) or isinstance(interval, bool) or interval <= 0:
        raise ValueError("agent.heartbeat.interval_minutes must be a positive integer")
    active_hours = value.get("active_hours", defaults["active_hours"])
    _validate_active_hours(active_hours)
    prompt = value.get("prompt", defaults["prompt"])
    if not isinstance(prompt, str):
        raise ValueError("agent.heartbeat.prompt must be a string")
    delivery = value.get("delivery", defaults["delivery"])
    if not isinstance(delivery, str) or not (
        delivery in {"owner", "none"} or _DELIVERY_RE.fullmatch(delivery)
    ):
        raise ValueError("agent.heartbeat.delivery must be 'owner', 'none' or '<channel:target>'")
    return {
        "enabled": value.get("enabled", defaults["enabled"]),
        "interval_minutes": interval,
        "active_hours": active_hours,
        "prompt": prompt,
        "delivery": delivery,
        "isolated_session": value.get("isolated_session", defaults["isolated_session"]),
    }


def _validate_active_hours(active_hours: Any) -> None:
    if not isinstance(active_hours, str):
        raise ValueError("agent.heartbeat.active_hours must be a string")
    if not active_hours:
        return
    match = _ACTIVE_HOURS_RE.fullmatch(active_hours)
    if match is None:
        raise ValueError("agent.heartbeat.active_hours must be 'HH:MM-HH:MM' or empty")
    hours = [int(part) for part in match.groups()]
    if any(h > 23 for h in (hours[0], hours[2])) or any(m > 59 for m in (hours[1], hours[3])):
        raise ValueError("agent.heartbeat.active_hours contains an invalid time")


def _validate_channels(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("agent.channels must be a list")
    bindings: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in value:
        if not isinstance(row, dict) or set(row) - _CHANNEL_BINDING_KEYS:
            raise ValueError("channel binding must be a table with channel/target/account")
        channel = row.get("channel", "")
        target = row.get("target", "")
        account = row.get("account", "")
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError("channel binding requires a channel name")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("channel binding requires a target")
        if not isinstance(account, str):
            raise ValueError("channel binding account must be a string")
        key = (channel, target, account)
        if key in seen:
            continue
        seen.add(key)
        binding = {"channel": channel, "target": target, "account": account}
        if "permission_mode" in row:
            from atlas.channels.routing import validate_permission_mode

            binding["permission_mode"] = validate_permission_mode(row["permission_mode"])
        bindings.append(binding)
    return bindings
