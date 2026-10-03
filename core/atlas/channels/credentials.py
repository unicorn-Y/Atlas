"""Channel credential storage.

The :class:`KeyringCredentialStore` pattern is lifted verbatim from
``atlas.telegram`` (which keeps its own copy for backwards compatibility — that
file is frozen for this wave). Channel secrets live under the key namespace
``atlas.channel.<name>.<field>``; the legacy ``atlas.telegram.bot_token`` key
stays readable through :func:`get_legacy_telegram_token`.

On machines without the ``keyring`` package the store degrades to environment
variables named ``ATLAS_CHANNEL_<NAME>_<FIELD>`` (reading only; writes still
require a working OS credential store, mirroring the original behaviour).
"""

from __future__ import annotations

import os
import re
from typing import Protocol

SERVICE_NAME = "Atlas"
KEY_PREFIX = "atlas.channel"
LEGACY_TELEGRAM_TOKEN_KEY = "atlas.telegram.bot_token"
ENV_PREFIX = "ATLAS_CHANNEL"


class CredentialStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


class KeyringCredentialStore:
    """OS keyring backed store (lazy import, degrades loudly on write only)."""

    def get(self, key: str) -> str | None:
        try:
            import keyring
        except ImportError:
            return None
        return keyring.get_password(SERVICE_NAME, key)

    def set(self, key: str, value: str) -> None:
        try:
            import keyring
        except ImportError:
            raise RuntimeError("系统凭据库不可用，请安装 Atlas 的完整依赖后重试。") from None
        keyring.set_password(SERVICE_NAME, key, value)

    def delete(self, key: str) -> None:
        try:
            import keyring
        except ImportError:
            return
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except keyring.errors.PasswordDeleteError:
            pass


def channel_key(name: str, field: str) -> str:
    """Credential key for one channel field: ``atlas.channel.<name>.<field>``."""
    return f"{KEY_PREFIX}.{name}.{field}"


def env_var_name(name: str, field: str) -> str:
    """Environment fallback name: ``ATLAS_CHANNEL_<NAME>_<FIELD>``."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{name}_{field}").strip("_").upper()
    return f"{ENV_PREFIX}_{slug}"


class ChannelCredentialStore:
    """Namespaced credential facade for channel adapters.

    Read order: keyring key ``atlas.channel.<name>.<field>`` → environment
    variable ``ATLAS_CHANNEL_<NAME>_<FIELD>`` (keyring-less machines). Writes
    always go to the OS credential store; a missing keyring raises ``RuntimeError``
    so a secret is never silently dropped into a plaintext env var or file.
    """

    def __init__(self, base: CredentialStore | None = None, *, environ: dict | None = None) -> None:
        self.base = base or KeyringCredentialStore()
        self._environ = environ if environ is not None else os.environ

    def get(self, name: str, field: str) -> str | None:
        value = self.base.get(channel_key(name, field))
        if value:
            return value
        return self._environ.get(env_var_name(name, field)) or None

    def set(self, name: str, field: str, value: str) -> None:
        self.base.set(channel_key(name, field), value)

    def delete(self, name: str, field: str) -> None:
        self.base.delete(channel_key(name, field))

    def get_legacy_telegram_token(self) -> str | None:
        """Bot token for the pre-channels Telegram integration.

        Reads the frozen legacy key ``atlas.telegram.bot_token`` first, then the
        new namespaced key, then the ``ATLAS_TELEGRAM_BOT_TOKEN`` environment
        variable — so the existing deployment keeps working after the takeover.
        """
        value = self.base.get(LEGACY_TELEGRAM_TOKEN_KEY)
        if value:
            return value
        value = self.get("telegram", "bot_token")
        if value:
            return value
        return self._environ.get("ATLAS_TELEGRAM_BOT_TOKEN") or None


channel_credentials = ChannelCredentialStore()

__all__ = [
    "SERVICE_NAME",
    "KEY_PREFIX",
    "LEGACY_TELEGRAM_TOKEN_KEY",
    "CredentialStore",
    "KeyringCredentialStore",
    "ChannelCredentialStore",
    "channel_key",
    "env_var_name",
    "channel_credentials",
    "get_legacy_telegram_token",
]


def get_legacy_telegram_token() -> str | None:
    return channel_credentials.get_legacy_telegram_token()
