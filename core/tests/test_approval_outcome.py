"""Approval answers collapse into four outcomes, and only one of them is consent.

The kernel used to compare against the single string ``"allow"`` in seven places.
That conflated a user refusal with a timeout and with a missing approval channel,
so a model told "not approved" could not tell whether to stop asking, retry, or
report a wiring problem. These tests pin the closed vocabulary and the
fail-closed default: an answer this code does not recognise must never read as
consent.
"""

from __future__ import annotations

import pytest

from atlas.approval_outcome import (
    ALLOWED,
    CANCELLED,
    OUTCOMES,
    REJECTED,
    UNAVAILABLE,
    denial_reason,
    is_allowed,
    normalize,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", ["allow", "allowed", "allow_once", "approve", "yes", True])
def test_recognised_consent_forms_all_normalize_to_allowed(value):
    assert normalize(value) == ALLOWED
    assert is_allowed(value) is True


@pytest.mark.parametrize("value", ["deny", "rejected", "no", False, "block"])
def test_recognised_refusals_normalize_to_rejected(value):
    assert normalize(value) == REJECTED


@pytest.mark.parametrize("value", ["cancel", "cancelled", "aborted"])
def test_cancellation_is_its_own_outcome(value):
    assert normalize(value) == CANCELLED


def test_missing_answer_is_unavailable_not_a_refusal():
    """A timeout or an absent channel must not be recorded as "the user said no"."""
    assert normalize(None) == UNAVAILABLE
    assert normalize("") == UNAVAILABLE


def test_unknown_string_fails_closed_but_does_not_claim_a_human_refusal():
    """An unparseable answer is a transport problem, not a person saying no.

    Calling it ``rejected`` would tell the model "the user refused" about an
    answer nobody could read, and the model would then stop asking for the rest
    of the run on the strength of a lie.
    """
    assert normalize("maybe-later") == UNAVAILABLE
    assert normalize("ALLOW_ALL_THE_THINGS") == UNAVAILABLE
    assert is_allowed("maybe-later") is False


def test_every_result_is_inside_the_closed_set():
    for value in [None, "", "allow", "deny", "cancel", "unavailable", "nonsense", True, False, 1]:
        assert normalize(value) in OUTCOMES


def test_allowed_has_no_model_facing_denial_text():
    assert denial_reason(ALLOWED) == ""


def test_each_denial_outcome_explains_a_different_next_move():
    rejected = denial_reason(REJECTED, tool="Write")
    cancelled = denial_reason(CANCELLED, tool="Write")
    unavailable = denial_reason(UNAVAILABLE, tool="Write")

    assert "rejected" in rejected and "Do not retry" in rejected
    assert "cancelled" in cancelled
    assert "no approval channel" in unavailable
    assert "never shown to the user" in unavailable
    # The three texts must actually differ; identical wording is how the
    # original bug looked from the model's side.
    assert len({rejected, cancelled, unavailable}) == 3


def test_only_a_positive_answer_is_consent():
    """Exhaustive guard: nothing but an allow form may return True."""
    for value in [None, "", "deny", "cancel", "unavailable", "maybe", False, 0]:
        assert is_allowed(value) is False
