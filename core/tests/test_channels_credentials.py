"""Credential store tests — keyring namespace, env degradation, legacy telegram token."""

from __future__ import annotations

import builtins
import sys
import types

import pytest

from atlas.channels.credentials import (
    ChannelCredentialStore,
    KeyringCredentialStore,
    channel_key,
    env_var_name,
)


class MemoryStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def test_key_naming_convention():
    assert channel_key("telegram", "bot_token") == "atlas.channel.telegram.bot_token"
    assert env_var_name("telegram", "bot_token") == "ATLAS_CHANNEL_TELEGRAM_BOT_TOKEN"
    assert env_var_name("my channel", "app.key") == "ATLAS_CHANNEL_MY_CHANNEL_APP_KEY"


def test_env_fallback_when_keyring_empty():
    store = ChannelCredentialStore(
        base=MemoryStore(), environ={"ATLAS_CHANNEL_SLACK_BOT_TOKEN": "env-secret"}
    )
    assert store.get("slack", "bot_token") == "env-secret"
    assert store.get("slack", "signing_secret") is None


def test_keyring_value_wins_over_env():
    store = ChannelCredentialStore(
        base=MemoryStore({"atlas.channel.slack.bot_token": "ring-secret"}),
        environ={"ATLAS_CHANNEL_SLACK_BOT_TOKEN": "env-secret"},
    )
    assert store.get("slack", "bot_token") == "ring-secret"


def test_set_and_delete_roundtrip_on_injected_store():
    base = MemoryStore()
    store = ChannelCredentialStore(base=base)
    store.set("email", "password", "p@ss")
    assert base.values["atlas.channel.email.password"] == "p@ss"
    assert store.get("email", "password") == "p@ss"
    store.delete("email", "password")
    assert store.get("email", "password") is None


def test_legacy_telegram_token_reads_old_key_first():
    store = ChannelCredentialStore(base=MemoryStore({
        "atlas.telegram.bot_token": "legacy-token",
        "atlas.channel.telegram.bot_token": "new-token",
    }))
    assert store.get_legacy_telegram_token() == "legacy-token"


def test_legacy_telegram_token_falls_back_to_new_key_then_env():
    store = ChannelCredentialStore(
        base=MemoryStore({"atlas.channel.telegram.bot_token": "new-token"}), environ={}
    )
    assert store.get_legacy_telegram_token() == "new-token"
    empty = ChannelCredentialStore(
        base=MemoryStore(), environ={"ATLAS_TELEGRAM_BOT_TOKEN": "env-token"}
    )
    assert empty.get_legacy_telegram_token() == "env-token"


def test_keyring_module_missing_degrades_get_and_blocks_set(monkeypatch):
    original_import = builtins.__import__

    def without_keyring(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_keyring)
    store = KeyringCredentialStore()
    assert store.get("atlas.channel.telegram.bot_token") is None
    with pytest.raises(RuntimeError, match="系统凭据库"):
        store.set("atlas.channel.telegram.bot_token", "secret")
    # delete is a no-op without keyring
    store.delete("atlas.channel.telegram.bot_token")


def test_keyring_backed_store_roundtrip(monkeypatch):
    backend: dict[str, str] = {}

    fake_errors = types.ModuleType("keyring.errors")
    fake_errors.PasswordDeleteError = type("PasswordDeleteError", (Exception,), {})
    fake_keyring = types.ModuleType("keyring")
    fake_keyring.errors = fake_errors
    fake_keyring.get_password = lambda service, key: backend.get((service, key))
    def set_password(service, key, value):
        backend[(service, key)] = value

    fake_keyring.set_password = set_password

    def delete_password(service, key):
        if (service, key) not in backend:
            raise fake_errors.PasswordDeleteError("missing")
        backend.pop((service, key))

    fake_keyring.delete_password = delete_password
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake_errors)

    store = ChannelCredentialStore(base=KeyringCredentialStore())
    store.set("telegram", "bot_token", "ring-token")
    assert backend[("Atlas", "atlas.channel.telegram.bot_token")] == "ring-token"
    assert store.get("telegram", "bot_token") == "ring-token"
    store.delete("telegram", "bot_token")
    assert store.get("telegram", "bot_token") is None
