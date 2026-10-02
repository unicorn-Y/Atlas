from __future__ import annotations

from .base import ParticipantAdapter, RunContext, RunOutcome
from .atlas import AtlasAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .fake import FakeAdapter
from .hermes import HermesAdapter
from .opencode import OpenCodeAdapter
from .pi import PiAdapter
from .zcode import ZCodeAdapter

_ADAPTERS = {a.name: a for a in (AtlasAdapter, ClaudeAdapter, CodexAdapter,
                                  OpenCodeAdapter, PiAdapter, HermesAdapter,
                                  ZCodeAdapter, FakeAdapter)}

def get_adapter(name: str, config: dict | None = None) -> ParticipantAdapter:
    try:
        return _ADAPTERS[name](config)
    except KeyError as exc:
        raise ValueError(f"unknown participant: {name}") from exc

__all__ = ["RunContext", "RunOutcome", "ParticipantAdapter", "get_adapter"]
