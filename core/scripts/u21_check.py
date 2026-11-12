"""U21 real-scenario checks for WSL policy, browser vault imports and MCP progress."""
from __future__ import annotations

import asyncio
import csv
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))


def check_wsl_policy() -> None:
    from atlas.api import wsl_policy_router
    import asyncio

    settings: dict[str, object] = {}
    with patch.object(wsl_policy_router, "load_user_settings", side_effect=lambda: dict(settings)), \
            patch.object(wsl_policy_router, "save_user_settings", side_effect=lambda value: settings.update(value)):
        response = asyncio.run(wsl_policy_router.write_wsl_policy(
            wsl_policy_router.WslPolicyRequest(enabled=False, require_isolation=True), None,
        ))
        assert response["enabled"] is False and response["require_isolation"] is True

    with patch.object(wsl_policy_router, "get_wsl_policy", return_value={"enabled": True, "require_isolation": True}):
        sandbox = wsl_policy_router.apply_wsl_session_policy(None, runtime_is_wsl=True)
        assert sandbox == {"type": "docker", "network": False}
        forced = wsl_policy_router.apply_wsl_session_policy(
            {"type": "docker", "network": True, "image": "atlas-test:latest"},
            runtime_is_wsl=True,
        )
        assert forced == {"type": "docker", "network": False, "image": "atlas-test:latest"}
    with patch.object(wsl_policy_router, "get_wsl_policy", return_value={"enabled": False, "require_isolation": False}):
        try:
            wsl_policy_router.apply_wsl_session_policy(None, runtime_is_wsl=True)
        except PermissionError as exc:
            assert "禁用 WSL 会话" in str(exc)
        else:
            raise AssertionError("disabled WSL sessions started")
    assert wsl_policy_router.apply_wsl_session_policy(None, runtime_is_wsl=False) is None
    print("WSL policy: WSL runs honor enable/disable and require-isolation; native runs remain unchanged")


def check_browser_password_import(base: Path) -> None:
    from atlas.engine.agent.browser_password_csv import import_selected, preview_csv
    from atlas.engine.agent.vault_store import VaultStore

    def csv_text(password: str) -> str:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=["name", "url", "username", "password", "note"])
        writer.writeheader()
        writer.writerow({"name": "Atlas fixture site", "url": "https://login.example.test/account", "username": "fixture-user", "password": password})
        writer.writerow({"name": "invalid URL", "url": "file:///private", "username": "ignored", "password": "ignored"})
        return output.getvalue()

    store = VaultStore(base / "vault")
    preview = preview_csv("Chrome CSV export", csv_text("u21-local-secret-one"))
    items = preview["candidates"]
    assert len(items) == 1 and items[0]["origin"] == "https://login.example.test"
    first_id = items[0]["id"]
    result = import_selected(preview["import_token"], [first_id], store, overwrite_confirmed=False)
    assert result == {"imported": [first_id], "skipped": []}
    meta = store.list_items()[0].to_dict()
    assert meta["origin"] == "https://login.example.test"
    assert meta["login_method"]["fields"] == {"identifier": "username", "password": "current-password"}
    assert meta["login_method"]["confirm_before_fill"] is True
    assert meta["login_method"]["source"] == "Chrome CSV export"
    assert store.resolve_secret(meta["id"])["password"] == "u21-local-secret-one"

    duplicate_preview = preview_csv("Edge CSV export", csv_text("u21-local-secret-two"))
    duplicate_id = duplicate_preview["candidates"][0]["id"]
    skipped = import_selected(duplicate_preview["import_token"], [duplicate_id], store, overwrite_confirmed=False)
    assert skipped == {"imported": [], "skipped": [duplicate_id]}
    overwrite_preview = preview_csv("Edge CSV export", csv_text("u21-local-secret-two"))
    overwrite_id = overwrite_preview["candidates"][0]["id"]
    replaced = import_selected(overwrite_preview["import_token"], [overwrite_id], store, overwrite_confirmed=True)
    assert replaced == {"imported": [overwrite_id], "skipped": []}
    assert store.resolve_secret(meta["id"])["password"] == "u21-local-secret-two"
    print("Browser password import: selected CSV metadata, encrypted vault write, exact origin, field mapping, fill confirmation and explicit overwrite")


def check_mcp_startup_progress() -> None:
    from atlas.tools.mcp_client import MCPClient, MCPServerConfig

    class Session:
        async def initialize(self):
            return SimpleNamespace(protocol_version="2025-03-26", server_info={"name": "fixture"}, instructions="")

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name="ping", description="test", input_schema={"type": "object"}, annotations=None)])

    async def scenario() -> None:
        client = MCPClient()

        async def attach(_cfg, handle):
            handle.session = Session()

        with patch.object(client, "_connect_stdio", new=attach):
            await client._connect_server(MCPServerConfig(name="fixture", transport="stdio", command="python"))
        states = [item["state"] for item in client.get_runtime_status()["startup_progress"]]
        assert states == ["connecting", "initializing", "discovering_tools", "ready"], states
        runtime = client.get_runtime_status()
        assert runtime["servers"][0]["connected"] and runtime["servers"][0]["tool_count"] == 1
        await asyncio.gather(*list(client._reconnect_tasks.values()), return_exceptions=True)

        failed = MCPClient()

        class BrokenSession:
            async def initialize(self):
                raise RuntimeError("fixture-secret-must-not-appear")

        async def attach_broken(_cfg, handle):
            handle.session = BrokenSession()

        with patch.object(failed, "_connect_stdio", new=attach_broken):
            try:
                await failed._connect_server(MCPServerConfig(name="broken", transport="stdio", command="python"))
            except RuntimeError:
                pass
            else:
                raise AssertionError("MCP initialization failure was not surfaced")
        failure = failed.get_runtime_status()["startup_progress"][-1]
        assert failure["state"] == "failed" and "RuntimeError" in failure["message"]
        assert "fixture-secret-must-not-appear" not in failure["message"]

    asyncio.run(scenario())
    print("MCP startup: per-server lifecycle records connecting/ready/tool discovery and safe failure causes")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u21-") as temporary:
        base = Path(temporary)
        check_wsl_policy()
        check_browser_password_import(base)
        check_mcp_startup_progress()
    print("U21 CHECK PASS")


if __name__ == "__main__":
    main()
