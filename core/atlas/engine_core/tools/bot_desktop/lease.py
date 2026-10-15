"""Explicit unsupported boundary for Bot Desktop leases."""

from . import UNSUPPORTED


def human_holds() -> bool:
    return False


def __getattr__(name: str):
    raise RuntimeError(f"{UNSUPPORTED} Missing lease operation: {name}")
