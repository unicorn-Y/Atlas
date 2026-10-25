from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.remote_tasks_router import router
from atlas.remote_tasks import RemoteTaskStore


PATCH = """diff --git a/readme.txt b/readme.txt
--- a/readme.txt
+++ b/readme.txt
@@ -1 +1 @@
-old
+new
"""


class FakeSSH:
    def __init__(self) -> None:
        self.diff_calls = 0
        self.commands: list[str] = []

    def hosts(self):
        return [{"alias": "loopback-fake", "hostname": "127.0.0.1", "user": "tester"}]

    @staticmethod
    def parse_workspace(uri: str):
        alias, path = uri.removeprefix("ssh://").split("/", 1)
        return alias, "/" + path

    async def remote_os(self, host: str) -> str:
        return "linux"

    async def run_result(self, host: str, command: str):
        self.commands.append(command)
        if "git diff --no-ext-diff --binary HEAD" in command:
            self.diff_calls += 1
            return {"exit_code": 0, "stdout": "" if self.diff_calls % 2 else PATCH, "stderr": ""}
        if "git status --short --branch" in command:
            return {"exit_code": 0, "stdout": "## main\n", "stderr": ""}
        return {"exit_code": 0, "stdout": "fake command completed\n", "stderr": ""}

    async def call_tool(self, *args, **kwargs):
        return {"data": {"exit_code": 0, "stdout": "ok", "stderr": ""}}

    async def test(self, alias: str):
        return {"ok": True, "os": "linux", "detail": "fake executor"}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_remote_task_lifecycle_cancel_logs_and_apply(tmp_path: Path) -> None:
    async def scenario() -> None:
        fake = FakeSSH()
        store = RemoteTaskStore(tmp_path / "remote.json", fake)  # type: ignore[arg-type]
        environment = await store.save_environment({
            "alias": "loopback-fake", "workspace": "ssh://loopback-fake/home/test/project",
            "tags": ["linux", "gpu"], "setup_command": "uv sync",
            "github_repository": "owner/repo", "web_setup_url": "https://example.test/setup",
        })
        assert environment["workspace"].endswith("/home/test/project")
        task = await store.create_task({"environment": "loopback-fake", "command": "printf task-output"})
        for _ in range(100):
            current = await store.get_task(task["id"])
            if current and current["status"] != "running" and current["status"] != "queued":
                break
            await asyncio.sleep(0.01)
        assert current and current["status"] == "completed"
        attempt = current["attempts"][0]
        assert "fake command completed" in attempt["log"]
        assert "readme.txt" in attempt["diff"]

        repo = tmp_path / "local-repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / "readme.txt").write_text("old\n", encoding="utf-8")
        _git(repo, "add", "readme.txt")
        _git(repo, "-c", "user.email=atlas@example.test", "-c", "user.name=Atlas", "commit", "-m", "base", "-q")
        applied = await store.apply_attempt(task["id"], attempt["id"], str(repo))
        assert applied["ok"]
        assert (repo / "readme.txt").read_text(encoding="utf-8") == "new\n"

        snapshot = await store.snapshot({"environment": "loopback-fake"})
        assert snapshot["message_count"] == 0
        assert "Git status" in snapshot["permissions"]
        assert (await store.list_snapshots())[0]["diff_bytes"] >= 0

        scheduled = await store.create_task({"environment": "loopback-fake", "command": "sleep 99", "scheduled_at": "2099-01-01T00:00:00+00:00"})
        assert scheduled["status"] == "scheduled"
        cancelled = await store.cancel(scheduled["id"])
        assert cancelled and cancelled["status"] == "cancelled"

    asyncio.run(scenario())


def test_remote_task_api_uses_fake_executor_and_filters(tmp_path: Path, monkeypatch) -> None:
    import atlas.api.remote_tasks_router as module

    fake = FakeSSH()
    monkeypatch.setattr(module, "_store", RemoteTaskStore(tmp_path / "api.json", fake))  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        saved = client.put("/api/remote-tasks/environments", json={
            "alias": "loopback-fake", "workspace": "ssh://loopback-fake/home/test/project", "tags": ["linux"],
        })
        assert saved.status_code == 200
        assert client.get("/api/remote-tasks/environments?q=linux").json()["environments"][0]["alias"] == "loopback-fake"
        submitted = client.post("/api/remote-tasks", json={"environment": "loopback-fake", "command": "echo hello"})
        assert submitted.status_code == 200
        task_id = submitted.json()["task"]["id"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            task = client.get(f"/api/remote-tasks/{task_id}").json()["task"]
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert task["status"] == "completed"
        assert client.post(f"/api/remote-tasks/{task_id}/cancel").status_code == 200

