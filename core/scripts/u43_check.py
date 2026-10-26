"""Real-scenario checks for the U43 implementation batch; all peers bind to localhost."""
from __future__ import annotations

import socket
import tempfile
import threading
import time
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
    print("U43 CHECK PASS")


if __name__ == "__main__":
    main()
