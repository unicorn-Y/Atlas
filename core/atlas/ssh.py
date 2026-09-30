"""SSH workspace transport used by the Atlas backend."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import posixpath
import re
import shlex
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit


@dataclass
class _Connection:
    client: Any
    last_used: float
    os_name: str | None = None


class SSHWorkspaceManager:
    """Pool key-authenticated SSH connections by configured host alias."""

    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = os.path.expanduser(config_path or "~/.ssh/config")
        self._pool: dict[str, _Connection] = {}
        self._reaper: asyncio.Task[None] | None = None

    def hosts(self) -> list[dict[str, str | None]]:
        result: list[dict[str, str | None]] = []
        aliases: list[str] = []
        hostname = user = None
        try:
            lines = open(self.config_path, encoding="utf-8").read().splitlines()
        except OSError:
            return []
        for raw in [*lines, "Host __end__"]:
            parts = raw.split()
            if not parts or parts[0].startswith("#"):
                continue
            key = parts[0].lower()
            value = " ".join(parts[1:]) if len(parts) > 1 else ""
            if key == "host":
                for alias in aliases:
                    if not any(char in alias for char in "*?!"):
                        result.append({"alias": alias, "hostname": hostname or alias, "user": user})
                aliases = value.split() if value else []
                hostname = user = None
            elif key == "hostname" and aliases:
                hostname = value
            elif key == "user" and aliases:
                user = value
        return result

    @staticmethod
    def parse_workspace(uri: str) -> tuple[str, str]:
        parsed = urlsplit(uri)
        if parsed.scheme != "ssh" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("workspace must be ssh://<host>/<absolute-path> without credentials")
        path = unquote(parsed.path)
        if not path.startswith("/") or "\x00" in path:
            raise ValueError("SSH workspace path must be absolute")
        return parsed.hostname, path

    async def _connect(self, host: str) -> _Connection:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_idle(), name="atlas-ssh-pool-reaper")
        cached = self._pool.get(host)
        is_closed = getattr(cached.client, "is_closed", None) if cached else None
        if (
            cached
            and time.monotonic() - cached.last_used < 300
            and not (callable(is_closed) and is_closed())
        ):
            cached.last_used = time.monotonic()
            return cached
        if cached:
            cached.client.close()
            self._pool.pop(host, None)
        try:
            import asyncssh
        except ImportError as exc:
            raise RuntimeError("SSH support requires asyncssh") from exc
        # Leave client_keys unset: asyncssh then uses the IdentityFile from ssh config or the
        # default keys. Passing None would disable key authentication altogether.
        client = await asyncssh.connect(
            host,
            config=[self.config_path] if os.path.isfile(self.config_path) else None,
            password=None,
        )
        conn = _Connection(client, time.monotonic())
        self._pool[host] = conn
        return conn

    async def _reap_idle(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                now = time.monotonic()
                for host, conn in list(self._pool.items()):
                    if now - conn.last_used >= 300:
                        self._pool.pop(host, None)
                        conn.client.close()
                        with suppress(Exception):
                            await conn.client.wait_closed()
        except asyncio.CancelledError:
            return

    async def run(self, host: str, command: str) -> str:
        result = await self.run_result(host, command)
        if result["exit_code"]:
            raise RuntimeError(result["stderr"] or f"remote command exited {result['exit_code']}")
        return result["stdout"]

    async def run_result(self, host: str, command: str) -> dict[str, Any]:
        for attempt in range(2):
            conn = await self._connect(host)
            try:
                result = await conn.client.run(command, check=False)
                conn.last_used = time.monotonic()
                return {
                    "exit_code": int(result.exit_status or 0),
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            except Exception as exc:
                try:
                    import asyncssh

                    retryable = isinstance(exc, (TimeoutError, OSError, asyncssh.Error))
                except ImportError:
                    retryable = isinstance(exc, (TimeoutError, OSError))
                if not retryable:
                    raise
                self._pool.pop(host, None)
                conn.client.close()
                if attempt:
                    raise
        raise RuntimeError("SSH connection failed")

    @staticmethod
    def _remote_path(root: str, path: Any) -> str:
        value = str(path or ".")
        normalized = posixpath.normpath(
            value if value.startswith("/") else posixpath.join(root, value)
        )
        if normalized != root and not normalized.startswith(root.rstrip("/") + "/"):
            raise ValueError("remote path escapes workspace root")
        return normalized

    @staticmethod
    def _powershell_quote(value: Any) -> str:
        text = str(value)
        # Workspace paths are kept POSIX-style for SFTP ("/D:/Atlas"); PowerShell needs "D:/Atlas".
        if re.match(r"^/[A-Za-z]:([/\\]|$)", text):
            text = text[1:]
        return "'" + text.replace("'", "''") + "'"

    @classmethod
    def _powershell_command(cls, script: str) -> str:
        # Silence progress records (they arrive as CLIXML on stderr) and hand back the exit code
        # of the last native command, which PowerShell would otherwise report as 0.
        script = f"$ProgressPreference = 'SilentlyContinue'; {script}; exit $LASTEXITCODE"
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        return f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"

    async def call_tool(
        self, name: str, arguments: dict[str, Any], workspace: str, run_id: str | None = None
    ) -> dict[str, Any]:
        host, root = self.parse_workspace(workspace)
        action = str(arguments.get("action", ""))
        if name == "local_file":
            path = self._remote_path(root, arguments.get("path"))
            if action in {"write", "append", "copy", "move", "delete"} and run_id:
                if action == "delete":
                    await self.create_checkpoint(workspace, [path], run_id)
                else:
                    await self._checkpoint(host, root, path, run_id)
                if action in {"copy", "move"} and arguments.get("destination"):
                    await self._checkpoint(
                        host, root, self._remote_path(root, arguments["destination"]), run_id
                    )
            conn = await self._connect(host)
            async with conn.client.start_sftp_client() as sftp:
                if action == "read":
                    async with sftp.open(path, "rb") as stream:
                        raw = await stream.read()
                    encoding = (
                        "base64"
                        if arguments.get("binary")
                        else str(arguments.get("encoding", "utf-8"))
                    )
                    content = (
                        base64.b64encode(raw).decode()
                        if encoding == "base64"
                        else raw.decode(encoding)
                    )
                    data = {
                        "path": path,
                        "size": len(raw),
                        "content": content,
                        "encoding": encoding,
                    }
                elif action in {"write", "append"}:
                    await sftp.makedirs(posixpath.dirname(path), exist_ok=True)
                    async with sftp.open(path, "ab" if action == "append" else "wb") as stream:
                        await stream.write(
                            str(arguments.get("content", "")).encode(
                                arguments.get("encoding", "utf-8")
                            )
                        )
                    data = {"path": path, "size": (await sftp.stat(path)).size}
                elif action == "mkdir":
                    await sftp.makedirs(path, exist_ok=True)
                    data = {"path": path, "is_dir": True}
                elif action == "list":
                    entries = await sftp.readdir(path)
                    data = {
                        "path": path,
                        "entries": [
                            {
                                "name": item.filename,
                                "path": posixpath.join(path, item.filename),
                                "is_dir": bool(
                                    item.attrs.permissions and item.attrs.permissions & 0o040000
                                ),
                            }
                            for item in entries
                            if item.filename not in {".", ".."}
                        ],
                    }
                elif action == "move":
                    destination = self._remote_path(root, arguments.get("destination"))
                    await sftp.rename(path, destination)
                    data = {"path": path, "destination": destination}
                elif action == "copy":
                    destination = self._remote_path(root, arguments.get("destination"))
                    await sftp.makedirs(posixpath.dirname(destination), exist_ok=True)
                    async with (
                        sftp.open(path, "rb") as source,
                        sftp.open(destination, "wb") as target,
                    ):
                        await target.write(await source.read())
                    data = {"path": path, "destination": destination}
                elif action == "delete":

                    async def remove_tree(target: str) -> None:
                        try:
                            entries = await sftp.readdir(target)
                        except Exception:
                            await sftp.remove(target)
                            return
                        for entry in entries:
                            if entry.filename in {".", ".."}:
                                continue
                            child = posixpath.join(target, entry.filename)
                            if entry.attrs.permissions and entry.attrs.permissions & 0o040000:
                                await remove_tree(child)
                            else:
                                await sftp.remove(child)
                        await sftp.rmdir(target)

                    await remove_tree(path)
                    data = {"path": path, "deleted": True}
                elif action == "stat":
                    try:
                        attrs = await sftp.stat(path)
                        data = {"path": path, "exists": True, "size": attrs.size}
                    except OSError:
                        data = {"path": path, "exists": False}
                elif action in {"glob", "search"}:
                    if await self.remote_os(host) == "windows":
                        quoted_path = self._powershell_quote(path)
                        if action == "glob":
                            pattern = self._powershell_quote(arguments.get("pattern", "*"))
                            script = (
                                f"Get-ChildItem -LiteralPath {quoted_path} -Filter {pattern} "
                                "-File -Recurse | ForEach-Object { $_.FullName }"
                            )
                        else:
                            query = self._powershell_quote(arguments.get("query", ""))
                            script = (
                                f"Get-ChildItem -LiteralPath {quoted_path} -File -Recurse "
                                f"| Select-String -SimpleMatch {query} "
                                '| ForEach-Object { "$($_.Path):$($_.LineNumber):$($_.Line)" }'
                            )
                        command = self._powershell_command(script)
                    elif action == "glob":
                        pattern = shlex.quote(str(arguments.get("pattern", "*")))
                        command = f"find {shlex.quote(path)} -type f -name {pattern}"
                    else:
                        command = f"grep -R -n {shlex.quote(str(arguments.get('query', '')))} {shlex.quote(path)}"
                    output = await self.run(host, command)
                    data = {"path": path, "matches": output.splitlines()}
                else:
                    raise ValueError(f"Unsupported remote file action: {action}")
        elif name == "local_edit":
            path = self._remote_path(root, arguments.get("path"))
            if run_id:
                await self._checkpoint(host, root, path, run_id)
            raw = await self.read_bytes(host, path)
            old, new = (
                str(arguments.get("old_string", "")).encode(),
                str(arguments.get("new_string", "")).encode(),
            )
            if not old or raw.count(old) != 1:
                raise ValueError("remote edit requires one exact old_string match")
            raw = raw.replace(old, new, 1)
            await self.write_bytes(host, path, raw)
            data = {"path": path, "size": len(raw)}
        elif name == "local_git":
            action = str(arguments.get("action", "status"))
            add_args = " ".join(map(shlex.quote, arguments.get("paths", ["."])))
            operations = {
                "status": "status --short --branch",
                "diff": "diff",
                "log": "log -10 --oneline --decorate",
                "branch": "branch --show-current",
                "add": "add " + add_args,
                "commit": "commit -m " + shlex.quote(str(arguments.get("message", "Atlas change"))),
                "pull": "pull",
                "fetch": "fetch",
                "push": "push",
            }
            if action not in operations:
                raise ValueError(f"Unsupported Git action: {action}")
            cwd = self._remote_path(root, arguments.get("repo", "."))
            if await self.remote_os(host) == "windows":
                git_args = {
                    "status": ["status", "--short", "--branch"],
                    "diff": ["diff"],
                    "log": ["log", "-10", "--oneline", "--decorate"],
                    "branch": ["branch", "--show-current"],
                    "add": ["add", *arguments.get("paths", ["."])],
                    "commit": ["commit", "-m", str(arguments.get("message", "Atlas change"))],
                    "pull": ["pull"],
                    "fetch": ["fetch"],
                    "push": ["push"],
                }[action]
                script = (
                    f"Set-Location -LiteralPath {self._powershell_quote(cwd)}; "
                    "& git " + " ".join(self._powershell_quote(arg) for arg in git_args)
                )
                command = self._powershell_command(script)
            else:
                command = f"cd {shlex.quote(cwd)} && git {operations[action]}"
            data = await self.run_result(host, command)
            data.update(action=action, repo=cwd)
        elif name in {"local_shell", "local_exec"}:
            cwd = self._remote_path(root, arguments.get("cwd", "."))
            if name == "local_exec":
                command = " ".join(
                    shlex.quote(str(value))
                    for value in [arguments.get("executable", ""), *arguments.get("args", [])]
                )
            else:
                command = str(arguments.get("command", ""))
            if await self.remote_os(host) == "windows":
                change_dir = f"Set-Location -LiteralPath {self._powershell_quote(cwd)}; "
                if name == "local_exec":
                    executable = self._powershell_quote(arguments.get("executable", ""))
                    args = " ".join(
                        self._powershell_quote(value) for value in arguments.get("args", [])
                    )
                    script = change_dir + f"& {executable} {args}"
                else:
                    script = change_dir + command
                wrapped = self._powershell_command(script)
            else:
                wrapped = f"cd {shlex.quote(cwd)} && {command}"
            data = await self.run_result(host, wrapped)
        else:
            raise ValueError("This tool runs in the local computer or browser environment")
        return {
            "data": data,
            "content": [{"type": "text", "text": str(data)}],
            "is_error": bool(isinstance(data, dict) and data.get("exit_code", 0)),
        }

    async def _checkpoint(self, host: str, root: str, path: str, run_id: str) -> None:
        try:
            relative = posixpath.relpath(path, root)
            if relative == ".." or relative.startswith("../"):
                return
            conn = await self._connect(host)
            async with conn.client.start_sftp_client() as sftp:
                manifest_path = posixpath.join(root, ".atlas-checkpoints", run_id, "manifest.json")
                try:
                    manifest = json.loads((await self.read_bytes(host, manifest_path)).decode())
                except Exception:
                    manifest = {"run_id": run_id, "workspace": root, "files": []}
                if any(item.get("path") == relative for item in manifest["files"]):
                    return
                try:
                    raw = await self.read_bytes(host, path)
                    exists = True
                except Exception:
                    raw, exists = b"", False
                snapshot = posixpath.join(root, ".atlas-checkpoints", run_id, "files", relative)
                if exists:
                    await sftp.makedirs(posixpath.dirname(snapshot), exist_ok=True)
                    async with sftp.open(snapshot, "wb") as stream:
                        await stream.write(raw)
                manifest["files"].append({"path": relative, "exists": exists, "directory": False})
                await sftp.makedirs(posixpath.dirname(manifest_path), exist_ok=True)
                async with sftp.open(manifest_path, "wb") as stream:
                    await stream.write(json.dumps(manifest).encode())
        except Exception:
            return

    async def changes(self, workspace: str, run_id: str) -> dict[str, Any]:
        host, root = self.parse_workspace(workspace)
        manifest_path = posixpath.join(root, ".atlas-checkpoints", run_id, "manifest.json")
        try:
            manifest = json.loads((await self.read_bytes(host, manifest_path)).decode())
        except Exception:
            return {"run_id": run_id, "files": []}
        files = []
        import difflib

        for item in manifest.get("files", []):
            relative = item["path"]
            current_path = posixpath.join(root, relative)
            before_path = posixpath.join(root, ".atlas-checkpoints", run_id, "files", relative)
            try:
                after = await self.read_bytes(host, current_path)
                exists_after = True
            except Exception:
                after, exists_after = b"", False
            try:
                before = await self.read_bytes(host, before_path) if item.get("exists") else b""
            except Exception:
                before = b""
            old = before.decode("utf-8", errors="replace").splitlines(keepends=True)
            new = after.decode("utf-8", errors="replace").splitlines(keepends=True)
            diff = list(
                difflib.unified_diff(old, new, fromfile=f"a/{relative}", tofile=f"b/{relative}")
            )
            files.append(
                {
                    "path": relative,
                    "workspace": workspace,
                    "status": "added"
                    if not item.get("exists")
                    else "deleted"
                    if not exists_after
                    else "modified",
                    "additions": sum(
                        line.startswith("+") and not line.startswith("+++") for line in diff
                    ),
                    "deletions": sum(
                        line.startswith("-") and not line.startswith("---") for line in diff
                    ),
                    "diff": "".join(diff)[: 200 * 1024],
                }
            )
        return {"run_id": run_id, "files": files}

    async def create_checkpoint(
        self, workspace: str, paths: list[str], run_id: str
    ) -> dict[str, Any]:
        host, root = self.parse_workspace(workspace)

        async def checkpoint_tree(target: str) -> None:
            try:
                entries = await self.list_dir(host, target)
            except Exception:
                await self._checkpoint(host, root, target, run_id)
                return
            for entry in entries:
                child = str(PurePosixPath(target) / entry["name"])
                relative = posixpath.relpath(child, root)
                if relative == ".atlas-checkpoints" or relative.startswith(".atlas-checkpoints/"):
                    continue
                if entry["type"] == "directory":
                    await checkpoint_tree(child)
                elif entry["type"] == "file":
                    await self._checkpoint(host, root, child, run_id)

        for relative in paths:
            target = self._remote_path(root, relative)
            await checkpoint_tree(target)
        try:
            manifest = json.loads(
                (
                    await self.read_bytes(
                        host,
                        posixpath.join(root, ".atlas-checkpoints", run_id, "manifest.json"),
                    )
                ).decode()
            )
        except Exception:
            manifest = {"run_id": run_id, "workspace": root, "files": []}
        manifest.setdefault("created_at", datetime.now(UTC).isoformat())
        conn = await self._connect(host)
        async with conn.client.start_sftp_client() as sftp:
            manifest_path = posixpath.join(root, ".atlas-checkpoints", run_id, "manifest.json")
            await sftp.makedirs(posixpath.dirname(manifest_path), exist_ok=True)
            async with sftp.open(manifest_path, "wb") as stream:
                await stream.write(json.dumps(manifest).encode())
        return {
            "id": run_id,
            "workspace": workspace,
            "created_at": manifest["created_at"],
            "run_id": run_id,
            "files": manifest.get("files", []),
        }

    async def list_checkpoints(
        self, workspace: str, run_id: str | None = None
    ) -> list[dict[str, Any]]:
        host, root = self.parse_workspace(workspace)
        parent = posixpath.join(root, ".atlas-checkpoints")
        try:
            entries = await self.list_dir(host, parent)
        except Exception:
            return []
        result = []
        for entry in entries:
            identifier = entry["name"]
            if run_id and identifier != run_id:
                continue
            try:
                manifest = json.loads(
                    (
                        await self.read_bytes(
                            host,
                            posixpath.join(parent, identifier, "manifest.json"),
                        )
                    ).decode()
                )
            except Exception:
                continue
            result.append(
                {
                    "id": identifier,
                    "workspace": workspace,
                    "created_at": manifest.get("created_at", ""),
                    "run_id": manifest.get("run_id", identifier),
                    "files": manifest.get("files", []),
                }
            )
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    async def restore_checkpoint(self, workspace: str, checkpoint_id: str) -> dict[str, Any]:
        host, root = self.parse_workspace(workspace)
        parent = posixpath.join(root, ".atlas-checkpoints", checkpoint_id)
        manifest = json.loads(
            (await self.read_bytes(host, posixpath.join(parent, "manifest.json"))).decode()
        )
        restored = []
        for item in manifest.get("files", []):
            relative = str(item["path"])
            target = self._remote_path(root, relative)
            if item.get("exists"):
                source = posixpath.join(parent, "files", relative)
                await self.write_bytes(host, target, await self.read_bytes(host, source))
            else:
                conn = await self._connect(host)
                async with conn.client.start_sftp_client() as sftp:
                    await sftp.remove(target)
            restored.append(relative)
        return {"id": checkpoint_id, "restored": restored}

    async def remote_os(self, host: str) -> str:
        conn = await self._connect(host)
        if conn.os_name is None:
            # Windows OpenSSH usually starts cmd.exe, where PowerShell variables print literally.
            # %OS% expands to Windows_NT in cmd; PowerShell and POSIX shells leave it untouched.
            result = await conn.client.run("echo %OS%", check=False)
            if "windows_nt" in str(result.stdout).lower():
                conn.os_name = "windows"
            else:
                probe = await conn.client.run("$PSVersionTable.PSVersion.Major", check=False)
                if str(probe.stdout).strip().isdigit():
                    conn.os_name = "windows"
                else:
                    result = await conn.client.run("uname -s", check=True)
                    conn.os_name = str(result.stdout).strip().lower()
        return conn.os_name

    async def test(self, host: str) -> dict[str, Any]:
        try:
            os_name = await self.remote_os(host)
            detail = (await self.run(host, "pwd")).strip()
            return {"ok": True, "os": os_name, "detail": detail}
        except Exception as exc:
            return {"ok": False, "os": None, "detail": str(exc)}

    async def read_bytes(self, host: str, path: str) -> bytes:
        conn = await self._connect(host)
        async with conn.client.start_sftp_client() as sftp:
            async with sftp.open(path, "rb") as stream:
                return await stream.read()

    async def write_bytes(self, host: str, path: str, data: bytes) -> None:
        conn = await self._connect(host)
        async with conn.client.start_sftp_client() as sftp:
            async with sftp.open(path, "wb") as stream:
                await stream.write(data)

    async def list_dir(self, host: str, path: str) -> list[dict[str, Any]]:
        conn = await self._connect(host)
        async with conn.client.start_sftp_client() as sftp:
            attrs = await sftp.readdir(path)
        return [
            {
                "name": item.filename,
                "type": "dir"
                if item.attrs.permissions and item.attrs.permissions & 0o040000
                else "file",
                "size": item.attrs.size,
            }
            for item in attrs
            if item.filename not in {".", ".."}
        ]

    async def close(self) -> None:
        if self._reaper:
            self._reaper.cancel()
            with suppress(asyncio.CancelledError):
                await self._reaper
            self._reaper = None
        clients, self._pool = self._pool, {}
        for conn in clients.values():
            conn.client.close()
            await conn.client.wait_closed()


ssh_workspaces = SSHWorkspaceManager()
