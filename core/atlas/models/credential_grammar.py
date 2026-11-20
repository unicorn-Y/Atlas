"""Credential reference and API-key grammar.

Ported from DSH ``packages/credentials/credentials`` (master ``2e39e704``).

Two different things live here:

* a **credential reference** is an environment-variable name (``MY_API_KEY``)
  stored in configuration instead of the secret itself;
* a **credential key** is a ``<scope>/<id>`` address for a stored record.

An API key has a third, transport-level rule: it must survive being placed in
an HTTP header.  DSH rejects everything outside printable ASCII except space;
we do the same, and additionally return the trimmed value so callers never
store accidental padding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ApiKeyVerdict",
    "normalize_api_key",
    "require_api_key",
    "redact_api_key",
    "credential_ref",
    "is_credential_ref_name",
    "is_credential_key_segment",
    "credential_key",
    "parse_credential_key",
    "credential_key_scope",
    "credential_key_id",
]

REF_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KEY_SEGMENT_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
#: Printable ASCII except space.  Latin-1 is excluded on purpose: a header could
#: carry it, but no provider issues such a key, and admitting it turns an
#: explained local refusal into an opaque upstream 401.
LEGAL_API_KEY = re.compile(r"^[\x21-\x7E]+$")


@dataclass(frozen=True)
class ApiKeyVerdict:
    """Outcome of :func:`normalize_api_key`; never carries the key in ``reason``."""

    ok: bool
    value: str = ""
    reason: str | None = None


def normalize_api_key(raw: object) -> ApiKeyVerdict:
    """Trim and judge one supplied API key.

    Absence is not this function's business: a caller decides whether a value
    was supplied at all (a profile may authenticate through ambient discovery
    or OAuth).  A key that is present but empty is reported as ``empty`` so the
    caller can distinguish "not configured" from "configured as blank".
    """
    if not isinstance(raw, str):
        return ApiKeyVerdict(False, reason="not_a_string")
    value = raw.strip()
    if not value:
        return ApiKeyVerdict(False, reason="empty")
    if not LEGAL_API_KEY.fullmatch(value):
        return ApiKeyVerdict(False, reason="illegal_characters")
    return ApiKeyVerdict(True, value=value)


def require_api_key(raw: object) -> str:
    """Return the trimmed key or raise ``ValueError`` without echoing it."""
    verdict = normalize_api_key(raw)
    if not verdict.ok:
        raise ValueError(f"invalid API key: {verdict.reason}")
    return verdict.value


def redact_api_key(value: object, *, keep: int = 4) -> str:
    """A short, log-safe fingerprint: first/last ``keep`` characters only."""
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned:
        return ""
    if len(cleaned) <= keep * 2:
        return "***"
    return f"{cleaned[:keep]}…{cleaned[-keep:]}"


def credential_ref(value: object) -> str:
    """Validate and return an environment-variable reference name."""
    if not isinstance(value, str) or not REF_PATTERN.fullmatch(value):
        raise TypeError(f"credential ref {value!r} must match {REF_PATTERN.pattern}")
    return value


def is_credential_ref_name(value: object) -> bool:
    """Whether *value* could name a reference at all (no exception on garbage)."""
    return isinstance(value, str) and bool(REF_PATTERN.fullmatch(value))


def is_credential_key_segment(value: object) -> bool:
    """Whether *value* is a valid scope or id segment."""
    return isinstance(value, str) and bool(KEY_SEGMENT_PATTERN.fullmatch(value))


def credential_key(scope: object, key_id: object) -> str:
    """Validate and join a ``<scope>/<id>`` credential address."""
    for segment in (scope, key_id):
        if not is_credential_key_segment(segment):
            raise TypeError(
                f"credential key segment {segment!r} must match {KEY_SEGMENT_PATTERN.pattern}"
            )
    return f"{scope}/{key_id}"


def parse_credential_key(value: object) -> str:
    """Parse an already-joined ``<scope>/<id>`` key and re-validate it."""
    if not isinstance(value, str):
        raise TypeError(f"credential key {value!r} must be a string")
    segments = value.split("/")
    if len(segments) != 2:
        raise TypeError(f'credential key "{value}" must be "<scope>/<id>"')
    return credential_key(segments[0], segments[1])


def credential_key_scope(key: str) -> str:
    """The owning plugin/scope half of a key."""
    return key.split("/", 1)[0]


def credential_key_id(key: str) -> str:
    """The owning plugin's own addressing unit."""
    return key.split("/", 1)[1]