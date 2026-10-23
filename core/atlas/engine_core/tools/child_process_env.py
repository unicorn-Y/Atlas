"""Build child environments for command tools and MCP servers."""
from __future__ import annotations

import os
from collections.abc import Mapping

# Atlas' gateway key plus exact environment names used by common model providers.
# Keep this list explicit: tool and SaaS credentials such as BRAVE_API_KEY must
# remain available to command children.
_MODEL_CREDENTIALS = frozenset({
    "ATLAS_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_TOKEN",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DASHSCOPE_API_KEY",
    "MOONSHOT_API_KEY",
    "ZHIPUAI_API_KEY",
    "ZAI_API_KEY",
    "GLM_API_KEY",
    "OPENROUTER_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
    "XAI_API_KEY",
    "MINIMAX_API_KEY",
    "COHERE_API_KEY",
    "TOGETHER_API_KEY",
    "NVIDIA_API_KEY",
    "HUGGINGFACEHUB_API_TOKEN",
    "HF_TOKEN",
})


def _scrub_enabled() -> bool:
    override = os.environ.get("ATLAS_SCRUB_CHILD_ENV")
    if override is not None:
        return override.strip().lower() not in {"0", "false", "no", "off"}
    try:
        from atlas.config import get_config

        return bool(get_config().get("local_execution.scrub_child_env", True))
    except Exception:
        # Keep command execution functional if optional config loading fails.
        return True


def _string_env(values: Mapping[str, object] | None) -> dict[str, str]:
    return {str(key): str(value) for key, value in (values or {}).items()}


def child_process_env(explicit: Mapping[str, object] | None = None) -> dict[str, str]:
    """Build a command-tool environment, optionally removing model credentials.

    Caller-provided values are applied last and are preserved even when their
    names are in the model credential list. A ``None`` value removes one
    inherited variable without serializing the string ``"None"`` to the child.
    """
    env = _string_env(os.environ)
    if _scrub_enabled():
        for name in _MODEL_CREDENTIALS:
            env.pop(name, None)
    overrides = explicit or {}
    for key, value in overrides.items():
        name = str(key)
        if value is None:
            env.pop(name, None)
        else:
            env[name] = str(value)
    return env


def mcp_child_process_env(explicit: Mapping[str, object] | None = None) -> dict[str, str]:
    """Build an MCP environment with complete parent inheritance and overrides."""
    env = _string_env(os.environ)
    env.update(_string_env(explicit))
    return env
