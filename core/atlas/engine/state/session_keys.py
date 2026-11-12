"""Legacy session-key namespace parsing retained for state repair compatibility."""

from __future__ import annotations

from typing import Optional


def _session_key_namespace(profile: Optional[str]) -> str:
    if not profile or profile == "default":
        return "agent:main"
    return "agent:main~" if profile == "main" else f"agent:{profile}"


def profile_from_session_key_namespace(namespace: str) -> str:
    if namespace == "main":
        return "default"
    return "main" if namespace == "main~" else namespace
