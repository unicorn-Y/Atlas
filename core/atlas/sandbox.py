"""Docker-backed per-run command sandbox."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class DockerSandboxManager:
    def __init__(self) -> None:
        self._status: tuple[float, dict[str, Any]] | None = None
        self._containers: dict[str, tuple[str, str]] = {}
        self._roots: dict[str, str] = {}

    async def status(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._status and now - self._status[0] < 60:
            return dict(self._status[1])
        docker = shutil.which("docker")
        if not docker:
            result = {"available": False, "version": None,
                      "detail": "未找到 Docker 命令，请安装并启动 Docker Desktop 后重试。"}
        else:
            try:
                completed = await asyncio.to_thread(
                    subprocess.run, [docker, "version", "--format", "json"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
                )
                if completed.returncode == 0:
                    try:
                        payload = json.loads(completed.stdout or "{}")
                    except json.JSONDecodeError:
                        payload = {}
                    version = (payload.get("Client") or {}).get("Version") or \
                              (payload.get("Server") or {}).get("Version") or "unknown"
                    result = {"available": True, "version": str(version), "detail": "Docker 可用。"}
                else:
                    result = {"available": False, "version": None,
                              "detail": "Docker 命令可用，但 Docker 服务未运行或不可访问。"}
            except (OSError, subprocess.TimeoutExpired):
                result = {"available": False, "version": None,
                          "detail": "查询 Docker 状态超时或失败，请检查 Docker Desktop。"}
        self._status = (now, result)
        return dict(result)

    async def start(self, run_id: str, workspace: str, sandbox: dict[str, Any]) -> dict[str, str]:
        existing = self._containers.get(run_id)
        if existing:
            return {"container_id": existing[0], "image": existing[1]}
        root = str(Path(workspace).expanduser().resolve())
        image = str(sandbox.get("image") or "python:3.12-slim")
        if not image or image.startswith("-"):
            raise ValueError("Docker image is invalid")
        command = shutil.which("docker") or "docker"
        argv = [command, "run", "-d", "--rm", "--name",
                f"atlas-{re.sub('[^a-zA-Z0-9_.-]', '-', run_id)[:48]}",
                "-v", f"{root}:/workspace", "-w", "/workspace"]
        if not sandbox.get("network", False):
            argv.extend(["--network", "none"])
        argv.extend([image, "sh", "-lc", "while true; do sleep 3600; done"])
        completed = await asyncio.to_thread(
            subprocess.run, argv, cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise RuntimeError(detail or "Docker 无法启动容器。")
        container_id = completed.stdout.strip().splitlines()[0]
        self._containers[run_id] = (container_id, image)
        self._roots[run_id] = root
        return {"container_id": container_id, "image": image}

    async def stop(self, run_id: str) -> None:
        entry = self._containers.pop(run_id, None)
        self._roots.pop(run_id, None)
        if not entry:
            return
        await asyncio.to_thread(
            subprocess.run, [shutil.which("docker") or "docker", "rm", "-f", entry[0]],
            capture_output=True, text=True, timeout=30,
        )

    async def call_tool(self, run_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        entry = self._containers.get(run_id)
        if not entry:
            raise RuntimeError("Docker 沙箱容器尚未启动。")
        container, _image = entry
        workspace = Path(self._roots[run_id]).resolve()
        cwd = Path(str(args.get("cwd") or workspace)).expanduser().resolve()
        if not cwd.is_relative_to(workspace):
            raise PermissionError("Docker 沙箱命令的工作目录必须位于工作目录内。")
        relative = cwd.relative_to(workspace).as_posix()
        container_cwd = "/workspace" if relative == "." else f"/workspace/{relative}"
        if name == "local_shell":
            command = ["sh", "-lc", str(args.get("command", ""))]
        elif name == "local_exec":
            executable = str(args.get("executable", ""))
            if not executable or executable.startswith(("/", "\\")) or ".." in Path(executable).parts:
                raise ValueError("容器可执行文件必须使用镜像内安装的命令名。")
            command = [executable, *[str(arg) for arg in args.get("args", [])]]
        elif name == "local_git":
            action = str(args.get("action", "status"))
            actions = {"status": ["status", "--short", "--branch"], "diff": ["diff"],
                       "log": ["log", "-10", "--oneline", "--decorate"],
                       "branch": ["branch", "--show-current"],
                       "add": ["add", *args.get("paths", ["."])],
                       "commit": ["commit", "-m", str(args.get("message", "Atlas change"))],
                       "pull": ["pull"], "fetch": ["fetch"], "push": ["push"]}
            if action not in actions:
                raise ValueError("不支持的 Git 操作。")
            command = ["git", *actions[action], *[str(arg) for arg in args.get("args", [])]]
        else:
            detail = "沙箱模式下此工具不可用。"
            return {"data": {"error": detail}, "content": [{"type": "text", "text": detail}],
                    "is_error": True}
        argv = [shutil.which("docker") or "docker", "exec", "-w", container_cwd, container, *command]
        started = time.monotonic()
        try:
            completed = await asyncio.to_thread(
                subprocess.run, argv, cwd=str(workspace), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=float(args.get("timeout", 120)),
            )
            stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr, code = "命令超时", 124
        duration = round(time.monotonic() - started, 3)
        output = (stdout + stderr).replace("/workspace", str(workspace))
        return {"data": {"command": " ".join(command), "cwd": str(cwd), "exit_code": code,
                         "stdout": stdout.replace("/workspace", str(workspace)),
                         "stderr": stderr.replace("/workspace", str(workspace)),
                         "duration_seconds": duration, "state": "completed"},
                "content": [{"type": "text", "text": output}], "is_error": code != 0}
