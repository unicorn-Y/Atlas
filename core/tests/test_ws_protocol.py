"""The run WebSocket needs a contract, not an if/elif chain.

An unknown message type used to be silently ignored and a missing field surfaced
later as a KeyError inside a handler, far from the frame that caused it. The
protocol is now data: each accepted frame declares its required and optional
fields, `validate` names what is wrong, and the router answers with a
`protocol.error` frame instead of dropping the message.
"""

from __future__ import annotations

import pytest

from atlas.api.ws_protocol import (
    INBOUND,
    PROTOCOL_VERSION,
    describe,
    unknown_message_types,
    validate,
)

pytestmark = pytest.mark.unit


def test_protocol_version_is_declared():
    assert PROTOCOL_VERSION >= 2


def test_every_router_message_type_is_described():
    """The nine types the router dispatches on must all be in the contract."""
    expected = {"run.start", "resume", "rules.trust", "run.cancel", "run.steer",
                "run.plan.approve", "approval.response", "input.response",
                "subtask.message"}
    assert set(unknown_message_types()) == expected


def test_valid_frame_passes_through_unchanged():
    payload, error = validate({"type": "run.cancel", "run_id": "r1"})
    assert error is None
    assert payload == {"type": "run.cancel", "run_id": "r1"}


def test_missing_required_field_names_the_field():
    payload, error = validate({"type": "run.start", "run_id": "r1"})
    assert payload is None
    # The first required field that is absent is the one reported.
    assert "conversation_id" in error and "run.start" in error


def test_unknown_type_lists_the_known_ones():
    payload, error = validate({"type": "run.teleport"})
    assert payload is None
    assert "run.teleport" in error
    assert "run.start" in error, "the error must tell a client what it can send"


def test_enum_field_is_enforced():
    _, error = validate({"type": "run.plan.approve", "run_id": "r1", "action": "maybe"})
    assert error is not None and "action" in error
    payload, error = validate({"type": "run.plan.approve", "run_id": "r1", "action": "approve"})
    assert error is None and payload["action"] == "approve"


def test_non_object_frame_is_refused():
    _, error = validate(["not", "an", "object"])
    assert error == "frame must be a JSON object"


def test_frame_without_a_type_is_refused():
    _, error = validate({"run_id": "r1"})
    assert "type" in error


def test_describe_is_serialisable_and_matches_the_contract():
    described = describe()
    assert len(described) == len(INBOUND)
    assert all({"type", "required", "optional", "enums"} <= set(d) for d in described)
