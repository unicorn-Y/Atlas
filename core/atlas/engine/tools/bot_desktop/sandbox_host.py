"""Explicit unsupported boundary for Bot Desktop sandbox hosting."""

from . import UNSUPPORTED


def __getattr__(name: str):
    raise RuntimeError(f"{UNSUPPORTED} Missing sandbox operation: {name}")
