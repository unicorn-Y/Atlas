"""Atlas user-local time helpers.

Timezone selection is centralized so model prompts, reminders, and memory
queries interpret calendar dates with the same IANA rules. ``now_utc`` is the
shared current-time seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone_name

__all__ = [
    "attach_user_timezone",
    "now_local",
    "now_utc",
    "resolve_user_timezone",
    "timezone_name",
]


def _effective_config(config: Any = None) -> Any:
    if config is not None:
        return config
    from atlas.config import get_config

    return get_config()


def _configured_timezone(config: Any) -> str | None:
    value = None
    getter = getattr(config, "get", None)
    if callable(getter):
        value = getter("user.timezone")
    if value is None and isinstance(config, Mapping):
        user = config.get("user")
        if isinstance(user, Mapping):
            value = user.get("timezone")
    normalized = str(value or "").strip()
    return normalized or None


def resolve_user_timezone(config: Any = None) -> ZoneInfo:
    """Return the configured IANA timezone, falling back to the OS timezone.

    ``tzlocal`` maps Windows timezone registry identifiers (for example,
    ``China Standard Time``) to IANA names. Returning ``ZoneInfo`` preserves
    historical and future DST rules; the fallback is never a fixed offset.
    """
    effective = _effective_config(config)
    configured = _configured_timezone(effective)
    name = configured or get_localzone_name()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        source = "user.timezone" if configured else "system timezone"
        raise ValueError(f"{source} is not a valid IANA timezone: {name!r}") from exc


def timezone_name(config: Any = None) -> str:
    """Return the selected IANA timezone key."""
    return resolve_user_timezone(config).key


def now_utc() -> datetime:
    """Current aware UTC instant; kept as the shared current-time seam."""
    return datetime.now(UTC)


def attach_user_timezone(value: datetime, config: Any = None) -> datetime:
    """Interpret a naive wall time in the user's zone or convert an aware time.

    Nonexistent wall times in a DST spring gap are rejected. If a wall time is
    repeated during a fall transition, the first occurrence is selected.
    """
    zone = resolve_user_timezone(config)
    if value.tzinfo is not None:
        source_zone = value.tzinfo
        normalized = value.astimezone(UTC).astimezone(source_zone)
        if (normalized.replace(tzinfo=None) != value.replace(tzinfo=None)
                or normalized.utcoffset() != value.utcoffset()):
            raise ValueError(
                f"aware local time {value.isoformat(sep=' ')} is invalid in "
                f"{getattr(source_zone, 'key', source_zone)}"
            )
        return value.astimezone(zone)

    first = value.replace(tzinfo=zone, fold=0)
    first_roundtrip = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if first_roundtrip == value:
        return first

    second = value.replace(tzinfo=zone, fold=1)
    second_roundtrip = second.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if second_roundtrip == value:
        return second
    raise ValueError(
        f"local time {value.isoformat(sep=' ')} does not exist in {zone.key}"
    )


def now_local(config: Any = None, *, now: datetime | None = None) -> datetime:
    """Return the current instant in the user's timezone.

    The optional ``now`` supports deterministic tests. Naive values are
    interpreted as local wall times to preserve reminder-helper compatibility.
    """
    reference = now if now is not None else now_utc()
    return attach_user_timezone(reference, config)
