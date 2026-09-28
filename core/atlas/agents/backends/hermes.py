"""Hermes' supported ACP protocol entry point."""

from atlas.runtime.backends import ACPBackend


def create() -> ACPBackend:
    return ACPBackend("hermes", "hermes", ["acp"])
