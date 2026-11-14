"""A typed description of the run WebSocket protocol.

`runtime_ws_router` dispatches on a bare `if msg_type == ...` chain, so a client
that sends the wrong shape learns nothing: an unknown type is silently ignored
and a missing field surfaces later as a `KeyError` inside a handler, far from the
message that caused it.

This module is the contract those handlers never had. Each inbound message is
described once — required fields, optional fields, and whether an unknown field
is a mistake — and `validate()` turns a frame into either a typed payload or a
reason a client can act on.

It deliberately does not replace the handlers: the router keeps its own dispatch
and calls `validate()` first, so the wire format and the behaviour stay in one
place while the shape gains a name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

__all__ = [
    "InboundMessage",
    "INBOUND",
    "PROTOCOL_VERSION",
    "unknown_message_types",
    "validate",
]

#: Bumped when a required field or a message type changes meaning. Clients can
#: read it from ``/api/health`` and refuse to talk to a build they do not know.
PROTOCOL_VERSION = 2


@dataclass(frozen=True)
class InboundMessage:
    """One accepted client frame."""

    type: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    #: A field that must be one of a closed set.
    enums: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Reject fields this message does not declare. Off by default: a client may
    #: be newer than the server, and dropping extra fields is friendlier than
    #: refusing the whole frame.
    strict: bool = False


#: Every frame the router accepts. Kept as data so the router, a test, and a
#: client generator all read the same list.
INBOUND: tuple[InboundMessage, ...] = (
    InboundMessage("run.start", required=("run_id", "conversation_id", "content"),
                   optional=("workspace", "model", "reasoning_effort", "mode",
                             "permission_mode", "agent_preset_id", "images",
                             "documents", "read_only", "sandbox_permissions")),
    InboundMessage("resume", required=("run_id",),
                   optional=("after_sequence", "conversation_id")),
    InboundMessage("rules.trust", required=("event_id",),
                   optional=("approve", "scope", "rules")),
    InboundMessage("run.cancel", required=("run_id",)),
    InboundMessage("run.steer", required=("run_id", "content"),
                   optional=("immediate", "send_now", "yield_requested", "lane")),
    InboundMessage("run.plan.approve", required=("run_id", "action"),
                   optional=("feedback", "plan"),
                   enums={"action": ("approve", "reject", "edit")}),
    InboundMessage("approval.response", required=("event_id", "choice"),
                   optional=("reason", "scope", "permission_scope")),
    InboundMessage("input.response", required=("event_id",),
                   optional=("value", "answers")),
    InboundMessage("subtask.message", required=("subtask_id", "content"),
                   optional=("run_id",)),
)

_BY_TYPE: dict[str, InboundMessage] = {m.type: m for m in INBOUND}


def unknown_message_types() -> tuple[str, ...]:
    return tuple(m.type for m in INBOUND)


def validate(frame: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(payload, error)``; exactly one is ``None``.

    The error names the message type and the offending field, because "bad
    request" is what a client cannot debug.
    """
    if not isinstance(frame, Mapping):
        return None, "frame must be a JSON object"
    msg_type = frame.get("type")
    if not isinstance(msg_type, str) or not msg_type:
        return None, "frame is missing a string 'type'"
    spec = _BY_TYPE.get(msg_type)
    if spec is None:
        known = ", ".join(sorted(_BY_TYPE))
        return None, f"unknown message type {msg_type!r}; known types: {known}"

    payload = dict(frame)
    for name in spec.required:
        if payload.get(name) is None:
            return None, f"{msg_type}: missing required field {name!r}"
    for name, allowed in spec.enums.items():
        value = payload.get(name)
        if value is not None and value not in allowed:
            return None, (
                f"{msg_type}: field {name!r} must be one of {sorted(allowed)}, "
                f"got {value!r}"
            )
    if spec.strict:
        declared = {"type", *spec.required, *spec.optional, *spec.enums}
        extra = sorted(set(payload) - declared)
        if extra:
            return None, f"{msg_type}: unknown fields {extra}"
    return payload, None


def describe() -> list[dict[str, Any]]:
    """The protocol as JSON-serialisable data, for a client or a doc page."""
    return [
        {
            "type": spec.type,
            "required": list(spec.required),
            "optional": list(spec.optional),
            "enums": {k: list(v) for k, v in spec.enums.items()},
        }
        for spec in INBOUND
    ]
