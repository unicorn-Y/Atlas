"""Explicit unsupported boundary for Hermes Bot Desktop browser hooks."""

from __future__ import annotations

from . import UNSUPPORTED
from . import placement


def desktop_env(env: dict) -> dict:
    """Leave the regular local browser environment unchanged."""
    return env


def published_env() -> dict:
    return {}


def ensure_started_for_tool() -> None:
    raise RuntimeError(UNSUPPORTED)


def tool_placement() -> str:
    where = placement.resolve()
    if where.where == placement.REFUSED:
        raise RuntimeError(where.reason)
    if where.where == placement.TERMINAL:
        raise RuntimeError(UNSUPPORTED)
    return placement.GATEWAY


def _sandbox_env(*, create: bool = False):
    del create
    raise RuntimeError(UNSUPPORTED)
