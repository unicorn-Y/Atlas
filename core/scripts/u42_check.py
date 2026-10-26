"""Focused integration checks for U42's six construction items."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))

from atlas.api import dns_router, linear_integration_router, plugins_router, portal_router  # noqa: E402
from atlas.api.app_services import AppServices  # noqa: E402
from atlas.api.network_retry import retry_external_request  # noqa: E402
from atlas.plugins.runtime import PluginRuntime  # noqa: E402


def check_cli() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CORE) + os.pathsep + env.get("PYTHONPATH", "")
    python = Path(sys.executable)
    verify = subprocess.run([str(python), "-m", "atlas.cli", "verify"], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert "internally consistent" in verify.stdout
    for shell, marker in (("bash", "_ATLAS_COMPLETE"), ("zsh", "_ATLAS_COMPLETE"), ("fish", "_ATLAS_COMPLETE")):
        result = subprocess.run([str(python), "-m", "atlas.cli", "completion", shell], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        assert result.returncode == 0, result.stderr
        assert marker in result.stdout and len(result.stdout) > 100


def check_dns() -> None:
    app = FastAPI()
    app.include_router(dns_router.router)
    client = TestClient(app, client=("127.0.0.1", 12345))
    request = {"domain": "atlas.example.com", "target": "203.0.113.10", "record_type": "A", "provider": "cloudflare"}
    plan = client.post("/api/dns/plan", json=request)
    assert plan.status_code == 200, plan.text
    assert plan.json()["record"] == {"type": "A", "name": "atlas.example.com", "value": "203.0.113.10", "ttl": 300, "proxy": "DNS only (gray cloud)"}
    assert plan.json()["status"] == "pending_manual_change"
    assert client.post("/api/dns/plan", json={**request, "target": "not-an-ip"}).status_code == 422

    class FakeTLS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getpeercert(self):
            return {"notAfter": "Dec 31 23:59:59 2030 GMT", "subject": ((("commonName", "atlas.example.com"),),)}

        def version(self):
            return "TLSv1.3"

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    with patch.object(dns_router.socket, "getaddrinfo", return_value=[(None, None, None, None, ("203.0.113.10", 0))]), \
         patch.object(dns_router.socket, "gethostbyname_ex", return_value=("atlas.example.com", [], ["203.0.113.10"])), \
         patch.object(dns_router.socket, "create_connection", return_value=FakeSocket()), \
         patch.object(dns_router.ssl, "create_default_context") as context_factory:
        context_factory.return_value.wrap_socket.return_value = FakeTLS()
        verified = client.post("/api/dns/verify", json=request)
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "healthy"
    assert verified.json()["dns"]["matches_expected"] is True
    assert verified.json()["tls"]["version"] == "TLSv1.3"

    class FakeTLS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getpeercert(self):
            return {"notAfter": "Dec 31 23:59:59 2030 GMT", "subject": ((("commonName", "atlas.example.com"),),)}

        def version(self):
            return "TLSv1.3"

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    with patch.object(dns_router.socket, "getaddrinfo", return_value=[(None, None, None, None, ("203.0.113.10", 0))]), \
         patch.object(dns_router.socket, "gethostbyname_ex", return_value=("atlas.example.com", [], ["203.0.113.10"])), \
         patch.object(dns_router.socket, "create_connection", return_value=FakeSocket()), \
         patch.object(dns_router.ssl, "create_default_context") as context_factory:
        context_factory.return_value.wrap_socket.return_value = FakeTLS()
        result = client.post("/api/dns/verify", json=request)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "healthy"
    assert result.json()["dns"]["matches_expected"] is True
    assert result.json()["tls"]["version"] == "TLSv1.3"


def check_portal() -> None:
    store: dict[str, object] = {"capability_portal": {"enabled": False, "private_network": False, "visible_entries": []}}
    portal_router.load_user_settings = lambda: dict(store)
    portal_router.save_user_settings = lambda value: store.update(value)
    app = FastAPI()
    app.include_router(portal_router.router)
    client = TestClient(app, client=("127.0.0.1", 12345))
    assert client.get("/portal").status_code == 404
    enabled = client.put("/api/portal/config", json={"enabled": True, "private_network": False,
                                                     "visible_entries": ["agent.atlas", "capability.health"]})
    assert enabled.status_code == 200, enabled.text
    manifest = client.get("/api/portal/manifest")
    assert manifest.status_code == 200, manifest.text
    assert {item["id"] for item in manifest.json()["entries"]} == {"agent.atlas", "capability.health"}
    page = client.get("/portal")
    assert page.status_code == 200 and "textContent" in page.text and "Atlas 能力门户" in page.text
    invalid = client.put("/api/portal/config", json={"enabled": True, "private_network": False,
                                                     "visible_entries": ["capability.not-real"]})
    assert invalid.status_code == 422


def check_network_retry() -> None:
    import httpx
    from fastapi import HTTPException
    from atlas.models import router as model_router

    async def connector_scenario() -> None:
        attempts = 0

        class FakeClient:
            def __init__(self, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *_args, **_kwargs):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    return httpx.Response(503)
                return httpx.Response(200, json={"data": {"viewer": {"id": "u1", "name": "Test", "email": "test@example.invalid"}, "teams": {"nodes": []}}})

        with patch.object(linear_integration_router.httpx, "AsyncClient", FakeClient):
            payload = await linear_integration_router._graphql("local-fake-key", "query Fake { viewer { id } }")
        assert payload["viewer"]["id"] == "u1" and attempts == 3

        async def fail_request():
            raise httpx.ConnectError("synthetic TLS EOF", request=httpx.Request("GET", "https://unit.invalid"))

        attempts_error = 0

        async def counted_failure():
            nonlocal attempts_error
            attempts_error += 1
            return await fail_request()

        try:
            await retry_external_request(counted_failure, service="本地假连接器")
        except HTTPException as exc:
            assert exc.status_code == 502 and "已重试 2 次" in exc.detail
        else:
            raise AssertionError("final connector transport failure was silently accepted")
        assert attempts_error == 3

    asyncio.run(connector_scenario())

    class FakeModelClient:
        def __init__(self, sequence):
            self.sequence = iter(sequence)
            self.calls = 0

        def post(self, *_args, **_kwargs):
            self.calls += 1
            result = next(self.sequence)
            if isinstance(result, Exception):
                raise result
            return result

    request = httpx.Request("POST", "https://model.invalid/v1/chat/completions")
    model_client = FakeModelClient([
        httpx.ConnectError("synthetic connection reset", request=request),
        httpx.Response(503),
        httpx.Response(200, json={"ok": True}),
    ])
    pooled = object.__new__(model_router._PooledClient)
    pooled._timeout = 1
    pooled._client = model_client
    with patch.object(model_router._PooledClient, "_rebuild_after_stale_socket", lambda self: None), \
         patch.object(model_router.time, "sleep", lambda _delay: None):
        response = pooled.post("https://model.invalid/v1/chat/completions", json={"model": "fake"})
    assert response.status_code == 200 and model_client.calls == 3

    git_attempts = 0

    def fake_git_run(args, **_kwargs):
        nonlocal git_attempts
        git_attempts += 1
        if git_attempts < 3:
            raise subprocess.CalledProcessError(1, args, stderr="synthetic network reset")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    import atlas.plugins.runtime as plugin_runtime_module
    with patch.object(plugin_runtime_module.subprocess, "run", fake_git_run), \
         patch.object(plugin_runtime_module.time, "sleep", lambda _delay: None):
        PluginRuntime._run_git_with_retry(["git", "fetch"])
    assert git_attempts == 3

    with tempfile.TemporaryDirectory(prefix="atlas-u42-git-offline-") as temp:
        checkout = Path(temp) / "checkout"
        (checkout / ".git").mkdir(parents=True)
        runtime = object.__new__(PluginRuntime)
        runtime._state = {"sources": {"offline-plugin": {"source": "git", "checkout": str(checkout)}}}
        runtime._save_state = lambda: None
        git_attempts = 0

        def failed_git_run(args, **_kwargs):
            nonlocal git_attempts
            git_attempts += 1
            raise subprocess.CalledProcessError(1, args, stderr="synthetic network reset")

        with patch.object(plugin_runtime_module.subprocess, "run", failed_git_run), \
             patch.object(plugin_runtime_module.time, "sleep", lambda _delay: None):
            assert runtime.check_updates() == {"offline-plugin": False}
        assert git_attempts == 3
        assert "已重试 2 次" in runtime._state["sources"]["offline-plugin"]["update_error"]


def check_plugin_update_error_surface() -> None:
    class FakeRuntime:
        def check_updates(self):
            return {"offline-plugin": False}

        def discover(self):
            return [{"name": "offline-plugin", "version": "1.0.0", "enabled": True, "loaded": False,
                     "update_available": False, "update_error": "Git 来源更新检查失败（已重试 2 次）：请检查网络、代理或仓库权限。"}]

    app = FastAPI()
    app.state.services = AppServices(plugin_runtime=FakeRuntime())
    app.include_router(plugins_router.router)
    client = TestClient(app, client=("127.0.0.1", 12345))
    response = client.post("/api/plugins/check-updates")
    assert response.status_code == 200, response.text
    assert "update_error" in response.json()["plugins"][0]
    assert response.json()["updates"] == {"offline-plugin": False}


def check_local_plugin_git() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_plugins.py::test_git_source_update_available"],
        cwd=CORE, env={**os.environ, "ATLAS_ROOT": str(ROOT / ".u42-test-root")},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def check_mobile_and_deep_link() -> None:
    app_tsx = (ROOT / "frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    mobile = (ROOT / "frontend/src/renderer/components/settings/MobileEntryPanel.tsx").read_text(encoding="utf-8")
    sidebar = (ROOT / "frontend/src/renderer/shell/Sidebar.tsx").read_text(encoding="utf-8")
    electron = (ROOT / "frontend/src/main/electron.ts").read_text(encoding="utf-8")
    assert "mobile" in app_tsx and "MobileEntryPanel" in app_tsx
    assert "没有已发布的 Atlas 原生 Android/iOS 应用" in mobile
    assert "telegram" in mobile.lower() and "二维码" in mobile
    assert "复制 Atlas 深层链接" in sidebar and "atlas://conversation/" in sidebar
    assert "receiveAtlasDeepLink" in electron and "url.protocol !== 'atlas:'" in electron
    deep_link = "atlas://conversation/" + "9d4c966d-75c2-42b3-83cd-07d300a68672"
    assert re.fullmatch(r"atlas://conversation/[0-9a-f-]{36}", deep_link)


def check_vm_limitation() -> None:
    """Exercise the real host capability probe and prevent a false VM claim."""
    probe = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "try { $vm='accessible:'+(@(Get-VM -ErrorAction Stop).Count) } catch { $vm='blocked' }; "
                            "$sandbox=Test-Path $env:WINDIR\\System32\\WindowsSandbox.exe; "
                            "$dockerVersion=& docker info --format '{{.ServerVersion}}' 2>$null; "
                            "if ($LASTEXITCODE -eq 0) { $docker='accessible:'+$dockerVersion } else { $docker='unavailable' }; "
                            "'hyperv='+$vm+' sandbox='+$sandbox+' docker='+$docker"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    assert probe.returncode == 0, probe.stderr
    files_panel = (ROOT / "frontend/src/renderer/shell/panels/FilesPanel.tsx").read_text(encoding="utf-8")
    assert "虚拟机隔离渲染" not in files_panel
    print("ITEM 1 LIMITATION: host probe=" + probe.stdout.strip() + "; no VM preview is claimed")


def main() -> None:
    check_vm_limitation()
    check_cli()
    check_dns()
    check_mobile_and_deep_link()
    check_portal()
    check_network_retry()
    check_plugin_update_error_surface()
    check_local_plugin_git()
    print("U42 CHECK PASS")


if __name__ == "__main__":
    main()
