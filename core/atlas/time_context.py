"""Atlas user-local time helpers.

Timezone selection is centralized so model prompts, reminders, and memory
queries interpret calendar dates with the same IANA rules. ``now_utc`` is the
shared current-time seam.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone_name

__all__ = [
    "attach_user_timezone",
    "now_local",
    "now_utc",
    "resolve_gated_test_clock",
    "resolve_source_event_test_clock",
    "resolve_user_timezone",
    "test_clock_context",
    "timezone_name",
]


_TEST_CLOCK_UTC: ContextVar[datetime | None] = ContextVar(
    "atlas_test_clock_utc", default=None,
)


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
    """Current aware UTC instant, or this request's gated test instant."""
    return _TEST_CLOCK_UTC.get() or datetime.now(UTC)


def resolve_gated_test_clock(value: Any, config: Any = None, *,
                             event_class: str | None = None) -> datetime | None:
    """Normalize a permitted test clock as an aware user-local datetime.

    ``resolve_test_clock`` remains the gate authority (TEST event class plus an
    isolated Atlas data root). ``event_class`` lets durable background work also
    prove that the specific source event was TEST. Naive values are interpreted
    as user-local wall times, matching reminder and observation semantics.
    """
    if event_class is not None and str(event_class).upper() != "TEST":
        return None
    from atlas.memory.test_clock import resolve_test_clock

    accepted = resolve_test_clock(value)
    if accepted is None:
        return None
    try:
        parsed = datetime.fromisoformat(accepted)
    except (TypeError, ValueError):
        return None
    try:
        return attach_user_timezone(parsed, config)
    except ValueError:
        # Invalid local wall times (for example a DST gap) are not effective
        # test clocks. They must not abort an otherwise valid run.
        return None


@contextmanager
def test_clock_context(value: Any, config: Any = None, *,
                       event_class: str | None = None) -> Iterator[datetime | None]:
    """Scope a gated test instant and always restore the caller's clock.

    An invalid or production scope explicitly masks any inherited test clock;
    this prevents a nested production operation from accidentally reusing an
    outer test context.
    """
    local = resolve_gated_test_clock(value, config, event_class=event_class)
    token = _TEST_CLOCK_UTC.set(local.astimezone(UTC) if local is not None else None)
    try:
        yield local
    finally:
        _TEST_CLOCK_UTC.reset(token)


def resolve_source_event_test_clock(events: list[dict[str, Any]],
                                    config: Any = None) -> datetime | None:
    """Pick the latest backed source time only when every source is TEST.

    This is for durable background work whose request ContextVar was not
    inherited. Mixed, incomplete, conflicting, or invalid source metadata
    deliberately falls back to the real clock.
    """
    if not events:
        return None
    unique: dict[str, tuple[datetime, str, str]] = {}
    for event in events:
        if not isinstance(event, dict) or str(event.get("event_class") or "").upper() != "TEST":
            return None
        source_id = str(event.get("source_event_id") or "").strip()
        occurred_at = str(event.get("occurred_at") or "").strip()
        source_timezone = str(event.get("source_timezone") or "").strip()
        if not source_id or not occurred_at or not source_timezone:
            return None
        try:
            ZoneInfo(source_timezone)
            parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            local = attach_user_timezone(parsed, config)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            return None
        value = (local, source_timezone, occurred_at)
        previous = unique.get(source_id)
        if previous is not None and previous != value:
            return None
        unique[source_id] = value
    latest = max(unique.values(), key=lambda item: item[0].astimezone(UTC))[0]
    return resolve_gated_test_clock(latest.isoformat(), config, event_class="TEST")


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
