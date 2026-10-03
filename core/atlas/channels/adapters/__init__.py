"""Built-in channel adapters (W2a: telegram / webhook / email).

W2b owns slack/feishu/dingtalk/wecom; nothing here imports those modules.
"""

from __future__ import annotations


def register_builtin_channels(register) -> None:
    """Register the W2a adapter factories on a :class:`atlas.channels.ChannelManager`."""
    from atlas.channels.adapters.email import EmailAdapter
    from atlas.channels.adapters.telegram import TelegramAdapter
    from atlas.channels.adapters.webhook import WebhookAdapter

    register("telegram", TelegramAdapter)
    register("webhook", WebhookAdapter)
    register("email", EmailAdapter)


__all__ = ["register_builtin_channels"]
