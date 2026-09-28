"""Shared runtime contracts for upstream integrations."""

from atlas.runtime.backends import ACPBackend, AgentBackend, AgentEvent, AgentSession
from atlas.runtime.capability_bus import CapabilityBus, CapabilityRecord
from atlas.runtime.external_process import ExternalProcessAdapter

__all__ = [
    "AgentBackend",
    "AgentBackendHost",
    "ACPBackend",
    "AgentEvent",
    "AgentSession",
    "CapabilityBus",
    "CapabilityRecord",
    "ExternalProcessAdapter",
]


def __getattr__(name: str):
    if name == "AgentBackendHost":
        from atlas.runtime.backend_host import AgentBackendHost

        return AgentBackendHost
    raise AttributeError(name)
