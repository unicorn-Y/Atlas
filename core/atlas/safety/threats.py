# Adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# tools/threat_patterns.py (MIT, (c) Nous Research); bounded Atlas content scanning.
"""Prompt-injection patterns for untrusted tool and memory content."""

from __future__ import annotations

import re
import unicodedata

MAX_SCAN_CHARS = 65_536
_PATTERNS = (
    ("prompt_injection", re.compile(r"ignore\s+(?:(?:all|previous|prior)\s+){0,2}instructions", re.I)),
    ("sys_prompt_override", re.compile(r"system\s+prompt\s+override", re.I)),
    ("leak_system_prompt", re.compile(r"(?:output|reveal|print)\s+(?:the\s+)?system\s+prompt", re.I)),
    ("context_exfil", re.compile(r"(?:send|upload|share)\s+(?:the\s+)?(?:conversation|full context|chat history)", re.I)),
    ("hidden_div", re.compile(r"<\s*div\s+style\s*=\s*['\"][^>]*display\s*:\s*none", re.I)),
)


def scan_for_threats(content: str, scope: str = "context") -> list[str]:
    if scope not in {"all", "context", "strict"}:
        raise ValueError(f"unknown threat scan scope: {scope}")
    value = unicodedata.normalize("NFKC", (content or "")[:MAX_SCAN_CHARS])
    return [rule_id for rule_id, pattern in _PATTERNS if pattern.search(value)]
