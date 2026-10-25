"""Tool failures seen in the installed app on a real Windows machine (2026-10-06)."""

from __future__ import annotations

import ipaddress
import socket

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("address", "public"), [
    ("8.8.8.8", True),
    ("198.18.0.20", True),     # proxy fake-IP answer for a public host
    ("198.19.255.1", True),
    ("10.0.0.5", False),
    ("192.168.31.158", False),
    ("127.0.0.1", False),
    ("169.254.169.254", False),
    ("::1", False),
])
def test_public_address_policy_accepts_proxy_fake_ip_only(address, public):
    from atlas.tools.ssrf_transport import is_public_address

    assert is_public_address(ipaddress.ip_address(address)) is public


def test_web_extract_url_check_passes_behind_a_fake_ip_proxy(monkeypatch):
    """With Clash fake-IP every site resolved into 198.18/15 and web_extract refused all
    of them as 'internal addresses'."""
    from atlas.tools import web_extract

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.20", 443)),
    ])
    assert web_extract._validate_url("https://example.com/", False) == "https://example.com/"

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443)),
    ])
    with pytest.raises(ValueError):
        web_extract._validate_url("https://intranet.example/", False)


def test_mcp_server_with_empty_credential_is_not_auto_started(monkeypatch):
    from atlas.tools.mcp_client import missing_credentials

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert missing_credentials({"BRAVE_API_KEY": ""}) == ["BRAVE_API_KEY"]
    assert missing_credentials({"BRAVE_API_KEY": "k"}) == []
    assert missing_credentials({"DEBUG": ""}) == []
    monkeypatch.setenv("BRAVE_API_KEY", "from-env")
    assert missing_credentials({"BRAVE_API_KEY": ""}) == []

    from atlas.engine.hermes_runtime import HermesRuntime

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    servers = HermesRuntime._adapt_atlas_mcp_servers({
        "brave-search": {"command": "npx", "env": {"BRAVE_API_KEY": ""}},
        "git": {"command": "uvx", "env": {}},
    })
    assert servers["brave-search"]["enabled"] is False
    assert servers["git"]["enabled"] is True


def test_missing_cloud_sandbox_sdk_returns_an_install_hint(monkeypatch):
    import importlib.util

    from atlas.engine_core.tools.environments.remote_common import ensure_lazy_dep

    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    with pytest.raises(ImportError, match=r"optional Atlas dependency.*\[daytona\]"):
        ensure_lazy_dep("daytona")


def test_browser_tool_uses_an_installed_browser(monkeypatch, tmp_path):
    from atlas.engine_core.tools import browser_tool_install

    browser = tmp_path / "msedge.exe"
    browser.write_bytes(b"")
    monkeypatch.setenv("AGENT_BROWSER_EXECUTABLE_PATH", str(browser))
    assert browser_tool_install._chromium_executable() == str(browser)
