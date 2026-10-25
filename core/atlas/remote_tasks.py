"""Self-hosted SSH task execution with local attempt and patch records."""
from __future__ import annotations

import asyncio
import difflib
import json
import re
import shlex
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from atlas.config import DATA_ROOT
from atlas.ssh import SSHWorkspaceManager, ssh_workspaces


class RemoteTaskStore:
    """Small atomic JSON store for host metadata, jobs, attempts and snapshots."""

    def __init__(self, path: Path | None = None, ssh: SSHWorkspaceManager = ssh_workspaces) -> None:
        self.path = path or DATA_ROOT / "data" / "remote-tasks.json"
        self.ssh = ssh
        self._lock = asyncio.Lock()
        self._runner: asyncio.Task[None] | None = None
        self._active: dict[str, asyncio.Task[None]] = {}

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    async def environments(self, query: str = "") -> list[dict[str, Any]]:
        data = self._read()
        configured = {item["alias"]: item for item in data.get("environments", [])}
        needle = query.casefold().strip()
        result = []
        for host in self.ssh.hosts():
            item = {**configured.get(host["alias"], {}), **host}
            item.setdefault("workspace", "")
            item.setdefault("tags", [])
            item.setdefault("setup_command", "")
            item.setdefault("github_repository", "")
            item.setdefault("web_setup_url", "")
            if not needle or needle in " ".join([str(item.get(k, "")) for k in ("alias", "hostname", "user", "workspace", "tags")]).casefold():
                result.append(item)
        return result

    async def save_environment(self, body: dict[str, Any]) -> dict[str, Any]:
        alias = str(body.get("alias", "")).strip()
        if not alias or alias not in {host["alias"] for host in self.ssh.hosts()}:
            raise ValueError("选择 ~/.ssh/config 中已配置的 Host 别名")
        workspace = str(body.get("workspace", "")).strip()
        if not workspace:
            raise ValueError("远端工作区不能为空")
        host, root = self.ssh.parse_workspace(workspace)
        if host != alias:
            raise ValueError("workspace 的 SSH 主机必须与环境别名相同")
        tags = body.get("tags", [])
        if isinstance(tags, str):
            tags = tags.split(",")
        repository = str(body.get("github_repository", "")).strip()
        if repository:
            parsed_repo = urlsplit(repository)
            repo_path = parsed_repo.path.strip("/") if parsed_repo.scheme else repository
            if parsed_repo.scheme and (parsed_repo.hostname != "github.com" or parsed_repo.username or parsed_repo.password):
                raise ValueError("GitHub 仓库必须使用 github.com URL")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", repo_path):
                raise ValueError("GitHub 仓库格式应为 owner/repo 或 github.com/owner/repo")
        web_setup_url = str(body.get("web_setup_url", "")).strip()
        if web_setup_url:
            parsed_url = urlsplit(web_setup_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or parsed_url.username or parsed_url.password:
                raise ValueError("Web Setup URL 必须是无凭据的 HTTP 或 HTTPS 地址")
        item = {
            "alias": alias, "workspace": f"ssh://{alias}{root}",
            "tags": [str(tag).strip() for tag in tags if str(tag).strip()][:24],
            "setup_command": str(body.get("setup_command", ""))[:4000],
            "github_repository": repository[:300],
            "web_setup_url": web_setup_url[:1000],
        }
        async with self._lock:
            data = self._read()
            entries = {entry["alias"]: entry for entry in data.get("environments", []) if isinstance(entry, dict) and entry.get("alias")}
            entries[alias] = item
            data["environments"] = list(entries.values())
            self._write(data)
        return item

    async def create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        envs = await self.environments()
        environment = next((item for item in envs if item["alias"] == body.get("environment")), None)
        if not environment or not environment["workspace"]:
            raise ValueError("请先保存远端环境和工作区")
        command = str(body.get("command", "")).strip()
        if not command:
            raise ValueError("任务命令不能为空")
        scheduled_at = str(body.get("scheduled_at", "")).strip()
        interval_seconds = max(0, min(int(body.get("interval_seconds") or 0), 31_536_000))
        if scheduled_at:
            try:
                scheduled = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("scheduled_at 必须是 ISO 日期时间") from exc
            if scheduled.tzinfo is None:
                raise ValueError("scheduled_at 必须包含时区")
            scheduled_at = scheduled.astimezone(UTC).isoformat()
        elif interval_seconds:
            raise ValueError("重复计划必须同时指定首次运行时间")
        snapshot_id = str(body.get("session_snapshot_id", ""))
        if snapshot_id:
            snapshot = next((item for item in self._read().get("snapshots", []) if item.get("id") == snapshot_id), None)
            if not snapshot or snapshot.get("environment") != environment["alias"]:
                raise ValueError("会话快照不存在或属于另一个远端环境")
        job = {
            "id": uuid.uuid4().hex, "environment": environment["alias"],
            "workspace": environment["workspace"], "command": command[:12000],
            "scheduled_at": scheduled_at, "interval_seconds": interval_seconds,
            "status": "scheduled" if scheduled_at else "queued", "created_at": self._now(),
            "next_run_at": scheduled_at, "attempts": [], "cancelled": False,
            "session_snapshot_id": snapshot_id,
        }
        async with self._lock:
            data = self._read()
            data.setdefault("tasks", []).insert(0, job)
            self._write(data)
        if not scheduled_at:
            self._start_attempt(job["id"])
        self._ensure_scheduler()
        return self._public_job(job)

    async def list_tasks(self, environment: str = "") -> list[dict[str, Any]]:
        self._ensure_scheduler()
        jobs = self._read().get("tasks", [])
        return [self._public_job(job) for job in jobs if not environment or job.get("environment") == environment]

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        job = next((item for item in self._read().get("tasks", []) if item.get("id") == task_id), None)
        return self._public_job(job) if job else None

    async def cancel(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            data = self._read()
            job = next((item for item in data.get("tasks", []) if item.get("id") == task_id), None)
            if not job:
                return None
            job["cancelled"] = True
            job["status"] = "cancelled"
            job["next_run_at"] = ""
            self._write(data)
        active = self._active.get(task_id)
        if active and not active.done():
            active.cancel()
        return self._public_job(job)

    async def retry(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            data = self._read()
            job = next((item for item in data.get("tasks", []) if item.get("id") == task_id), None)
            if not job:
                return None
            job["cancelled"] = False
            job["status"] = "queued"
            job["next_run_at"] = ""
            self._write(data)
        self._start_attempt(task_id)
        return self._public_job(job)

    async def apply_attempt(self, task_id: str, attempt_id: str, root: str) -> dict[str, Any]:
        job = next((item for item in self._read().get("tasks", []) if item.get("id") == task_id), None)
        if not job:
            raise KeyError("远端任务不存在")
        attempt = next((item for item in job.get("attempts", []) if item.get("id") == attempt_id), None)
        if not attempt or not attempt.get("diff"):
            raise ValueError("此 attempt 没有可应用的 Git diff")
        target = Path(root).expanduser().resolve()
        if not target.is_dir():
            raise ValueError("本机取回目录不存在")
        patch_path = target / f".atlas-remote-{task_id[:12]}-{attempt_id[:8]}.patch"
        patch_path.write_text(attempt["diff"], encoding="utf-8")
        try:
            for args in (["git", "apply", "--check", str(patch_path)], ["git", "apply", str(patch_path)]):
                result = await asyncio.create_subprocess_exec(*args, cwd=target, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await result.communicate()
                if result.returncode:
                    raise RuntimeError((stderr or stdout).decode("utf-8", errors="replace")[-2000:])
        finally:
            patch_path.unlink(missing_ok=True)
        return {"ok": True, "workspace": str(target), "attempt_id": attempt_id}

    async def snapshot(self, body: dict[str, Any], services: Any = None) -> dict[str, Any]:
        env = next((item for item in await self.environments() if item["alias"] == body.get("environment")), None)
        if not env or not env.get("workspace"):
            raise ValueError("请先选择已保存工作区的 SSH 环境")
        conversation_id = str(body.get("conversation_id", ""))
        history: list[dict[str, str]] = []
        if conversation_id:
            memory = getattr(services, "memory", None)
            conversation = await memory.get_conversation(conversation_id) if memory else None
            if not conversation:
                raise ValueError("会话不存在或当前尚未加载会话服务")
            for message in conversation.get("messages", [])[-80:]:
                if isinstance(message, dict) and message.get("role") in {"user", "assistant"}:
                    history.append({"role": str(message["role"]), "content": str(message.get("content", ""))[:12000]})
        host, root = self.ssh.parse_workspace(env["workspace"])
        status_result = await self.ssh.run_result(host, self._git_command(root, "status --short --branch"))
        diff_result = await self.ssh.run_result(host, self._git_command(root, "diff --no-ext-diff --binary HEAD"))
        snapshot = {"id": uuid.uuid4().hex, "environment": env["alias"], "workspace": env["workspace"],
            "conversation_id": conversation_id, "history": history, "created_at": self._now(),
            "workspace_status": str(status_result.get("stdout", ""))[-16000:],
            "workspace_diff": str(diff_result.get("stdout", ""))[-500_000:],
            "permissions": "迁移内容：最近 80 条 user/assistant 历史、工作区 URI、Git status 和相对 HEAD 的二进制补丁。未迁移 SSH 私钥、Atlas 凭据或本机配置。任务在所选 SSH 用户权限下对该工作区执行；快照留在本机 Atlas 数据目录。"}
        async with self._lock:
            data = self._read()
            data.setdefault("snapshots", []).insert(0, snapshot)
            self._write(data)
        return {key: value for key, value in snapshot.items() if key != "history"} | {"message_count": len(history)}

    async def list_snapshots(self) -> list[dict[str, Any]]:
        return [{key: value for key, value in item.items() if key not in {"history", "workspace_diff"}} | {"message_count": len(item.get("history", [])), "diff_bytes": len(item.get("workspace_diff", "").encode("utf-8"))}
            for item in self._read().get("snapshots", [])]

    def start(self) -> None:
        self._ensure_scheduler()

    async def close(self) -> None:
        tasks = [task for task in [self._runner, *self._active.values()] if task and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._runner = None
        self._active.clear()

    def _ensure_scheduler(self) -> None:
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._schedule_loop(), name="atlas-remote-task-scheduler")

    async def _schedule_loop(self) -> None:
        await self._recover_interrupted()
        while True:
            await asyncio.sleep(2)
            now = datetime.now(UTC)
            for job in self._read().get("tasks", []):
                if job.get("status") != "scheduled" or job.get("cancelled") or not job.get("next_run_at"):
                    continue
                try:
                    due = datetime.fromisoformat(job["next_run_at"].replace("Z", "+00:00"))
                except ValueError:
                    continue
                if due.tzinfo is None:
                    due = due.replace(tzinfo=UTC)
                if due <= now and job.get("id") not in self._active:
                    self._start_attempt(job["id"])

    async def _recover_interrupted(self) -> None:
        async with self._lock:
            data = self._read()
            changed = False
            for job in data.get("tasks", []):
                if job.get("status") == "running":
                    for attempt in reversed(job.get("attempts", [])):
                        if attempt.get("status") == "running":
                            attempt.update(status="failed", finished_at=self._now(), exit_code=1,
                                           log=(str(attempt.get("log", "")) + "\nAtlas restarted before this attempt completed.")[-100_000:])
                            break
                    job["status"] = "failed"
                    job["next_run_at"] = ""
                    changed = True
                elif job.get("status") == "queued" and not job.get("cancelled"):
                    asyncio.get_running_loop().call_soon(self._start_attempt, str(job["id"]))
            if changed:
                self._write(data)

    def _start_attempt(self, task_id: str) -> None:
        current = self._active.get(task_id)
        if current and not current.done():
            return
        self._active[task_id] = asyncio.create_task(self._run_attempt(task_id), name=f"atlas-remote-task-{task_id}")

    async def _run_attempt(self, task_id: str) -> None:
        attempt = {"id": uuid.uuid4().hex, "started_at": self._now(), "finished_at": "", "status": "running", "log": "", "diff": "", "exit_code": None}
        async with self._lock:
            data = self._read()
            job = next((item for item in data.get("tasks", []) if item.get("id") == task_id), None)
            if not job or job.get("cancelled"):
                return
            job.setdefault("attempts", []).append(attempt)
            job["status"] = "running"
            self._write(data)
        try:
            host, root = self.ssh.parse_workspace(job["workspace"])
            before = await self.ssh.run_result(host, self._git_command(root, "diff --no-ext-diff --binary HEAD"))
            result = await self._execute(host, root, job["command"])
            after = await self.ssh.run_result(host, self._git_command(root, "diff --no-ext-diff --binary HEAD"))
            patch = str(after.get("stdout", "")) if after.get("exit_code") == 0 else ""
            if before.get("stdout") and patch:
                patch = "".join(difflib.unified_diff(str(before["stdout"]).splitlines(keepends=True), patch.splitlines(keepends=True), fromfile="a/worktree", tofile="b/worktree"))
            log_text = (str(result.get("stdout", "")) + ("\n[stderr]\n" + str(result.get("stderr", "")) if result.get("stderr") else ""))[-100_000:]
            if after.get("exit_code"):
                log_text = (log_text + "\n[diff capture unavailable]\n" + str(after.get("stderr", "")))[-100_000:]
            attempt.update(status="completed" if result.get("exit_code", 1) == 0 else "failed", exit_code=int(result.get("exit_code", 1)), log=log_text, diff=patch)
        except asyncio.CancelledError:
            attempt.update(status="cancelled", log="任务已取消。")
            raise
        except Exception as exc:
            attempt.update(status="failed", log=str(exc)[:4000], exit_code=1)
        finally:
            attempt["finished_at"] = self._now()
            async with self._lock:
                data = self._read()
                job = next((item for item in data.get("tasks", []) if item.get("id") == task_id), None)
                if job:
                    current = next((item for item in job.get("attempts", []) if item.get("id") == attempt["id"]), None)
                    if current:
                        current.update(attempt)
                    if job.get("cancelled"):
                        job["status"] = "cancelled"
                    elif job.get("interval_seconds", 0) and job.get("scheduled_at"):
                        from datetime import timedelta
                        next_time = datetime.now(UTC) + timedelta(seconds=int(job["interval_seconds"]))
                        job["status"] = "scheduled"
                        job["next_run_at"] = next_time.isoformat()
                    else:
                        job["status"] = attempt["status"]
                        job["next_run_at"] = ""
                    self._write(data)
            self._active.pop(task_id, None)

    async def _execute(self, host: str, root: str, command: str) -> dict[str, Any]:
        if await self.ssh.remote_os(host) == "windows":
            result = await self.ssh.call_tool("local_shell", {"command": command, "cwd": "."}, f"ssh://{host}{root}")
            return result["data"]
        return await self.ssh.run_result(host, f"cd {shlex.quote(root)} && {command}")

    @staticmethod
    def _git_command(root: str, args: str) -> str:
        return f"cd {shlex.quote(root)} && git {args}"

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {**job, "attempts": [{**item, "log": item.get("log", "")[-100_000:], "diff": item.get("diff", "")[-200_000:]} for item in job.get("attempts", [])]}
