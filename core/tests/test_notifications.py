"""NotificationBus coverage — config parsing, disabled no-op, fake delivery."""

from __future__ import annotations

import pytest

from atlas.notifications import NotificationBus
from atlas.notifications import apprise as apprise_module


def test_configured_urls_reads_env_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_NOTIFY_URLS", "json://localhost:1\n tgram://token/chat")
    assert apprise_module.configured_urls() == ["json://localhost:1", "tgram://token/chat"]
    monkeypatch.setenv("ATLAS_NOTIFY_URLS", "json://a, json://b")
    assert apprise_module.configured_urls() == ["json://a", "json://b"]


async def test_disabled_bus_is_a_safe_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_NOTIFY_URLS", raising=False)
    bus = NotificationBus(urls=[])
    assert bus.enabled is False
    result = await bus.notify("title", "body")
    assert result == {"enabled": False, "sent": [], "failed": [], "error": None}


async def test_notify_delivers_to_every_target(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def add(self, url: str) -> bool:
            return url != "broken://target"

        def remove(self, url: str) -> None:
            return None

        def notify(self, *, body: str, title: str, body_format=None) -> bool:
            calls.append((title, body))
            return "fail" not in body

    import sys

    fake_apprise = type(sys)("apprise")
    fake_apprise.Apprise = FakeClient
    fake_apprise.NotifyFormat = type("NotifyFormat", (), {"TEXT": "text"})
    monkeypatch.setitem(sys.modules, "apprise", fake_apprise)

    bus = NotificationBus(urls=["json://one", "broken://target", "json://two"])
    result = await bus.notify("Atlas", "hello")
    assert result["sent"] == ["json://one", "json://two"]
    assert result["failed"] == ["broken://target"]
    assert len(calls) == 2


async def test_delivery_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    def boom() -> None:
        raise RuntimeError("apprise exploded")

    monkeypatch.setitem(sys.modules, "apprise", property(boom))  # import-time failure path
    bus = NotificationBus(urls=["json://one"])
    result = await bus.notify("t", "b")
    assert result["enabled"] is True
    assert result["failed"] == ["json://one"]
    assert result["error"]
