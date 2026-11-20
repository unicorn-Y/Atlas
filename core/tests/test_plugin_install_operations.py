from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from atlas.plugins.runtime import PluginRuntime

pytestmark = pytest.mark.unit


def _local_package(tmp_path: Path, *, dependencies: dict[str, str] | None = None) -> Path:
    root = tmp_path / "source" / "fixture-plugin"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": "fixture-plugin", "version": "1.0.0"}), encoding="utf-8")
    (root / "package.json").write_text(json.dumps({
        "name": "fixture-plugin", "version": "1.0.0", "dependencies": dependencies or {},
    }), encoding="utf-8")
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    return root


def test_install_source_classifier_keeps_scoped_npm_specs_out_of_git_shorthand(tmp_path: Path) -> None:
    runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
    assert runtime._infer_install_source_type("@scope/plugin") == "npm"
    assert runtime._infer_install_source_type("@scope/plugin@^2.1") == "npm"
    assert runtime._infer_install_source_type("npm:@scope/plugin@~1") == "npm"
    assert runtime._infer_install_source_type("owner/repository") == "git"
    assert runtime._infer_install_source_type("https://example.invalid/plugin.git") == "git"
    assert runtime._infer_install_source_type(str(_local_package(tmp_path))) == "local"


def test_git_fixture_installs_through_request_task_and_persists_checkout(tmp_path: Path) -> None:
    import subprocess

    async def scenario() -> None:
        source = _local_package(tmp_path)
        subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "atlas-test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Atlas test"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "plugin.json", "package.json", "pnpm-lock.yaml"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        started = await runtime.start_install_operation(str(source), source_type="git", ref="main")
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=15)
        assert result["status"] == "completed", result
        assert (tmp_path / "installed" / "fixture-plugin" / "plugin.json").is_file()
        record = runtime._state["sources"]["fixture-plugin"]
        assert record["source"] == "git"
        assert Path(record["checkout"]).is_dir()
        assert (Path(record["checkout"]) / ".git").is_dir()
        await runtime.close_install_operations()

    asyncio.run(scenario())


def test_git_manifest_identity_is_repo_slug_for_reinstall_and_contribution_validation(tmp_path: Path) -> None:
    import subprocess

    async def scenario() -> None:
        source = tmp_path / "repo-a"
        source.mkdir()
        (source / "plugin.json").write_text(json.dumps({
            "name": "plugin-b", "version": "1.0.0", "commands": ["commands"],
        }), encoding="utf-8")
        (source / "commands").mkdir()
        (source / "commands" / "hello.md").write_text("---\ndescription: hello\n---\nhello", encoding="utf-8")
        (source / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "fixture": {"command": "node", "args": ["fixture.js"]},
        }}), encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "atlas-test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Atlas test"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        for _ in range(2):
            started = await runtime.start_install_operation(str(source), source_type="git", ref="main")
            result = await runtime.wait_install_operation(started["requestId"], wait_seconds=15)
            assert result["status"] == "completed", {key: result.get(key) for key in ("status", "phase", "error", "failureType", "rollback")}
        plugins = runtime.discover()
        assert [item["name"] for item in plugins if item["installed"]] == ["repo-a"]
        contributions = runtime.enabled_contributions()
        assert any(path.endswith("commands") for item in contributions for path in item.get("command_sources", []))
        assert any("fixture" in item.get("mcp_servers", {}) for item in contributions)
        await runtime.close_install_operations()

    asyncio.run(scenario())


def test_install_upgrade_preserves_old_patch_and_revert_restores_new_upstream(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = _local_package(tmp_path)
        commands = source / "commands"
        commands.mkdir()
        command = commands / "hello.md"
        command.write_text("upstream v1", encoding="utf-8")
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        first = await runtime.start_install_operation(str(source))
        assert (await runtime.wait_install_operation(first["requestId"], wait_seconds=5))["status"] == "completed"
        assert runtime.patch_file("fixture-plugin", "commands/hello.md", "local patch")
        command.write_text("upstream v2", encoding="utf-8")
        second = await runtime.start_install_operation(str(source))
        result = await runtime.wait_install_operation(second["requestId"], wait_seconds=5)
        assert result["status"] == "completed", result
        installed_command = tmp_path / "installed" / "fixture-plugin" / "commands" / "hello.md"
        assert installed_command.read_text(encoding="utf-8") == "local patch"
        assert runtime.revert_patch("fixture-plugin", "commands/hello.md")["reverted"] is True
        assert installed_command.read_text(encoding="utf-8") == "upstream v2"
        await runtime.close_install_operations()

    asyncio.run(scenario())


def test_first_install_refresh_failure_removes_target_source_and_enabled_state(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = _local_package(tmp_path)
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")

        def fail_refresh():
            raise RuntimeError("fixture refresh failure")

        started = await runtime.start_install_operation(str(source), on_complete=fail_refresh)
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=5)
        assert result["status"] == "failed"
        assert not (tmp_path / "installed" / "fixture-plugin").exists()
        assert "fixture-plugin" not in runtime._state.get("sources", {})
        assert "fixture-plugin" not in runtime._enabled
        assert not any(plugin["name"] == "fixture-plugin" for plugin in runtime.discover())
        await runtime.close_install_operations()

    asyncio.run(scenario())


def test_marketplace_api_installs_via_waitable_request_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.api import plugins_router
    from atlas.api.app_services import AppServices

    source = tmp_path / "marketplace-plugin-source"
    source.mkdir()
    (source / "plugin.json").write_text(json.dumps({"name": "fixture-plugin", "version": "1.0.0"}), encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "config", "user.email", "atlas-test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Atlas test"], check=True)
    subprocess.run(["git", "-C", str(source), "add", "plugin.json"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
    marketplace = tmp_path / "market"
    marketplace.mkdir()
    (marketplace / "marketplace.json").write_text(json.dumps({"plugins": [{
        "name": "fixture-plugin", "source": {"source": "url", "url": str(source), "ref": "main"},
    }]}), encoding="utf-8")
    runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
    runtime.add_marketplace(marketplace, name="fixture-market")

    async def refresh():
        return {"loaded": ["fixture-plugin"]}

    monkeypatch.setattr(plugins_router._server(), "_reload_extensions", refresh)
    app = FastAPI()
    app.state.services = AppServices(plugin_runtime=runtime)
    app.include_router(plugins_router.router)
    with TestClient(app) as client:
        started_response = client.post("/api/plugin-marketplaces/fixture-market/install", json={
            "plugin": "fixture-plugin", "requestId": "marketplace-install-1",
        })
        assert started_response.status_code == 200, started_response.text
        started = started_response.json()
        assert started["requestId"] == "marketplace-install-1"
        assert started["status"] in {"queued", "running"}
        assert "result" not in started
        result = client.get("/api/plugins/install/marketplace-install-1?wait_ms=2000").json()
        assert result["status"] == "completed", result
        assert result["report"] == {"loaded": ["fixture-plugin"]}
        assert (tmp_path / "installed" / "fixture-plugin" / "plugin.json").is_file()
        assert (tmp_path / "installed" / ".sources" / "fixture-plugin" / ".git").is_dir()
        assert runtime._state["sources"]["fixture-plugin"]["source"] == "marketplace"


@pytest.mark.parametrize("source_type", ["git", "npm", "marketplace"])
def test_remote_source_fetch_cancellation_finishes_request_and_cleans_workspace(
    tmp_path: Path, source_type: str,
) -> None:
    async def scenario() -> None:
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        if source_type == "marketplace":
            market = tmp_path / "market"
            market.mkdir()
            (market / "marketplace.json").write_text(json.dumps({"plugins": [{
                "name": "fixture-plugin", "source": {"source": "url", "url": "fixture-remote.git"},
            }]}), encoding="utf-8")
            runtime.add_marketplace(market, name="market")
        entered = asyncio.Event()
        workspace_paths: list[Path] = []

        async def blocked_git(_request_id: str, _url: str, target: Path, *, ref: str | None = None):
            workspace_paths.append(target.parent)
            entered.set()
            await runtime._install_cancel_events[_request_id].wait()
            return -1, ""

        async def blocked_npm(_request_id: str, _spec: str, cwd: Path, _registry: str | None):
            workspace_paths.append(cwd)
            entered.set()
            await runtime._install_cancel_events[_request_id].wait()
            return -1, ""

        runtime._run_git_clone_operation = blocked_git
        runtime._run_npm_pack = blocked_npm
        if source_type == "marketplace":
            started = await runtime.start_install_operation(
                "marketplace:market/fixture-plugin", source_type="marketplace",
                marketplace="market", plugin_name="fixture-plugin",
            )
        else:
            source = "@fixture/plugin@1.0.0" if source_type == "npm" else "owner/repository"
            started = await runtime.start_install_operation(source, source_type=source_type)
        await asyncio.wait_for(entered.wait(), timeout=3)
        cancelled = await runtime.cancel_install_operation(started["requestId"])
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=1)
        assert cancelled["status"] == "cancelled"
        assert result["status"] == "cancelled", result
        assert workspace_paths and all(not path.exists() for path in workspace_paths)
        await runtime.close_install_operations()

    asyncio.run(scenario())


@pytest.mark.skipif(os.name != "nt", reason="the process-tree assertion exercises Windows taskkill /T")
def test_git_source_cancel_terminates_real_managed_process_tree(tmp_path: Path) -> None:
    import ctypes
    from ctypes import wintypes
    import sys

    async def scenario() -> None:
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        child_ready = tmp_path / "source-child.ready"
        child_script = f"import os,time; open({str(child_ready)!r},'w').write(str(os.getpid())); time.sleep(60)"
        command = (
            "import subprocess,sys,time; "
            f"child=subprocess.Popen([sys.executable,'-c',{child_script!r}]); "
            "print(child.pid,flush=True); time.sleep(60)"
        )

        async def managed_source(request_id: str, _url: str, target: Path, *, ref: str | None = None):
            return await runtime._run_managed_command(
                request_id, target.parent, [sys.executable, "-c", command],
                {"PATH": os.environ.get("PATH", ""), "SystemRoot": os.environ.get("SystemRoot", "")},
                timeout=20,
            )

        runtime._run_git_clone_operation = managed_source
        started = await runtime.start_install_operation("owner/repository", source_type="git")
        request_id = started["requestId"]
        deadline = asyncio.get_running_loop().time() + 5
        while request_id not in runtime._install_processes:
            assert asyncio.get_running_loop().time() < deadline, "source child process did not start"
            await asyncio.sleep(0.01)
        managed_process = runtime._install_processes[request_id]
        process_api = ctypes.WinDLL("kernel32", use_last_error=True)
        process_api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        process_api.OpenProcess.restype = wintypes.HANDLE
        process_api.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        process_api.GetExitCodeProcess.restype = wintypes.BOOL
        process_api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        process_api.WaitForSingleObject.restype = wintypes.DWORD
        process_api.CloseHandle.argtypes = (wintypes.HANDLE,)
        process_api.CloseHandle.restype = wintypes.BOOL
        child_handle = None
        try:
            ready_deadline = asyncio.get_running_loop().time() + 5
            while not child_ready.is_file():
                assert asyncio.get_running_loop().time() < ready_deadline, "source child did not complete its ready handshake"
                await asyncio.sleep(0.02)
            child_pid = int(child_ready.read_text(encoding="utf-8"))
            query_limited_information = 0x1000
            synchronize = 0x00100000
            child_handle = process_api.OpenProcess(query_limited_information | synchronize, False, child_pid)
            assert child_handle, f"OpenProcess failed with WinError {ctypes.get_last_error()}"
            exit_code = wintypes.DWORD()
            assert process_api.GetExitCodeProcess(child_handle, ctypes.byref(exit_code))
            assert exit_code.value == 259, f"child was not active before cancel: {exit_code.value}"
            assert process_api.WaitForSingleObject(child_handle, 0) == 0x102, "child was already signaled before cancel"

            cancelled = await asyncio.wait_for(runtime.cancel_install_operation(request_id), timeout=8)
            result = await runtime.wait_install_operation(request_id, wait_seconds=0)
            assert cancelled["status"] == "cancelled"
            assert result["status"] == "cancelled", result
            assert managed_process.returncode is not None
            assert request_id not in runtime._install_processes
            wait_deadline = asyncio.get_running_loop().time() + 5
            wait_result = process_api.WaitForSingleObject(child_handle, 0)
            while wait_result == 0x102:
                assert asyncio.get_running_loop().time() < wait_deadline, "source child survived process-tree cancellation"
                await asyncio.sleep(0.05)
                wait_result = process_api.WaitForSingleObject(child_handle, 0)
            assert wait_result == 0, f"unexpected WaitForSingleObject result: {wait_result:#x}"
            assert process_api.GetExitCodeProcess(child_handle, ctypes.byref(exit_code))
            assert exit_code.value != 259
        finally:
            if child_handle:
                process_api.CloseHandle(child_handle)
            if not runtime._install_done_events.get(request_id, asyncio.Event()).is_set():
                # Cleanup is only for this test's own process tree; it is not
                # considered cancellation evidence if the assertions above fail.
                await runtime.cancel_install_operation(request_id)
        await runtime.close_install_operations()

    asyncio.run(scenario())


@pytest.mark.parametrize("source_type", ["git", "marketplace"])
def test_git_and_marketplace_sources_share_dependency_approval_request_lifecycle(
    tmp_path: Path, source_type: str,
) -> None:
    import subprocess

    async def scenario() -> None:
        source = tmp_path / "approval-source"
        source.mkdir()
        (source / "plugin.json").write_text(json.dumps({"name": "approval-plugin", "version": "1.0.0"}), encoding="utf-8")
        (source / "package.json").write_text(json.dumps({
            "name": "approval-plugin", "version": "1.0.0", "dependencies": {"direct-dep": "1.0.0"},
        }), encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "atlas-test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Atlas test"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        if source_type == "marketplace":
            market = tmp_path / "market"
            market.mkdir()
            (market / "marketplace.json").write_text(json.dumps({"plugins": [{
                "name": "approval-plugin", "source": {"source": "url", "url": str(source), "ref": "main"},
            }]}), encoding="utf-8")
            runtime.add_marketplace(market, name="approval-market")
        calls = 0

        async def pnpm(_request_id: str, _cwd: Path, _registry: str | None, _args: list[str]):
            nonlocal calls
            calls += 1
            if calls == 1:
                return 1, "ERR_PNPM_IGNORED_BUILDS\nIgnored build scripts: @fixture/approved-build@1.0.0"
            return 0, "approved build completed"

        runtime._run_package_manager = pnpm
        if source_type == "marketplace":
            started = await runtime.start_install_operation(
                "marketplace:approval-market/approval-plugin", source_type="marketplace",
                marketplace="approval-market", plugin_name="approval-plugin",
            )
        else:
            started = await runtime.start_install_operation(str(source), source_type="git", ref="main")
        deadline = asyncio.get_running_loop().time() + 10
        pending = await runtime.wait_install_operation(started["requestId"], wait_seconds=0)
        while pending["status"] not in {"awaiting_approval", "failed", "completed"}:
            assert asyncio.get_running_loop().time() < deadline, pending
            await asyncio.sleep(0.02)
            pending = await runtime.wait_install_operation(started["requestId"], wait_seconds=0)
        assert pending["status"] == "awaiting_approval", pending
        assert pending["approvalRequired"] == ["@fixture/approved-build"]
        assert calls == 1
        runtime.grant_script_approval(
            "@fixture/approved-build", request_id=started["requestId"],
            expires_at="2099-01-01T00:00:00Z",
        )
        deadline = asyncio.get_running_loop().time() + 10
        completed = await runtime.wait_install_operation(started["requestId"], wait_seconds=0)
        while completed["status"] not in {"completed", "failed", "cancelled"}:
            assert asyncio.get_running_loop().time() < deadline, completed
            await asyncio.sleep(0.02)
            completed = await runtime.wait_install_operation(started["requestId"], wait_seconds=0)
        assert completed["status"] == "completed", completed
        assert calls == 2
        installed_name = "approval-plugin" if source_type == "marketplace" else "approval-source"
        assert (tmp_path / "installed" / installed_name / "plugin.json").is_file()
        assert completed["executedBuildPackages"] == ["@fixture/approved-build"]
        await runtime.close_install_operations()

    asyncio.run(scenario())


def test_scoped_npm_tarball_installs_from_local_registry_through_request_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import shutil
    import tarfile
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
        files = {
            "package/package.json": json.dumps({"name": "@fixture/npm-plugin", "version": "1.0.0"}).encode(),
            "package/plugin.json": json.dumps({"name": "npm-fixture-plugin", "version": "1.0.0"}).encode(),
        }
        for name, payload in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    archive_bytes = archive_buffer.getvalue()

    class RegistryHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.lower().startswith("/@fixture%2f") or self.path.lower().startswith("/@fixture/"):
                metadata = {"name": "@fixture/npm-plugin", "dist-tags": {"latest": "1.0.0"}, "versions": {
                    "1.0.0": {"name": "@fixture/npm-plugin", "version": "1.0.0", "dist": {
                        "tarball": f"http://127.0.0.1:{self.server.server_port}/tarball.tgz",
                    }}
                }}
                payload = json.dumps(metadata).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/tarball.tgz":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(archive_bytes)))
                self.end_headers()
                self.wfile.write(archive_bytes)
            else:
                self.send_error(404)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RegistryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    npm_cmd = shutil.which("npm")
    assert npm_cmd, "npm command must be installed for the real scoped registry probe"
    npm_entry = Path(npm_cmd).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not npm_entry.is_file():
        # npm can be a shim beside a separately installed Node distribution.
        node = shutil.which("node")
        assert node
        npm_entry = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    assert npm_entry.is_file(), npm_entry
    monkeypatch.setenv("ATLAS_NPM_ENTRY", str(npm_entry))

    async def scenario() -> None:
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        registry = f"http://127.0.0.1:{server.server_port}/"
        started = await runtime.start_install_operation(
            "@fixture/npm-plugin@1.0.0", registry=registry, source_type="npm",
        )
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=30)
        assert result["status"] == "completed", result
        assert (tmp_path / "installed" / "npm-fixture-plugin" / "plugin.json").is_file()
        assert runtime._state["sources"]["npm-fixture-plugin"]["source"] == "npm"
        await runtime.close_install_operations()

    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_install_operation_reports_unknown_cancelled_and_too_late(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        assert await runtime.wait_install_operation("missing-id", wait_seconds=0) == {"requestId": "missing-id", "status": "unknown"}
        assert await runtime.cancel_install_operation("missing-id") == {"requestId": "missing-id", "status": "unknown"}

        source = _local_package(tmp_path)
        started = await runtime.start_install_operation(str(source))
        cancelled = await runtime.cancel_install_operation(started["requestId"])
        assert cancelled["status"] == "cancelled"
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=2)
        assert result["status"] == "cancelled"
        assert not (tmp_path / "installed" / "fixture-plugin").exists()
        assert (await runtime.cancel_install_operation(started["requestId"]))["status"] == "too_late"

    asyncio.run(scenario())


def test_install_request_id_survives_runtime_restart_without_replaying_install(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = tmp_path / "state.json"
        source = _local_package(tmp_path)
        first = PluginRuntime([tmp_path / "installed"], state)
        started = await first.start_install_operation(str(source), request_id="persisted-request")
        assert (await first.wait_install_operation(started["requestId"], wait_seconds=2))["status"] == "completed"

        restarted = PluginRuntime([tmp_path / "installed"], state)
        status = await restarted.wait_install_operation("persisted-request", wait_seconds=0)
        assert status == {"requestId": "persisted-request", "status": "unknown", "previousRuntime": True}
        with pytest.raises(ValueError, match="earlier runtime"):
            await restarted.start_install_operation(str(source), request_id="persisted-request")
        assert restarted._install_tasks == {}
        await first.close_install_operations()
        await restarted.close_install_operations()

    asyncio.run(scenario())


def test_failed_package_install_discards_staging_and_restores_lockfiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        source = _local_package(tmp_path, dependencies={"@fixture/dep": "file:../dep"})

        seen: list[tuple[str | None, list[str]]] = []

        async def fail_after_mutation(_request_id: str, cwd: Path, registry: str | None, args: list[str]) -> tuple[int, str]:
            seen.append((registry, args))
            (cwd / "pnpm-lock.yaml").write_text("partially-written\n", encoding="utf-8")
            return 17, "fixture failure"

        monkeypatch.setattr(runtime, "_run_package_manager", fail_after_mutation)
        started = await runtime.start_install_operation(str(source), registry="http://127.0.0.1:9/private")
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=2)
        assert result["status"] == "failed"
        assert result["error"] == "package_manager_failed"
        assert not (tmp_path / "installed" / "fixture-plugin").exists()
        assert not list((tmp_path / "installed").glob(".transactions/*"))
        assert (source / "pnpm-lock.yaml").read_text(encoding="utf-8") == "lockfileVersion: '9.0'\n"
        assert result["rollback"] == ["package.json", "pnpm-lock.yaml"]
        assert seen[0][0] == "http://127.0.0.1:9/private"
        assert "registry.npmjs.org" not in " ".join(seen[0][1])

    asyncio.run(scenario())


def test_script_approval_is_persisted_per_package_and_expires(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = tmp_path / "state.json"
        runtime = PluginRuntime([tmp_path / "installed"], state)
        source = _local_package(tmp_path, dependencies={"direct-dep": "1.0.0"})

        calls = 0
        async def runner(_request_id: str, _cwd: Path, _registry: str | None, args: list[str]) -> tuple[int, str]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return 1, "ERR_PNPM_IGNORED_BUILDS\nIgnored build scripts: @fixture/native-addon@1.2.3"
            return 0, "approved build executed"

        runtime._run_package_manager = runner
        started = await runtime.start_install_operation(str(source))
        pending = await runtime.wait_install_operation(started["requestId"], wait_seconds=2)
        assert pending["status"] == "awaiting_approval"
        with pytest.raises(ValueError, match="stale"):
            runtime.grant_script_approval(
                "@fixture/other", expires_at="2099-01-01T00:00:00Z", request_id=started["requestId"],
            )
        runtime.grant_script_approval(
            "@fixture/native-addon", expires_at="2099-01-01T00:00:00Z", request_id=started["requestId"],
        )
        restored = PluginRuntime([], state)
        assert restored.script_approval_status("@fixture/native-addon") == "approved"
        assert restored.script_approval_status("@fixture/other") == "not_approved"
        assert restored.script_approval_status("@fixture/native-addon", now="2100-01-01T00:00:00Z") == "expired"
        with pytest.raises(ValueError, match="stale"):
            runtime.grant_script_approval(
                "@fixture/native-addon", expires_at="2099-01-01T00:00:00Z", request_id="unknown-request",
            )
        await runtime.close_install_operations()

    asyncio.run(scenario())


def test_process_tree_termination_shares_the_install_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    class StuckKiller:
        async def wait(self) -> int:
            await asyncio.Event().wait()
            return 0

    class RunningProcess:
        pid = 12345
        returncode = None

        async def wait(self) -> int:
            await asyncio.Event().wait()
            return 0

        def kill(self) -> None:
            pass

    async def scenario() -> None:
        async def create_killer(*_args: object, **_kwargs: object) -> StuckKiller:
            return StuckKiller()

        monkeypatch.setattr("atlas.plugins.runtime.os.name", "nt")
        monkeypatch.setattr("atlas.plugins.runtime.asyncio.create_subprocess_exec", create_killer)
        deadline = asyncio.get_running_loop().time() + 0.05
        task = asyncio.create_task(PluginRuntime._terminate_install_process_tree(RunningProcess(), deadline=deadline))
        done, _ = await asyncio.wait({task}, timeout=0.2)
        assert task in done, "process-tree termination escaped its shared deadline"
        with pytest.raises(asyncio.TimeoutError):
            await task

    asyncio.run(scenario())


def test_legacy_uninstall_holds_mutation_claim_against_new_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        installed = tmp_path / "installed"
        old = installed / "fixture-plugin"
        old.mkdir(parents=True)
        (old / "plugin.json").write_text(json.dumps({"name": "fixture-plugin", "version": "1.0.0"}), encoding="utf-8")
        runtime = PluginRuntime([installed], tmp_path / "state.json")
        source = _local_package(tmp_path)
        entered = threading.Event()
        release = threading.Event()
        original_rmtree = PluginRuntime._rmtree

        def paused_rmtree(path: Path) -> None:
            if Path(path) == old:
                entered.set()
                assert release.wait(2)
            original_rmtree(path)

        monkeypatch.setattr(PluginRuntime, "_rmtree", staticmethod(paused_rmtree))
        deleting = asyncio.create_task(asyncio.to_thread(runtime.uninstall, "fixture-plugin"))
        assert await asyncio.to_thread(entered.wait, 2)
        started = await runtime.start_install_operation(str(source))
        failed = await runtime.wait_install_operation(started["requestId"], wait_seconds=2)
        release.set()
        assert await deleting is True
        assert failed["status"] == "failed"
        assert not old.exists()
        assert not (installed / "fixture-plugin").exists()

    import threading
    asyncio.run(scenario())


def test_private_registry_is_used_without_public_registry_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        source = _local_package(tmp_path, dependencies={"@fixture/dep": "file:../dep"})
        seen: list[tuple[str | None, list[str]]] = []

        async def succeed(_request_id: str, _cwd: Path, registry: str | None, args: list[str]) -> tuple[int, str]:
            seen.append((registry, args))
            return 0, "ok"

        monkeypatch.setattr(runtime, "_run_package_manager", succeed)
        started = await runtime.start_install_operation(str(source), registry="https://packages.example.invalid/npm/")
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=2)
        assert result["status"] == "completed"
        assert len(seen) == 1
        assert all(registry == "https://packages.example.invalid/npm/" for registry, _ in seen)
        assert all("registry.npmjs.org" not in " ".join(args) for _, args in seen)
        assert [args[0] for _, args in seen] == ["install"]

    asyncio.run(scenario())


def test_install_waits_only_for_pnpm_reported_transitive_build_and_resumes_on_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        source = _local_package(tmp_path, dependencies={"direct-dep": "1.0.0"})
        ran: list[str] = []

        async def runner(_request_id: str, _cwd: Path, _registry: str | None, args: list[str]) -> tuple[int, str]:
            ran.append(args[0])
            if len(ran) == 1:
                return 1, "ERR_PNPM_IGNORED_BUILDS\nIgnored build scripts: @transitive/native-build@2.0.0"
            return 0, "ok"

        monkeypatch.setattr(runtime, "_run_package_manager", runner)
        started = await runtime.start_install_operation(str(source))
        for _ in range(100):
            status = await runtime.wait_install_operation(started["requestId"], wait_seconds=0)
            if status["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.01)
        assert status["status"] == "awaiting_approval"
        assert status["approvalRequired"] == ["@transitive/native-build"]
        assert ran == ["install"]
        runtime.grant_script_approval("@transitive/native-build", expires_at="2099-01-01T00:00:00Z", request_id=started["requestId"])
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=2)
        assert result["status"] == "completed"
        assert ran == ["install", "install"]

    asyncio.run(scenario())


def test_shutdown_drain_cancels_install_waiting_for_build_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")
        source = _local_package(tmp_path, dependencies={"direct-dep": "1.0.0"})

        async def runner(_request_id: str, _cwd: Path, _registry: str | None, args: list[str]) -> tuple[int, str]:
            return 1, "ERR_PNPM_IGNORED_BUILDS\nIgnored build scripts: @transitive/native-build@2.0.0"

        monkeypatch.setattr(runtime, "_run_package_manager", runner)
        started = await runtime.start_install_operation(str(source))
        for _ in range(100):
            result = await runtime.wait_install_operation(started["requestId"], wait_seconds=0)
            if result["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.01)
        await runtime.close_install_operations()
        assert (await runtime.wait_install_operation(started["requestId"], wait_seconds=0))["status"] == "cancelled"
        assert not list((tmp_path / "installed").glob(".transactions/*"))

    asyncio.run(scenario())


def test_failed_second_install_rename_restores_previous_target_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        installed = tmp_path / "installed"
        old_target = installed / "fixture-plugin"
        old_target.mkdir(parents=True)
        (old_target / "old.bin").write_bytes(b"existing plugin bytes\x00\x01")
        runtime = PluginRuntime([installed], tmp_path / "state.json")
        source = _local_package(tmp_path)
        original_replace = Path.replace
        fail_once = True

        def fail_prepared_promotion(path: Path, target: str | Path) -> Path:
            nonlocal fail_once
            if fail_once and ".prepared-" in path.name and Path(target) == old_target:
                fail_once = False
                raise OSError("fixture second rename failure")
            return original_replace(path, target)

        monkeypatch.setattr(Path, "replace", fail_prepared_promotion)
        started = await runtime.start_install_operation(str(source))
        result = await runtime.wait_install_operation(started["requestId"], wait_seconds=2)
        assert result["status"] == "failed"
        assert (old_target / "old.bin").read_bytes() == b"existing plugin bytes\x00\x01"
        assert not list(installed.glob(".transactions/*"))
        assert not list(installed.glob(".*.prepared-*"))

    asyncio.run(scenario())


def test_real_pnpm_blocks_transitive_script_until_scoped_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote, urlsplit
    import tarfile
    import shutil
    import threading

    async def scenario() -> None:
        pnpm_entry = os.environ.get("ATLAS_PNPM_ENTRY")
        assert pnpm_entry and Path(pnpm_entry).is_file(), "real pnpm entry must be supplied for this local integration test"
        postinstall_marker = tmp_path / "postinstall-ran.marker"
        pnpmfile_marker = tmp_path / "pnpmfile-ran.marker"
        source = _local_package(tmp_path, dependencies={"direct-dep": "1.0.0"})
        (source / "pnpm-lock.yaml").unlink()
        direct = tmp_path / "registry-fixtures" / "direct-dep"
        native = tmp_path / "registry-fixtures" / "native-build"
        direct.mkdir(parents=True)
        native.mkdir(parents=True)
        (direct / "package.json").write_text(json.dumps({
            "name": "direct-dep", "version": "1.0.0",
            "dependencies": {"@fixture/native-build": "1.0.0"},
        }), encoding="utf-8")
        (native / "package.json").write_text(json.dumps({
            "name": "@fixture/native-build", "version": "1.0.0",
            "scripts": {"postinstall": "node write-marker.js"},
        }), encoding="utf-8")
        (native / "write-marker.js").write_text(
            f"require('fs').writeFileSync({json.dumps(str(postinstall_marker))}, 'executed')\n", encoding="utf-8",
        )
        (source / ".pnpmfile.cjs").write_text(
            f"require('fs').writeFileSync({json.dumps(str(pnpmfile_marker))}, 'executed'); module.exports = {{}}\n",
            encoding="utf-8",
        )
        (source / "pnpm-workspace.yaml").write_text(
            "packages: []\npnpmfile: ./.pnpmfile.cjs\ndangerouslyAllowAllBuilds: true\nallowBuilds:\n  '@fixture/native-build': true\n",
            encoding="utf-8",
        )
        package_manifest = json.loads((source / "package.json").read_text(encoding="utf-8"))
        package_manifest["pnpm"] = {
            "dangerouslyAllowAllBuilds": True,
            "allowBuilds": {"@fixture/native-build": True},
        }
        (source / "package.json").write_text(json.dumps(package_manifest), encoding="utf-8")

        def pack(root: Path, destination: Path) -> bytes:
            with tarfile.open(destination, "w:gz") as archive:
                for file in sorted(root.rglob("*")):
                    if file.is_file():
                        archive.add(file, arcname=f"package/{file.relative_to(root).as_posix()}")
            return destination.read_bytes()

        direct_tarball = pack(direct, tmp_path / "direct-dep-1.0.0.tgz")
        native_tarball = pack(native, tmp_path / "native-build-1.0.0.tgz")
        npm_plugin_tarball = pack(source, tmp_path / "npm-plugin-1.0.0.tgz")
        requests: list[str] = []
        server_holder: dict[str, ThreadingHTTPServer] = {}

        class RegistryHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = unquote(urlsplit(self.path).path)
                requests.append(route)
                server = server_holder["server"]
                base_url = f"http://127.0.0.1:{server.server_port}"
                if route == "/@fixture/npm-plugin":
                    body = json.dumps({"name": "@fixture/npm-plugin", "dist-tags": {"latest": "1.0.0"}, "versions": {
                        "1.0.0": {"name": "@fixture/npm-plugin", "version": "1.0.0",
                                  "dependencies": {"direct-dep": "1.0.0"},
                                  "dist": {"tarball": f"{base_url}/npm-plugin-1.0.0.tgz"}},
                    }}).encode()
                elif route == "/npm-plugin-1.0.0.tgz":
                    body = npm_plugin_tarball
                elif route == "/direct-dep":
                    body = json.dumps({"name": "direct-dep", "dist-tags": {"latest": "1.0.0"}, "versions": {
                        "1.0.0": {"name": "direct-dep", "version": "1.0.0",
                                  "dependencies": {"@fixture/native-build": "1.0.0"},
                                  "dist": {"tarball": f"{base_url}/direct-dep-1.0.0.tgz"}},
                    }}).encode()
                elif route == "/@fixture/native-build":
                    body = json.dumps({"name": "@fixture/native-build", "dist-tags": {"latest": "1.0.0"}, "versions": {
                        "1.0.0": {"name": "@fixture/native-build", "version": "1.0.0",
                                  "scripts": {"postinstall": "node write-marker.js"},
                                  "dist": {"tarball": f"{base_url}/native-build-1.0.0.tgz"}},
                    }}).encode()
                elif route == "/direct-dep-1.0.0.tgz":
                    body = direct_tarball
                elif route == "/native-build-1.0.0.tgz":
                    body = native_tarball
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream" if route.endswith(".tgz") else "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RegistryHandler)
        server_holder["server"] = server
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        registry = f"http://127.0.0.1:{server.server_port}/"
        npm_command = shutil.which("npm")
        assert npm_command, "npm command must be installed for the scoped source fixture"
        npm_entry = Path(npm_command).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if not npm_entry.is_file():
            node = shutil.which("node")
            assert node
            npm_entry = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        assert npm_entry.is_file(), npm_entry
        monkeypatch.setenv("ATLAS_NPM_ENTRY", str(npm_entry))

        padding = max(60, 170 - len(str(tmp_path)) - len("installed-root-"))
        installed = tmp_path / ("installed-root-" + "x" * padding)
        assert len(str(installed)) >= 170, "fixture must exercise an extended installation root"
        runtime = PluginRuntime([installed], tmp_path / "state.json")
        runtime._package_manager_timeout = 30
        real_runner = runtime._run_package_manager
        pnpm_output: list[tuple[list[str], int, str, list[str]]] = []
        pnpm_cwd_lengths: list[int] = []
        pnpm_policy: list[dict[str, object]] = []

        async def observe_pnpm(request_id: str, cwd: Path, registry: str | None, args: list[str]) -> tuple[int, str]:
            import yaml

            workspace_policy = yaml.safe_load((cwd / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
            package_policy = json.loads((cwd / "package.json").read_text(encoding="utf-8")).get("pnpm", {})
            pnpm_policy.append({
                "workspace_dangerous": workspace_policy.get("dangerouslyAllowAllBuilds"),
                "workspace_allowed": workspace_policy.get("allowBuilds", {}),
                "package_dangerous": package_policy.get("dangerouslyAllowAllBuilds"),
                "package_allowed": package_policy.get("allowBuilds", {}),
            })
            code, output = await real_runner(request_id, cwd, registry, args)
            pnpm_cwd_lengths.append(len(str(cwd)))
            node_modules = [str(path.relative_to(cwd)) for path in cwd.rglob("node_modules")]
            pnpm_output.append((args, code, output, node_modules))
            return code, output

        runtime._run_package_manager = observe_pnpm
        async def refresh():
            return {"loaded": []}

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from atlas.api import plugins_router
        from atlas.api.app_services import AppServices
        monkeypatch.setattr(plugins_router._server(), "_reload_extensions", refresh)
        app = FastAPI()
        app.state.services = AppServices(plugin_runtime=runtime)
        app.include_router(plugins_router.router)
        try:
            with TestClient(app) as client:
                started = client.post("/api/plugins/install", json={
                    "source": "@fixture/npm-plugin@1.0.0", "registry": registry,
                }).json()
                request_id = started["requestId"]
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    status = client.get(f"/api/plugins/install/{request_id}?wait_ms=250").json()
                    if status["status"] in {"awaiting_approval", "failed", "completed"}:
                        break
                assert status["status"] == "awaiting_approval", {
                    "status": status,
                    "pnpm": ascii([(args[0], code, output[-800:], paths) for args, code, output, paths in pnpm_output]),
                }
                assert status["approvalRequired"] == ["@fixture/native-build"]
                assert not postinstall_marker.exists()
                assert not pnpmfile_marker.exists()
                approved = client.post("/api/plugins/script-approvals", json={
                    "requestId": request_id, "packageName": "@fixture/native-build", "days": 30,
                })
                assert approved.status_code == 200
                while time.monotonic() < deadline:
                    result = client.get(f"/api/plugins/install/{request_id}?wait_ms=250").json()
                    if result["status"] in {"completed", "failed", "cancelled"}:
                        break
                print("REAL_PNPM_APPROVED_DIAGNOSTIC=" + ascii({
                    "result": result,
                    "error": result.get("error"), "rollback": result.get("rollback"),
                    "failureType": result.get("failureType"),
                    "pnpm_cwd_lengths": pnpm_cwd_lengths,
                    "host_policy": pnpm_policy,
                    "runs": [{"args": args, "exit": code, "output": output[-1200:], "node_modules": paths}
                             for args, code, output, paths in pnpm_output],
                    "postinstall_marker": postinstall_marker.exists(),
                    "pnpmfile_marker": pnpmfile_marker.exists(),
                }))
                assert result["status"] == "completed", {"result": result, "pnpm": pnpm_output}
                assert postinstall_marker.read_text(encoding="utf-8") == "executed"
                assert not pnpmfile_marker.exists()
                assert (installed / "fixture-plugin" / "pnpm-lock.yaml").is_file()
                assert all(length < 128 for length in pnpm_cwd_lengths), pnpm_cwd_lengths
                assert pnpm_policy == [
                    {"workspace_dangerous": False, "workspace_allowed": {}, "package_dangerous": False, "package_allowed": {}},
                    {"workspace_dangerous": False, "workspace_allowed": {"@fixture/native-build": True},
                     "package_dangerous": False, "package_allowed": {}},
                ], pnpm_policy
                assert len(str(installed / "fixture-plugin" / "node_modules" / ".pnpm" / "@fixture+native-build@1.0.0" / "node_modules" / "@fixture" / "native-build")) >= 260
                assert "/@fixture/npm-plugin" in requests
                assert "/npm-plugin-1.0.0.tgz" in requests
                assert all(path.startswith(("/@fixture/npm-plugin", "/npm-plugin-", "/direct-dep", "/@fixture/native-build", "/direct-dep-", "/native-build-")) for path in requests)
                assert [args[0] for args, _code, _output, _paths in pnpm_output] == ["install", "install"]
                print("REAL_PNPM_CAPTURE=" + ascii([
                    {"args": args, "exit": code, "output": output[-1200:]}
                    for args, code, output, _paths in pnpm_output
                ]))
                print(f"REAL_PNPM_MARKERS=postinstall:{postinstall_marker.read_text(encoding='utf-8')},pnpmfile:absent")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    asyncio.run(scenario())


def test_install_api_exposes_request_wait_unknown_cancel_and_script_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.api import plugins_router
    from atlas.api.app_services import AppServices

    source = _local_package(tmp_path)
    runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")

    async def refresh():
        return {"loaded": []}

    monkeypatch.setattr(plugins_router._server(), "_reload_extensions", refresh)
    app = FastAPI()
    app.state.services = AppServices(plugin_runtime=runtime)
    app.include_router(plugins_router.router)

    with TestClient(app) as client:
        started = client.post("/api/plugins/install", json={"source": str(source), "requestId": "stable-install-id"})
        assert started.status_code == 200
        request_id = started.json()["requestId"]
        retry = client.post("/api/plugins/install", json={"source": str(source), "requestId": "stable-install-id"})
        assert retry.status_code == 200
        assert retry.json()["requestId"] == request_id
        mismatch = client.post("/api/plugins/install", json={
            "source": str(source), "requestId": "stable-install-id", "registry": "https://different.example.invalid/",
        })
        assert mismatch.status_code == 400
        assert started.json()["status"] == "queued"
        assert "source" not in started.json()
        completed = client.get(f"/api/plugins/install/{request_id}?wait_ms=2000").json()
        assert completed["status"] == "completed"
        assert completed["report"] == {"loaded": []}
        assert client.post("/api/plugins/install/unknown/cancel").json()["status"] == "unknown"
        assert client.post("/api/plugins/script-approvals", json={
            "packageName": "@fixture/native-addon", "days": 30,
        }).status_code == 422


def test_script_approval_api_rejects_stale_request_and_resumes_current_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.api import plugins_router
    from atlas.api.app_services import AppServices

    source = _local_package(tmp_path, dependencies={"direct-dep": "1.0.0"})
    runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "state.json")

    calls = 0
    async def runner(_request_id: str, _cwd: Path, _registry: str | None, args: list[str]) -> tuple[int, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return 1, "ERR_PNPM_IGNORED_BUILDS\nIgnored build scripts: @transitive/native-build@1.0.0"
        return 0, "approved build executed"

    runtime._run_package_manager = runner

    async def refresh():
        return {"loaded": []}

    monkeypatch.setattr(plugins_router._server(), "_reload_extensions", refresh)
    app = FastAPI()
    app.state.services = AppServices(plugin_runtime=runtime)
    app.include_router(plugins_router.router)

    with TestClient(app) as client:
        started = client.post("/api/plugins/install", json={"source": str(source)}).json()
        request_id = started["requestId"]
        pending = client.get(f"/api/plugins/install/{request_id}?wait_ms=2000").json()
        assert pending["status"] == "awaiting_approval"
        removal = client.delete("/api/plugins/fixture-plugin")
        assert removal.status_code == 400
        assert "mutation already in progress" in removal.json()["detail"]
        stale = client.post("/api/plugins/script-approvals", json={
            "requestId": "old-request", "packageName": "@transitive/native-build", "days": 30,
        })
        assert stale.status_code == 422
        approved = client.post("/api/plugins/script-approvals", json={
            "requestId": request_id, "packageName": "@transitive/native-build", "days": 30,
        })
        assert approved.status_code == 200
        completed = client.get(f"/api/plugins/install/{request_id}?wait_ms=2000").json()
        assert completed["status"] == "completed"
