"""Typed pointers to canonical SessionDB messages.

The transcript itself remains exclusively in SessionDB.  This value object is
safe to persist in Markdown metadata because it contains identifiers and
verification hints only, never message content.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Stable pointer whose identity is the pair (conversation_id, message_uid)."""

    conversation_id: str
    message_uid: str
    tool_call_id: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    content_hash: str | None = None
    observed_role: str | None = None
    observed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.conversation_id.strip() or not self.message_uid.strip():
            raise ValueError("conversation_id and message_uid are required")
        if (self.span_start is None) != (self.span_end is None):
            raise ValueError("span_start and span_end must be supplied together")
        if self.span_start is not None and (self.span_start < 0 or self.span_end < self.span_start):
            raise ValueError("invalid source span")

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready metadata, omitting unset optional values."""
        return {key: value for key, value in asdict(self).items() if value is not None}

    def to_ref(self) -> str:
        """Return the stable, URL-encoded ``atlas://source/v1`` tool reference."""
        return "atlas://source/v1?" + urlencode(self.to_dict())

    @classmethod
    def from_ref(cls, ref: str) -> SourceRef:
        parsed = urlsplit(str(ref))
        if parsed.scheme != "atlas" or parsed.netloc != "source" or parsed.path != "/v1":
            raise ValueError("unsupported SourceRef format")
        values = parse_qs(parsed.query, keep_blank_values=False, strict_parsing=True)
        if any(len(items) != 1 for items in values.values()):
            raise ValueError("duplicate SourceRef fields")
        data = {key: items[0] for key, items in values.items()}
        allowed = set(cls.__dataclass_fields__)
        if set(data) - allowed:
            raise ValueError("unknown SourceRef fields")
        for field in ("span_start", "span_end"):
            if field in data:
                data[field] = int(data[field])
        return cls(**data)
