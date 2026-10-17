"""Stable provenance pointers to canonical SessionDB messages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit


@dataclass(frozen=True, slots=True)
class SourceRef:
    conversation_id: str
    message_uid: str

    def __post_init__(self) -> None:
        if not self.conversation_id.strip() or not self.message_uid.strip():
            raise ValueError("conversation_id and message_uid are required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_ref(self) -> str:
        return "atlas://source/v1?" + urlencode(self.to_dict())

    @classmethod
    def from_ref(cls, ref: str) -> SourceRef:
        parsed = urlsplit(str(ref))
        if (parsed.scheme, parsed.netloc, parsed.path) != ("atlas", "source", "/v1"):
            raise ValueError("unsupported SourceRef format")
        values = parse_qs(parsed.query, keep_blank_values=False, strict_parsing=True)
        if set(values) != {"conversation_id", "message_uid"} or any(len(v) != 1 for v in values.values()):
            raise ValueError("invalid SourceRef fields")
        return cls(values["conversation_id"][0], values["message_uid"][0])

