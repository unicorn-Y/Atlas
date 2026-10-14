"""Atlas-side no-op adapter for optional Hermes startup progress hooks."""

from __future__ import annotations


def report_startup_progress(*args, **kwargs) -> None:
    return None

