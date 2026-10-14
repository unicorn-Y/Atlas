"""Transcript sanitization needed by the SessionDB message readers."""

from __future__ import annotations

import re

_INTERNAL_CONTEXT_RE = re.compile(r'<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>', re.IGNORECASE)
_INTERNAL_NOTE_RE = re.compile(
    r'\[System note:\s*The following is recalled memory context,\s*NOT new user input\.\s*Treat as (?:informational background data|authoritative reference data[^\]]*)\.\]\s*',
    re.IGNORECASE,
)
_FENCE_TAG_RE = re.compile(r'</?memory-context>', re.IGNORECASE)


def sanitize_context(text: str) -> str:
    for pattern in (_INTERNAL_CONTEXT_RE, _INTERNAL_NOTE_RE, _FENCE_TAG_RE):
        text = pattern.sub('', text)
    return text


