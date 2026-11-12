"""Atlas registry view used by Hermes' deferred-tool argument validator."""

from __future__ import annotations


def _core_tool_names() -> set[str]:
    from atlas.engine.tools.registry import registry

    return set(registry.get_all_tool_names())
