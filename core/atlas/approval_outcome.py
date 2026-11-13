"""Approval outcomes, normalised to one closed vocabulary.

The kernel used to ask one question in seven places — ``result == "allow"`` —
which collapsed four genuinely different facts into "not allow":

* the user said no            -> the model should stop asking for this
* the user never answered     -> a timeout, not a refusal; retrying is reasonable
* there was no way to ask     -> a wiring/config problem, not a policy decision
* the call was cancelled      -> the run is going away

A model that cannot tell these apart reacts wrongly to all of them: it treats a
timeout as a refusal and gives up, or retries against an explicit "no". DSH
models this as a closed outcome set (``allowed-once`` / ``rejected`` /
``cancelled`` / ``unavailable``) with a distinct model-facing reason per value;
this module is the Atlas equivalent, kept presentation-neutral so each call site
can word its own message.
"""

from __future__ import annotations

from typing import Any, Final

#: The only grant. Nothing here is "always": a standing grant is a separate,
#: user-managed record (``atlas.approval_policy``), never an approval answer.
ALLOWED: Final[str] = "allowed-once"
REJECTED: Final[str] = "rejected"
CANCELLED: Final[str] = "cancelled"
UNAVAILABLE: Final[str] = "unavailable"

OUTCOMES: Final[frozenset[str]] = frozenset({ALLOWED, REJECTED, CANCELLED, UNAVAILABLE})

#: Values a UI/transport may send back. Anything unrecognised is treated as
#: ``rejected``: an approval path must fail closed, and silently reinterpreting
#: an unknown string as consent is the one failure this module exists to stop.
_ALLOWING: Final[frozenset[str]] = frozenset({
    "allow", "allowed", "allowed-once", "allow_once", "approve", "approved",
    "yes", "true", "always", "allow_always",
})
_REJECTING: Final[frozenset[str]] = frozenset({
    "deny", "denied", "reject", "rejected", "no", "false", "block",
})
_CANCELLING: Final[frozenset[str]] = frozenset({
    "cancel", "cancelled", "canceled", "aborted", "interrupted",
})
_UNAVAILABLE_MARKERS: Final[frozenset[str]] = frozenset({
    "unavailable", "no_channel", "no-channel", "not_available", "unsupported",
})


def normalize(value: Any) -> str:
    """Map any answer this codebase can receive onto one of :data:`OUTCOMES`.

    ``None`` means the question was never answered (timeout or a missing
    channel), which is *not* a refusal and must stay distinguishable from one.
    """
    if value is None:
        return UNAVAILABLE
    if isinstance(value, bool):
        return ALLOWED if value else REJECTED
    text = str(value).strip().lower()
    if not text:
        return UNAVAILABLE
    if text in _ALLOWING:
        return ALLOWED
    if text in _REJECTING:
        return REJECTED
    if text in _CANCELLING:
        return CANCELLED
    if text in _UNAVAILABLE_MARKERS:
        return UNAVAILABLE
    # Fail closed on anything else, but do not pretend a human said no: an
    # unrecognised answer means the answer could not be understood, which is a
    # transport problem and must not be reported back to the model as a refusal.
    return UNAVAILABLE


def is_allowed(value: Any) -> bool:
    return normalize(value) == ALLOWED


def denial_reason(outcome: str, *, tool: str = "The tool call") -> str:
    """A model-facing sentence that says what actually happened.

    The distinction matters to the model's next move: a ``rejected`` means stop
    asking, ``cancelled`` means the run is ending, and ``unavailable`` means the
    request never reached a human — the last one is often worth retrying after
    the channel is restored, so it must not read as a policy refusal.
    """
    if outcome == ALLOWED:
        return ""
    if outcome == CANCELLED:
        return f"{tool} was cancelled before it was approved; do not retry it in this run."
    if outcome == UNAVAILABLE:
        return (
            f"{tool} needs approval, but no approval channel was available. "
            "Do not assume it was refused; it was never shown to the user."
        )
    return f"{tool} was rejected by the user. Do not retry it; continue with what is available."