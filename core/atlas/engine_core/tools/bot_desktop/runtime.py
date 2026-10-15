"""Explicit unsupported boundary for Hermes Bot Desktop browser hooks."""

from __future__ import annotations

from . import UNSUPPORTED


def desktop_env(env: dict) -> dict:
    """Leave the regular local browser environment unchanged."""
    return env


def published_env() -> dict:
    return {}


def ensure_started_for_tool() -> None:
    raise RuntimeError(UNSUPPORTED)


def _sandbox_env(*, create: bool = False):
    del create
    raise RuntimeError(UNSUPPORTED)
