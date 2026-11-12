"""Atlas boundary for Hermes' interactive sudo integration."""

from __future__ import annotations

import re


_SUDO_COMMAND = re.compile(r"(^|[;&|()\s])sudo(?=\s|$)")


def _rewrite_compound_background(command: str) -> str:
    """No Atlas-specific compound-background wrapper is installed."""
    return command


def _transform_sudo_command(command: str | None, sudo_nopasswd_check=None):
    del sudo_nopasswd_check
    if command is None:
        return None, None
    if _SUDO_COMMAND.search(command):
        raise RuntimeError("Interactive sudo is not supported by this Atlas terminal backend.")
    return command, None
