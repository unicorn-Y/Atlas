"""Explicit unsupported boundary for Bot Desktop shared Chromium."""

from . import UNSUPPORTED


def __getattr__(name: str):
    raise RuntimeError(f"{UNSUPPORTED} Missing browser operation: {name}")
