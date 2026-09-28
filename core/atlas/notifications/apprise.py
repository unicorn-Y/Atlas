"""Apprise-backed notification bus — how Atlas talks to the user.

One thin adapter over caronc/apprise: Windows toast, Telegram, Discord,
Slack, Email, Webhook, and hundreds more, configured purely by URLs
(``[notifications] urls`` in atlas.toml or ``ATLAS_NOTIFY_URLS``, one URL
per line or comma-separated). With no URLs configured the bus is a no-op
that reports ``disabled`` instead of failing.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from atlas.config import get_config


def configured_urls() -> list[str]:
    """Notification target URLs from config/environment (empty = disabled)."""
    env = os.environ.get("ATLAS_NOTIFY_URLS", "")
    candidates = [line.strip() for line in env.replace(",", "\n").splitlines()]
    if not candidates:
        raw = get_config().raw.get("notifications", {})
        if isinstance(raw, dict):
            urls = raw.get("urls", [])
            if isinstance(urls, list):
                candidates = [str(url).strip() for url in urls]
    return [url for url in candidates if url]


class NotificationBus:
    """Send one message to every configured Apprise target."""

    def __init__(self, urls: list[str] | None = None) -> None:
        self._urls = configured_urls() if urls is None else list(urls)

    @property
    def enabled(self) -> bool:
        return bool(self._urls)

    def status(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "targets": len(self._urls)}

    async def notify(self, title: str, body: str) -> dict[str, Any]:
        """Deliver one notification; never raises into caller flows."""
        if not self._urls:
            return {"enabled": False, "sent": [], "failed": [], "error": None}
        try:
            return await asyncio.to_thread(self._send_sync, title, body)
        except Exception as exc:  # notifications must not break task flows
            return {"enabled": True, "sent": [], "failed": self._urls, "error": str(exc)}

    def _send_sync(self, title: str, body: str) -> dict[str, Any]:
        import apprise

        client = apprise.Apprise()
        sent: list[str] = []
        failed: list[str] = []
        for url in self._urls:
            if not client.add(url):
                failed.append(url)
                continue
            try:
                if client.notify(body=body, title=title, body_format=apprise.NotifyFormat.TEXT):
                    sent.append(url)
                else:
                    failed.append(url)
            finally:
                client.remove(url)
        return {"enabled": True, "sent": sent, "failed": failed, "error": None}
