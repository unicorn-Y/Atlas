"""Build child environments for command tools and MCP servers."""
from __future__ import annotations

import os
import fnmatch
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
# Atlas intentionally preserves non-model provider keys (for example BRAVE_API_KEY)
# because local tools need them. Model-provider credentials remain exact-name
# scrubbed; deployments can add broader patterns through env_policy.exclude.
_DEFAULT_SENSITIVE_PATTERNS: tuple[str, ...] = ()
_UNIX_CORE_ENV = frozenset({
    "PATH", "SHELL", "TMPDIR", "TEMP", "TMP", "HOME", "LANG", "LC_ALL",
    "LC_CTYPE", "LOGNAME", "USER",
})
_WINDOWS_CORE_ENV = frozenset({
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "WINDIR", "USERPROFILE",
    "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PSMODULEPATH",
    "PSExecutionPolicyPreference", "PROMPT",
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


def _matches(name: str, patterns: object) -> bool:
    if not isinstance(patterns, (list, tuple, set, frozenset)):
        return False
    folded = name.casefold()
    return any(
        isinstance(pattern, str) and fnmatch.fnmatchcase(folded, pattern.casefold())
        for pattern in patterns
    )


def _policy() -> dict[str, object]:
    try:
        from atlas.config import get_config

        value = get_config().get("local_execution.env_policy", {})
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def _core_names() -> frozenset[str]:
    return _WINDOWS_CORE_ENV if os.name == "nt" else _UNIX_CORE_ENV


def _inherit_env(mode: object) -> dict[str, str]:
    selected = str(mode or "all").strip().casefold()
    if selected == "none":
        return {}
    source = _string_env(os.environ)
    if selected == "core":
        allowed = {name.casefold() for name in _core_names()}
        return {key: value for key, value in source.items() if key.casefold() in allowed}
    return source


def _apply_overrides(env: dict[str, str], explicit: Mapping[str, object] | None) -> None:
    for key, value in (explicit or {}).items():
        name = str(key)
        existing = next((item for item in env if item.casefold() == name.casefold()), name)
        if value is None:
            env.pop(existing, None)
        else:
            env[existing] = str(value)


def child_process_env(explicit: Mapping[str, object] | None = None) -> dict[str, str]:
    """Build a command-tool environment, optionally removing model credentials.

    Caller-provided values are applied last and are preserved even when their
    names are in the model credential list. A ``None`` value removes one
    inherited variable without serializing the string ``"None"`` to the child.
    """
    policy = _policy()
    env = _inherit_env(policy.get("inherit", "all"))
    if _scrub_enabled():
        sensitive = {name.casefold() for name in _MODEL_CREDENTIALS}
        for name in tuple(env):
            if name.casefold() in sensitive or _matches(name, _DEFAULT_SENSITIVE_PATTERNS):
                env.pop(name, None)
    # Explicit excludes are applied before set overrides, matching the shell
    # policy contract. include_only is applied afterwards, so set cannot bypass
    # an allowlist.
    excludes = policy.get("exclude", ())
    for name in tuple(env):
        if _matches(name, excludes):
            env.pop(name, None)
    _apply_overrides(env, explicit)
    if os.name == "nt" and not any(key.casefold() == "pathext" for key in env):
        env["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
    include_only = policy.get("include_only", ())
    if isinstance(include_only, (list, tuple, set, frozenset)) and include_only:
        env = {key: value for key, value in env.items() if _matches(key, include_only)}
    return env


def mcp_child_process_env(explicit: Mapping[str, object] | None = None) -> dict[str, str]:
    """Build an MCP environment with parent inheritance and explicit removals."""
    env = _string_env(os.environ)
    _apply_overrides(env, explicit)
    return env
