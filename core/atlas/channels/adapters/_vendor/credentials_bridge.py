"""Credential lookup bridge for the W2b adapters (slack / feishu / dingtalk / wecom).

Wave2 converge: the shared credential store lives in :mod:`atlas.channels.credentials`
(owned by W2a). When that module is importable we read through it — keyring key
``atlas.channel.<name>.<field>`` first, then the documented env fallback
``ATLAS_CHANNEL_<NAME>_<FIELD>``. When it is not importable this bridge degrades to the
env fallback only. Adapter ``config`` dict values take precedence over anything resolved
here; that precedence is enforced in each adapter, not in this module.
"""

from __future__ import annotations

import os
import re
from typing import Optional

try:  # Wave2 converge: shared W2a credential store when present.
    from atlas.channels.credentials import channel_credentials as _shared
except Exception:  # pragma: no cover - pre-converge fallback only
    _shared = None


def env_var_name(name: str, field: str) -> str:
    """Mirror of :func:`atlas.channels.credentials.env_var_name`."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{name}_{field}").strip("_").upper()
    return f"ATLAS_CHANNEL_{slug}"


def get_channel_secret(name: str, field: str) -> Optional[str]:
    """Return one channel credential (``str | None``) via the shared store or env."""
    if _shared is not None:
        try:
            value = _shared.get(name, field)
        except Exception:
            value = None
        if value:
            return value
    return os.environ.get(env_var_name(name, field)) or None


__all__ = ["env_var_name", "get_channel_secret"]
