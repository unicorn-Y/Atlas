"""Context-local project identity for settings and credentials during a run."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from collections.abc import AsyncIterator
from typing import Any
import json
import re

_PROJECT_ID: ContextVar[str | None] = ContextVar("atlas_project_id", default=None)
_SESSION_ID: ContextVar[str | None] = ContextVar("atlas_session_id", default=None)
_CONFIG_OVERRIDE: ContextVar[dict[str, Any] | None] = ContextVar("atlas_config_override", default=None)
_IGNORE_PROJECT_CONFIG: ContextVar[bool] = ContextVar("atlas_ignore_project_config", default=False)


def current_project_id() -> str | None:
    return _PROJECT_ID.get()


def current_session_id() -> str | None:
    return _SESSION_ID.get()


@contextmanager
def project_scope(
    project_id: str | None, *, config_override: dict[str, Any] | None = None,
    ignore_project_config: bool = False, session_id: str | None = None,
) -> Iterator[None]:
    token = _PROJECT_ID.set(str(project_id).strip() or None if project_id else None)
    session_token = _SESSION_ID.set(str(session_id).strip() or None if session_id else None)
    config_token = _CONFIG_OVERRIDE.set(config_override)
    ignore_token = _IGNORE_PROJECT_CONFIG.set(ignore_project_config)
    try:
        yield
    finally:
        _IGNORE_PROJECT_CONFIG.reset(ignore_token)
        _CONFIG_OVERRIDE.reset(config_token)
        _SESSION_ID.reset(session_token)
        _PROJECT_ID.reset(token)


def current_config_override() -> dict[str, Any] | None:
    return _CONFIG_OVERRIDE.get()


def project_config_ignored() -> bool:
    return _IGNORE_PROJECT_CONFIG.get()


def validate_config_override(value: Any) -> dict[str, Any]:
    """Validate an ephemeral nested config object without accepting secret fields."""
    if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False)) > 65536:
        raise ValueError("config_override must be a JSON object no larger than 64 KiB")
    allowed_roots = {
        "general", "server", "models", "agents", "delegation", "moa", "agent",
        "engine", "library", "memory", "scheduler", "notifications", "web",
        "tools", "tool_output", "integrations", "gateway", "local_execution",
        "computer_use", "logging", "user", "expert", "browser", "telegram",
    }
    if any(key not in allowed_roots for key in value):
        raise ValueError("config_override contains an unknown top-level config section")
    key_pattern = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

    def visit(node: Any, depth: int = 0) -> None:
        if depth > 12:
            raise ValueError("config_override nesting is too deep")
        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str) or not key_pattern.fullmatch(key):
                    raise ValueError("config_override contains an invalid key")
                if any(term in key.casefold() for term in ("api_key", "secret", "password", "token", "credential")):
                    raise ValueError("credentials cannot be passed through config_override")
                visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
        elif node is not None and not isinstance(node, (str, int, float, bool)):
            raise ValueError("config_override values must be JSON values")

    visit(value)
    return value


async def project_scoped_events(
    project_id: str | None, events: Any, *, config_override: dict[str, Any] | None = None,
    ignore_project_config: bool = False, session_id: str | None = None,
) -> AsyncIterator[Any]:
    """Keep a project context active for an asynchronous run and its child tasks."""
    with project_scope(project_id, config_override=config_override,
                       ignore_project_config=ignore_project_config, session_id=session_id):
        async for event in events:
            yield event
