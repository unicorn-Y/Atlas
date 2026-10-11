# Behavior references: OpenAI Codex plugin tools documentation (`list_plugins`,
# `request_plugin_install`) and Atlas's existing `PluginRuntime` API. This module
# adds a narrow adapter and does not copy third-party marketplace implementation.
"""Model-callable view of the Atlas plugin marketplace runtime."""

from __future__ import annotations

from typing import Any


def plugin_runtime_for(agent: Any) -> Any:
    runtime = getattr(agent, "_plugin_runtime", None)
    if runtime is not None:
        return runtime
    from atlas.config import PROJECT_ROOT, get_config
    from atlas.plugins import PluginRuntime

    state_path = get_config().db_path.parent / "plugins" / "state.json"
    runtime = PluginRuntime(
        [PROJECT_ROOT / "plugins", state_path.parent], state_path,
    )
    agent._plugin_runtime = runtime
    return runtime
