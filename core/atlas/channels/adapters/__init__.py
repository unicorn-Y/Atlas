"""Built-in channel adapters with optional SDKs registered only when usable."""

from __future__ import annotations


def register_builtin_channels(register) -> None:
    """Register built-in factories, including Slack when Socket Mode is available."""
    from atlas.channels.adapters.email import EmailAdapter
    from atlas.channels.adapters.telegram import TelegramAdapter
    from atlas.channels.adapters.webhook import WebhookAdapter

    register("telegram", TelegramAdapter)
    register("webhook", WebhookAdapter)
    register("email", EmailAdapter)

    # Slack's SDK is an optional ``channels`` extra. Probe the concrete imports
    # used by start(), because the SDK root package can exist without its aiohttp
    # Socket Mode transport. Keep a missing optional dependency channel-local.
    try:
        from atlas.channels.adapters.slack import SlackAdapter

        if not SlackAdapter.is_available():
            return
        from slack_sdk.socket_mode.aiohttp import SocketModeClient  # noqa: F401
        from slack_sdk.web.async_client import AsyncWebClient  # noqa: F401
    except ImportError:
        return

    register("slack", SlackAdapter)


__all__ = ["register_builtin_channels"]
