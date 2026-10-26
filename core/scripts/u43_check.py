"""Real-scenario checks for the U43 implementation batch; all peers bind to localhost."""
from __future__ import annotations

import socket
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import uvicorn

import atlas.cluster_control as cluster_control
from atlas.api import cluster_router
from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.runtime import RunState
from atlas.office import render_isolated_preview


def check_interactive_cli_and_private_bug_bundle() -> None:
    core = Path(__file__).resolve().parents[1]
    repo = core.parent
    app_source = (repo / "frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    progress_source = (repo / "frontend/src/renderer/components/ProgressCapsule.tsx").read_text(encoding="utf-8")
    motion_source = (repo / "frontend/src/renderer/styles/app.css").read_text(encoding="utf-8")
    diagnostics_ui = (repo / "frontend/src/renderer/components/settings/DiagnosticsPanel.tsx").read_text(encoding="utf-8")
    tool_source = (core / "atlas/agent/tool_node.py").read_text(encoding="utf-8")
    assert all(token in app_source for token in ("id: 'env'", "id: 'tui'", "id: 'quit'", "id: 'bug'", "id: 'battery'", "setQuitActivity"))
    assert "session_env" in tool_source and "fn_args[\"env\"]" in tool_source
    assert "id: 'indicator'" in app_source and all(value in app_source for value in ("'static'", "'spin'", "'subtle'", "'indicator-style'"))
    assert all(value in progress_source for value in ("indicatorStyle === 'spin'", "indicatorStyle === 'subtle'", "indicatorStyle = 'spin'"))
    assert "prefers-reduced-motion: reduce" in motion_source and "animation: none !important" in motion_source
    assert "saveBugBundle" in diagnostics_ui and "导出脱敏 Bug Bundle" in diagnostics_ui
    with tempfile.TemporaryDirectory(prefix="u43-cli-") as directory:
        root = Path(directory)
        env = {**os.environ, "ATLAS_ROOT": str(root / "atlas-root"), "PYTHONPATH": str(core)}
        (root / "atlas-root").mkdir()

        def run(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "-m", "atlas.cli", *arguments], cwd=core, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )

        for shell in ("bash", "zsh", "fish"):
            result = run("completion", shell)
            assert result.returncode == 0 and "_ATLAS_COMPLETE" in result.stdout and len(result.stdout) > 100
        version = run("version")
        assert version.returncode == 0 and version.stdout.startswith("Atlas v")
        chat_quit = subprocess.run(
            [sys.executable, "-m", "atlas.cli", "chat", "--safe-mode"], cwd=core, env=env,
            input="/quit\n", capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        assert chat_quit.returncode == 0 and "Bye!" in chat_quit.stdout
        terminal = run("terminal", "doctor")
        assert terminal.returncode == 0 and "平台：" in terminal.stdout and "建议：" in terminal.stdout
        assert run("uninstall", "--help").returncode == 0
        fake_uninstaller = root / "Uninstall Atlas.exe"
        fake_uninstaller.write_text("placeholder; the prompt below must cancel before launching", encoding="utf-8")
        uninstall_env = {**env, "ATLAS_UNINSTALLER_EXECUTABLE": str(fake_uninstaller)}
        cancelled = subprocess.run(
            [sys.executable, "-m", "atlas.cli", "uninstall"], cwd=core, env=uninstall_env,
            input="n\n", capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        assert cancelled.returncode == 0 and "已取消卸载" in cancelled.stdout and fake_uninstaller.exists()
        assert run("desktop", "--help").returncode == 0

        bundle_path = root / "selected-bundle.json"
        generated = run("bug", "--output", str(bundle_path))
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        assert generated.returncode == 0 and bundle["kind"] == "atlas-local-bug-bundle"
        assert bundle["privacy"]["local_only"] and bundle["privacy"]["uploaded"] is False
        serialized = json.dumps(bundle, ensure_ascii=False).lower()
        assert "api_key" not in serialized and "secrets.json" not in serialized
        assert "atlas.preference.session-env-presets" not in serialized

    from atlas.api.diagnostics_router import get_battery_status

    battery = asyncio.run(get_battery_status())
    assert set(battery) == {"supported", "level", "charging", "seconds_left"}
    assert (battery["supported"] and isinstance(battery["level"], int)) or battery["level"] is None


def check_isolated_preview() -> None:
    from docx import Document
    from pypdf import PdfWriter

    with tempfile.TemporaryDirectory(prefix="u43-preview-") as directory:
        root = Path(directory)
        document = Document()
        document.add_heading("U43 isolated DOCX", 0)
        document.add_paragraph("worker parses Office bytes in an isolated process")
        docx = root / "sample.docx"
        document.save(docx)
        rendered, mode = render_isolated_preview(docx.read_bytes(), ".docx")
        assert mode == "office-html" and "U43 isolated DOCX" in rendered

        pdf = root / "sample.pdf"
        writer = PdfWriter(); writer.add_blank_page(width=612, height=792)
        with pdf.open("wb") as output:
            writer.write(output)
        rendered, mode = render_isolated_preview(pdf.read_bytes(), ".pdf")
        assert mode in {"pdf-image", "pdf-text"}
        assert ("data:image/png;base64" in rendered) if mode == "pdf-image" else ("提取" in rendered or "没有可提取" in rendered)


class _Memory:
    async def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        return [{"id": "local-session", "title": "Local session", "workspace": "C:/local", "updated_at": "now"}]

    async def create_conversation(self, title: str) -> str:
        return "local-new-session"

    async def update_conversation(self, *args: Any, **kwargs: Any) -> bool:
        return True


class _Manager:
    def __init__(self) -> None:
        self.runs: dict[str, RunState] = {}
        self.started = 0

    async def persist_run(self, run: RunState) -> None:
        return None

    async def send_run(self, run: RunState, envelope: dict[str, Any], fallback: str) -> None:
        run.events.append(envelope)


async def _start_run(conn_id: str, data: dict[str, Any], manager: _Manager) -> None:
    manager.started += 1
    manager.runs[data["run_id"]] = RunState(data["run_id"], data["conversation_id"], "fake-model")


def check_cluster_control() -> None:
    with tempfile.TemporaryDirectory(prefix="u43-cluster-") as directory:
        cluster_control._path = lambda: Path(directory) / "cluster-control.json"  # type: ignore[assignment]
        services = AppServices(memory=_Memory(), runtime_mgr=_Manager(), runtime_start_handler=_start_run)
        app = FastAPI(); app.include_router(cluster_router.router)
        app.dependency_overrides[get_app_services] = lambda: services

        peer = FastAPI(); fake = {"up": True, "trusted": set(), "calls": []}
        peer_token = "localhost-fake-node-token-0123456789"

        def authenticate(token: str | None, source: str | None = None, paired: bool = False) -> None:
            if token != peer_token:
                raise HTTPException(401, "invalid fake-node token")
            if paired and source not in fake["trusted"]:
                raise HTTPException(403, "fake node source is not paired")
            if not fake["up"]:
                raise HTTPException(503, "fake node offline")

        @peer.get("/api/cluster/identity")
        def identity(x_atlas_cluster_token: str | None = Header(default=None),
                     x_atlas_cluster_node: str | None = Header(default=None)) -> dict[str, Any]:
            authenticate(x_atlas_cluster_token)
            if x_atlas_cluster_node:
                fake["trusted"].add(x_atlas_cluster_node)
            return {"node_id": "localhost-fake-node", "node_name": "Fake node", "protocol": 1,
                    "version": "test", "capabilities": ["sessions.read", "tasks.start", "runs.pause", "runs.resume", "runs.cancel"]}

        @peer.get("/api/cluster/health")
        def health(x_atlas_cluster_token: str | None = Header(default=None),
                   x_atlas_cluster_node: str | None = Header(default=None)) -> dict[str, Any]:
            authenticate(x_atlas_cluster_token, x_atlas_cluster_node, True)
            return {"status": "online", "version": "test", "capabilities": ["sessions.read"], "components": {"api": "ready"}}

        @peer.get("/api/cluster/sessions")
        def sessions(x_atlas_cluster_token: str | None = Header(default=None),
                     x_atlas_cluster_node: str | None = Header(default=None)) -> dict[str, Any]:
            authenticate(x_atlas_cluster_token, x_atlas_cluster_node, True)
            return {"sessions": [{"id": "peer-session", "title": "Remote session", "status": "running", "run_id": "peer-run"}]}

        @peer.post("/api/cluster/tasks")
        def receive_task(payload: dict[str, Any], x_atlas_cluster_token: str | None = Header(default=None),
                         x_atlas_cluster_node: str | None = Header(default=None)) -> dict[str, Any]:
            authenticate(x_atlas_cluster_token, x_atlas_cluster_node, True)
            fake["calls"].append(payload)
            return {"status": "accepted", "run_id": "peer-run", "conversation_id": "peer-session"}

        @peer.post("/api/cluster/operations")
        def receive_operation(payload: dict[str, Any], x_atlas_cluster_token: str | None = Header(default=None),
                              x_atlas_cluster_node: str | None = Header(default=None)) -> dict[str, Any]:
            authenticate(x_atlas_cluster_token, x_atlas_cluster_node, True)
            fake["calls"].append(payload)
            return {"run_id": payload["run_id"], "status": payload["action"]}

        @peer.post("/api/cluster/revoke")
        def receive_revoke(payload: dict[str, Any], x_atlas_cluster_token: str | None = Header(default=None),
                           x_atlas_cluster_node: str | None = Header(default=None)) -> dict[str, Any]:
            authenticate(x_atlas_cluster_token, x_atlas_cluster_node, True)
            fake["trusted"].discard(payload["source_node_id"]); fake["calls"].append({"revoke": payload})
            return {"revoked": True}

        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        server = uvicorn.Server(uvicorn.Config(peer, host="127.0.0.1", port=port, log_level="critical"))
        thread = threading.Thread(target=server.run, daemon=True); thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.03)
        assert server.started, "localhost fake node did not start"
        try:
            with TestClient(app) as client:
                assert client.get("/api/cluster/identity").status_code == 401
                settings = client.get("/api/cluster/settings").json()
                auth = {"X-Atlas-Cluster-Token": settings["service_token"]}
                added = client.post("/api/cluster/nodes", json={"name": "Fake local node", "url": f"http://127.0.0.1:{port}", "token": peer_token})
                assert added.status_code == 200, added.text
                peer_id = added.json()["id"]
                snapshot = client.get("/api/cluster/instances", headers=auth).json()
                assert snapshot["instances"][0]["sessions"][0]["id"] == "local-session"
                assert snapshot["instances"][1]["sessions"][0]["id"] == "peer-session"
                assert snapshot["instances"][1]["version"] == "test"

                sent = client.post(f"/api/cluster/nodes/{peer_id}/tasks", json={"title": "Remote work", "content": "hello peer"})
                assert sent.json()["status"] == "sent" and fake["calls"][-1]["content"] == "hello peer"
                operation = client.post(f"/api/cluster/nodes/{peer_id}/runs/peer-run/pause")
                assert operation.status_code == 200 and operation.json()["status"] == "pause"

                fake["up"] = False
                queued = client.post(f"/api/cluster/nodes/{peer_id}/tasks", json={"title": "Queued work", "content": "deliver later"})
                assert queued.json()["status"] == "queued"
                fake["up"] = True
                flushed = client.get("/api/cluster/instances", headers=auth).json()
                assert flushed["queue"][0]["status"] == "sent" and fake["calls"][-1]["content"] == "deliver later"

                incoming = {"X-Atlas-Cluster-Token": settings["service_token"], "X-Atlas-Cluster-Node": "other-local-node"}
                assert client.get("/api/cluster/identity", headers=incoming).status_code == 200
                request = {"request_id": "stable-request-id-01", "title": "Inbound task", "content": "run task", "workspace": "C:/tmp"}
                started = client.post("/api/cluster/tasks", headers=incoming, json=request)
                assert started.status_code == 200 and services.runtime_mgr.started == 1, started.text
                duplicate = client.post("/api/cluster/tasks", headers=incoming, json=request)
                assert duplicate.json()["duplicate"] is True and services.runtime_mgr.started == 1
                run_id = started.json()["run_id"]
                for action, status in (("pause", "paused"), ("resume", "running"), ("cancel", "cancelled")):
                    controlled = client.post("/api/cluster/operations", headers=incoming, json={"run_id": run_id, "action": action})
                    assert controlled.status_code == 200 and controlled.json()["status"] == status
                revoked = client.post("/api/cluster/revoke", headers=incoming, json={"source_node_id": "other-local-node"})
                assert revoked.json()["revoked"]
                duplicate_revoke = client.post("/api/cluster/revoke", headers=incoming, json={"source_node_id": "other-local-node"})
                assert duplicate_revoke.json()["already_revoked"]
                assert client.get("/api/cluster/health", headers=incoming).status_code == 403

                events = client.get("/api/cluster/audit", headers=auth).json()["events"]
                assert any(row["action"] == "task.queue.dispatch" for row in events)
                assert all("token" not in row and "content" not in row for row in events)
                fake["up"] = False
                removed = client.delete(f"/api/cluster/nodes/{peer_id}")
                assert removed.status_code == 200
                queued_revoke = client.get("/api/cluster/nodes", headers=auth).json()["queue"]
                assert any(row["title"] == "撤销远端信任" and row["status"] == "queued" for row in queued_revoke)
                fake["up"] = True
                client.get("/api/cluster/instances", headers=auth)
                dispatched_revoke = client.get("/api/cluster/nodes", headers=auth).json()["queue"]
                assert next(row for row in dispatched_revoke if row["title"] == "撤销远端信任")["status"] == "sent"
        finally:
            server.should_exit = True; thread.join(timeout=3)


def main() -> None:
    check_isolated_preview()
    check_cluster_control()
    check_interactive_cli_and_private_bug_bundle()
    print("U43 CHECK PASS")


if __name__ == "__main__":
    main()
