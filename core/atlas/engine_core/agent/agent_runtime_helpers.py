"""Minimal transcript sequence adapter retained for SessionDB restoration."""

from __future__ import annotations


def repair_message_sequence(agent, messages: list[dict]) -> int:
    """Leave durable rows unchanged; Atlas kernel repairs unpaired calls before model requests."""
    return 0


