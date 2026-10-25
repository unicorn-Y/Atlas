"""Built-in channel adapters with optional SDKs registered only when usable."""

from __future__ import annotations


def register_builtin_channels(register) -> None:
    """Register built-ins and each usable optional SDK adapter independently."""
    from atlas.channels.adapters.email import EmailAdapter
    from atlas.channels.adapters.telegram import TelegramAdapter
    from atlas.channels.adapters.webhook import WebhookAdapter

    register("telegram", TelegramAdapter)
    register("webhook", WebhookAdapter)
    register("email", EmailAdapter)

    # Optional adapters are independent: a missing SDK must not hide later
    # adapters from the registry (a previous early return skipped all of them).
    optional = (
        ("slack", "atlas.channels.adapters.slack", "SlackAdapter"),
        ("feishu", "atlas.channels.adapters.feishu", "FeishuAdapter"),
        ("dingtalk", "atlas.channels.adapters.dingtalk", "DingTalkAdapter"),
        ("wecom", "atlas.channels.adapters.wecom", "WeComAdapter"),
    )
    import importlib

    for channel, module_name, class_name in optional:
        try:
            adapter = getattr(importlib.import_module(module_name), class_name)
            if adapter.is_available() and channel == "slack":
                importlib.import_module("slack_sdk.socket_mode.aiohttp")
                importlib.import_module("slack_sdk.web.async_client")
            if adapter.is_available():
                register(channel, adapter)
        except ImportError:
            continue


__all__ = ["register_builtin_channels"]
