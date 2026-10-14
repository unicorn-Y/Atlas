"""Atlas does not ship Hermes' browser provider plugin registry."""
from __future__ import annotations


def get_provider(_name: str):
    return None


def registry_generation(*, scope=None) -> int:
    del scope
    return 0

