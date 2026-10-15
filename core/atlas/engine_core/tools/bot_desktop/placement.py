"""Explicit unsupported boundary for Bot Desktop window placement."""

from . import UNSUPPORTED


def __getattr__(name: str):
    raise RuntimeError(f"{UNSUPPORTED} Missing placement operation: {name}")
