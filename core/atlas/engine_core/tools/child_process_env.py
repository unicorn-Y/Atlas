"""Build child environments without leaking inherited model API credentials."""
from __future__ import annotations

import os
import re
from collections.abc import Mapping

_EXACT_CREDENTIALS = frozenset({
    "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_API_KEY",
    "HUGGINGFACEHUB_API_TOKEN", "HF_TOKEN", "DASHSCOPE_API_KEY",
})
_API_CREDENTIAL = re.compile(r"(?:^|_)(?:API_KEY|API_TOKEN)$", re.IGNORECASE)


def child_process_env(explicit: Mapping[str, object] | None = None) -> dict[str, str]:
    """Scrub only inherited model credentials, then apply caller-provided values.

    Explicit variables belong to this particular child launch and intentionally
    override the inherited environment, including a credential if requested.
    """
    env = {str(key): str(value) for key, value in os.environ.items()
           if str(key).upper() not in _EXACT_CREDENTIALS
           and not _API_CREDENTIAL.search(str(key))}
    env.update({str(key): str(value) for key, value in (explicit or {}).items()})
    return env
