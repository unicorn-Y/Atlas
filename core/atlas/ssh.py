"""SSH workspace transport used by the Atlas backend."""

from __future__ import annotations

import asyncio
import base64
import glob
import hashlib
import json
import os
import posixpath
import re
import shlex
import stat
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit

import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SSHAuthority:
    """Resolved, non-secret identity for one configured SSH trust domain."""

    alias: str
    hostname: str
    port: int
    username: str
    identity_files: tuple[str, ...]
    host_key_alias: str
    known_hosts: tuple[str, ...]
    config_digest: str

    @property
    def id(self) -> str:
        payload = json.dumps(
            {
                "alias": self.alias.casefold(), "hostname": self.hostname.casefold(),
                "port": self.port, "username": self.username,
                "identity_files": self.identity_files, "host_key_alias": self.host_key_alias,
                "known_hosts": self.known_hosts, "config_digest": self.config_digest,
            }, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class _Connection:
    client: Any
    last_used: float
    os_name: str | None = None
    authority_id: str = ""
    authority: SSHAuthority | None = None
    active_leases: int = 0


@dataclass
class _SSHProcessRecord:
    execution_id: str
    process: Any
    connection: _Connection
    command: str
    cwd: str
    started_monotonic: float
    started_at: str
    owner_run_id: str | None
    detached: bool
    pty: bool
    state: str = "starting"
    exit_code: int | None = None
    cancelled: bool = False
    cancel_requested: bool = False
    cancel_note: str = ""
    last_output_monotonic: float = 0.0
    streams: dict[str, bytearray] = field(
        default_factory=lambda: {"stdout": bytearray(), "stderr": bytearray()}
    )
    total_bytes: dict[str, int] = field(default_factory=lambda: {"stdout": 0, "stderr": 0})
    reader_tasks: list[asyncio.Task[None]] = field(default_factory=list)
    wait_task: asyncio.Task[None] | None = None
    start_task: asyncio.Task[Any] | None = None
    start_complete: asyncio.Event = field(default_factory=asyncio.Event)
    stdin_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cancel_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    lease_released: bool = False
    sandbox_backend: str | None = None
    sandbox_permissions: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "pid": None,
            "command": self.command,
            "cwd": self.cwd,
            "shell": "SSH remote process",
            "state": self.state,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "duration_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "detached": self.detached,
            "pty": self.pty,
            "authority_id": self.connection.authority_id,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_permissions": self.sandbox_permissions,
            "output_bytes_total": sum((self.total_bytes or {}).values()),
            "cancel_note": self.cancel_note,
        }


class _SSHBridgeReader:
    """Binary SSH reader whose AsyncSSH calls always run on the connection owner loop."""

    def __init__(self, owner_loop: asyncio.AbstractEventLoop, reader: Any) -> None:
        self._owner_loop = owner_loop
        self._reader = reader

    async def _call(self, method: str, *args: Any) -> Any:
        return await _ssh_owner_call(self._owner_loop, getattr(self._reader, method), *args)

    async def read(self, size: int = -1) -> bytes:
        return await self._call("read", size)

    async def readexactly(self, size: int) -> bytes:
        return await self._call("readexactly", size)

    async def readuntil(self, separator: bytes = b"\n") -> bytes:
        return await self._call("readuntil", separator)

    async def readline(self) -> bytes:
        try:
            return await self.readuntil(b"\n")
        except asyncio.IncompleteReadError as exc:
            return exc.partial


class _SSHBridgeWriter:
    """Bounded local write buffer; drain performs the remote write and backpressure wait."""

    MAX_PENDING_BYTES = 1024 * 1024

    def __init__(self, owner_loop: asyncio.AbstractEventLoop, writer: Any) -> None:
        self._owner_loop = owner_loop
        self._writer = writer
        self._pending = bytearray()
        self._closing = False
        self._eof_sent = False

    def is_closing(self) -> bool:
        return self._closing

    def write(self, data: bytes) -> None:
        if self._closing:
            raise BrokenPipeError("SSH LSP stdin is closing")
        value = bytes(data)
        if len(self._pending) + len(value) > self.MAX_PENDING_BYTES:
            raise BufferError("SSH LSP stdin pending buffer exceeded 1 MiB before drain")
        self._pending.extend(value)

    def write_eof(self) -> None:
        self._closing = True

    def close(self) -> None:
        self.write_eof()

    async def drain(self) -> None:
        data = bytes(self._pending)
        self._pending.clear()
        if data:
            async def _write() -> None:
                self._writer.write(data)
                await self._writer.drain()
            await _ssh_owner_call(self._owner_loop, _write)
        if self._closing and not self._eof_sent:
            await _ssh_owner_call(self._owner_loop, self._writer.write_eof)
            self._eof_sent = True


async def _ssh_owner_call(
    owner_loop: asyncio.AbstractEventLoop, method: Any, *args: Any,
) -> Any:
    """Await one SSH coroutine on its owning loop without blocking either loop."""
    if not owner_loop.is_running():
        raise ConnectionError("SSH connection owner loop is not running")
    if asyncio.get_running_loop() is owner_loop:
        result = method(*args)
        return await result if hasattr(result, "__await__") else result

    async def _invoke() -> Any:
        result = method(*args)
        return await result if hasattr(result, "__await__") else result

    future = asyncio.run_coroutine_threadsafe(_invoke(), owner_loop)
    try:
        return await asyncio.wrap_future(future)
    except asyncio.CancelledError:
        future.cancel()
        raise


class _SSHBridgeProcess:
    """Async subprocess-shaped view of a raw, binary AsyncSSH process."""

    remote = True
    pid = None

    def __init__(self, owner_loop: asyncio.AbstractEventLoop, process: Any,
                 on_closed: Any) -> None:
        self._owner_loop = owner_loop
        self._process = process
        self._on_closed = on_closed
        self._closed = False
        self.transport_closed = False
        self.exit_confirmed = False
        self.returncode: int | None = None
        self.stdin = _SSHBridgeWriter(owner_loop, process.stdin)
        self.stdout = _SSHBridgeReader(owner_loop, process.stdout)
        self.stderr = _SSHBridgeReader(owner_loop, process.stderr)

    async def _wait_owner(self) -> int | None:
        await self._process.wait_closed()
        status = getattr(self._process, "exit_status", None)
        self.returncode = int(status) if status is not None else None
        self.exit_confirmed = self.returncode is not None
        self._finish_owner()
        return self.returncode

    def _finish_owner(self) -> None:
        if not self._closed:
            self._closed = True
            self.transport_closed = True
            self._on_closed(self)

    async def wait(self) -> int | None:
        return await _ssh_owner_call(self._owner_loop, self._wait_owner)

    async def _kill_owner(self) -> None:
        if not self._closed:
            terminate = getattr(self._process, "terminate", None)
            close = getattr(self._process, "close", None)
            if callable(terminate):
                result = terminate()
                if hasattr(result, "__await__"):
                    await result
            elif callable(close):
                result = close()
                if hasattr(result, "__await__"):
                    await result
            try:
                await asyncio.wait_for(self._process.wait_closed(), timeout=5.0)
            except TimeoutError:
                if callable(close):
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                await asyncio.wait_for(self._process.wait_closed(), timeout=2.0)
            status = getattr(self._process, "exit_status", None)
            self.returncode = int(status) if status is not None else None
            self.exit_confirmed = self.returncode is not None
            self._finish_owner()

    async def kill(self) -> None:
        await _ssh_owner_call(self._owner_loop, self._kill_owner)


class _SSHTerminalSession:
    """One authority-pinned interactive PTY and its connection-pool lease."""

    def __init__(self, manager: Any, connection: Any, authority_id: str) -> None:
        self.manager = manager
        self.connection = connection
        self.authority_id = authority_id
        self.process: Any = None
        self.start_task: asyncio.Task | None = None
        self.exit_status: int | None = None
        self.transport_closed = False
        self._released = False
        self.process_cleanup_confirmed = False
        self._close_lock = asyncio.Lock()
        self.recovery_task: asyncio.Task | None = None

    async def read(self, size: int = 4096) -> bytes:
        if self.process is None:
            return b""
        data = await self.process.stdout.read(size)
        return data if isinstance(data, bytes) else str(data).encode("utf-8", "replace")

    async def write(self, data: bytes) -> None:
        if self.process is None or self.transport_closed:
            raise ConnectionError("SSH terminal is closed")
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def resize(self, rows: int, cols: int) -> None:
        if self.process is None or self.transport_closed:
            return
        result = self.process.change_terminal_size(cols, rows, 0, 0)
        if hasattr(result, "__await__"):
            await result

    def _finish(self, *, transport_closed: bool) -> None:
        self.transport_closed = self.transport_closed or transport_closed
        if not self._released:
            self._released = True
            self.manager._terminal_sessions.discard(self)
            self.connection.active_leases = max(0, self.connection.active_leases - 1)
            self.connection.last_used = time.monotonic()

    def _transport_closed(self) -> None:
        # A lost transport releases local ownership; it does not prove remote exit.
        self._finish(transport_closed=True)

    async def wait_closed(self) -> int | None:
        if self.process is not None and not self.transport_closed:
            await self.process.wait_closed()
            status = getattr(self.process, "exit_status", None)
            self.exit_status = int(status) if status is not None else None
            self._finish(transport_closed=True)
        return self.exit_status

    async def close(self) -> bool:
        async with self._close_lock:
            if self.process is None:
                if self.start_task is None or self.start_task.done():
                    self._finish(transport_closed=True)
                    return True
                # Never block shutdown waiting for create_process acknowledgement.
                # The manager closes the transport, while recovery keeps ownership
                # of any handle which arrives later.
                return False
            close = getattr(self.process, "close", None)
            if self.transport_closed:
                if self.process_cleanup_confirmed:
                    return True
                if callable(close):
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                try:
                    await asyncio.wait_for(self.process.wait_closed(), timeout=1.0)
                except TimeoutError:
                    return False
                status = getattr(self.process, "exit_status", None)
                self.exit_status = int(status) if status is not None else None
                self.process_cleanup_confirmed = True
                return True
            terminate = getattr(self.process, "terminate", None)
            if callable(terminate):
                result = terminate()
                if hasattr(result, "__await__"):
                    await result
            elif callable(close):
                result = close()
                if hasattr(result, "__await__"):
                    await result
            try:
                await asyncio.wait_for(self.process.wait_closed(), timeout=2.0)
            except TimeoutError:
                if callable(close):
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                await asyncio.wait_for(self.process.wait_closed(), timeout=1.0)
            status = getattr(self.process, "exit_status", None)
            self.exit_status = int(status) if status is not None else None
            self.process_cleanup_confirmed = True
            self._finish(transport_closed=True)
            return True


class SSHLspWorkspace:
    """One authority-bound remote filesystem/process view shared with the LSP service loop."""

    def __init__(self, manager: Any, workspace: str, owner_loop: asyncio.AbstractEventLoop,
                 authority_id: str, trusted: bool) -> None:
        self.manager = manager
        self.workspace = workspace
        self.owner_loop = owner_loop
        self.authority_id = authority_id
        self.trusted = trusted
        self.host, self.root = manager.parse_workspace(workspace)
        self.uri_for_path = lambda path: "file://" + quote(path, safe="/:@")
        self.path_from_uri = lambda uri: unquote(uri.removeprefix("file://"))
        self.normalize_path = posixpath.normpath
        self.process_factory = manager.make_lsp_process_factory(
            workspace, owner_loop, expected_authority_id=authority_id,
        )

    def _sync(self, coroutine: Any, timeout: float = 10.0) -> Any:
        if not self.owner_loop.is_running():
            if hasattr(coroutine, "close"):
                coroutine.close()
            raise ConnectionError("SSH LSP owner loop is not running")
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is self.owner_loop:
            if hasattr(coroutine, "close"):
                coroutine.close()
            raise RuntimeError("SSH LSP synchronous bridge cannot block the owner loop")
        future = asyncio.run_coroutine_threadsafe(coroutine, self.owner_loop)
        try:
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            raise

    async def _exists(self, path: str, *, directory: bool | None = None) -> bool:
        return await _ssh_owner_call(self.owner_loop, self._exists_on_owner, path, directory)

    async def _exists_on_owner(self, path: str, directory: bool | None = None) -> bool:
        import asyncssh

        connection = await self.manager._connect(self.host, expected_authority_id=self.authority_id)
        try:
            async with connection.client.start_sftp_client() as sftp:
                attrs = await sftp.stat(path)
        except (OSError, asyncssh.SFTPError):
            return False
        if directory is None or not getattr(attrs, "permissions", None):
            return True
        mode = attrs.permissions & 0o170000
        return mode == (0o040000 if directory else 0o100000)

    def cache_key(self, root: str) -> str:
        return f"{self.authority_key}{posixpath.normpath(root)}"

    @property
    def authority_key(self) -> str:
        return f"ssh://{quote(self.authority_id, safe='')}@{self.host}"

    async def resolve_root(self, server: Any, file_path: str, workspace_root: str) -> str | None:
        """Resolve the nearest remote language project root using the server's marker contract."""
        markers = server.root_markers
        if markers is None:
            return workspace_root
        excludes = server.root_excludes
        current = posixpath.dirname(file_path)
        ceiling = posixpath.normpath(workspace_root)
        for _ in range(64):
            for marker in excludes:
                if await self._exists(posixpath.join(current, marker)):
                    return None
            if not await self._exists(posixpath.join(current, "__init__.py")):
                for marker in markers:
                    if await self._exists(posixpath.join(current, marker)):
                        return current
            if current == ceiling:
                break
            parent = posixpath.dirname(current)
            if parent == current or posixpath.commonpath((ceiling, parent)) != ceiling:
                break
            current = parent
        return workspace_root

    def workspace_file(self, raw_path: Any) -> tuple[str, str]:
        root = posixpath.normpath(self.root)
        candidate = str(raw_path or "")
        if candidate.startswith("ssh://"):
            host, candidate = self.manager.parse_workspace(candidate)
            if host.casefold() != self.host.casefold():
                raise PermissionError("LSP path belongs to a different SSH authority")
        path = posixpath.normpath(candidate if candidate.startswith("/") else posixpath.join(root, candidate))
        try:
            if posixpath.commonpath((root, path)) != root:
                raise ValueError("LSP queries are restricted to the active SSH workspace.")
        except ValueError as exc:
            raise ValueError("LSP queries are restricted to the active SSH workspace.") from exc
        if not self._sync(self._exists(posixpath.join(root, ".git"))):
            raise PermissionError("SSH LSP requires a Git workspace inside the active authority root.")
        if not self._sync(self._exists(path, directory=False)):
            raise FileNotFoundError(f"Remote file not found: {posixpath.relpath(path, root)}")
        return root, path

    async def read_document(self, path: str) -> str:
        raw = await _ssh_owner_call(self.owner_loop, self._read_bytes, path)
        return raw.decode("utf-8-sig", "replace")

    async def _read_bytes(self, path: str) -> bytes:
        return await self.manager.read_bytes(
            self.host, path, expected_authority_id=self.authority_id,
        )

    def resolve_binary(self, _server_id: str, override: Any, candidates: Any) -> str | None:
        names: list[str] = []
        if isinstance(override, (list, tuple)) and override and isinstance(override[0], str):
            names.append(override[0])
        names.extend(str(name) for name in candidates if name)
        return self._sync(self._find_binary(names), timeout=8.0)

    async def _find_binary(self, names: list[str]) -> str | None:
        connection = await self.manager._connect(self.host, expected_authority_id=self.authority_id)
        os_name = await self.manager.remote_os(
            self.host, expected_authority_id=self.authority_id,
        )
        for name in dict.fromkeys(names):
            if os_name == "windows":
                script = (
                    "$item = Get-Command -Name " + self.manager._powershell_quote(name)
                    + " -ErrorAction SilentlyContinue | Select-Object -First 1; "
                    + "if ($item) { [Console]::Out.WriteLine($item.Source) }"
                )
                command = self.manager._powershell_command(script)
            else:
                command = "command -v -- " + shlex.quote(name)
            result = await connection.client.run(command, check=False)
            if result.exit_status == 0 and str(result.stdout).strip():
                return str(result.stdout).strip().splitlines()[0]
        return None


class SSHWorkspaceManager:
    """Pool key-authenticated SSH connections by configured host alias."""

    _MAX_PROCESS_STREAM_BYTES = 4 * 1024 * 1024
    _PROCESS_STOP_TIMEOUT_SECONDS = 3.0
    _PROCESS_START_ACK_TIMEOUT_SECONDS = 10.0
    _PROCESS_START_RECOVERY_TIMEOUT_SECONDS = 4.0
    _SANDBOX_PREFLIGHT_TIMEOUT_SECONDS = 20.0

    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = os.path.expanduser(config_path or "~/.ssh/config")
        self._pool: dict[str, _Connection] = {}
        self._processes: dict[str, _SSHProcessRecord] = {}
        self._lsp_processes: set[_SSHBridgeProcess] = set()
        self._lsp_cleanup_tasks: set[asyncio.Task] = set()
        self._terminal_sessions: set[_SSHTerminalSession] = set()
        self._terminal_cleanup_tasks: set[asyncio.Task] = set()
        self._remote_file_observations: dict[tuple[str, str, str], str] = {}
        self._closing = False
        self._process_lock = asyncio.Lock()
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
        try:
            explicit_port = parsed.port
        except ValueError as exc:
            raise ValueError("SSH workspace port is invalid") from exc
        if explicit_port is not None:
            raise ValueError("SSH workspace port must be configured on its SSH alias")
        if parsed.query or parsed.fragment:
            raise ValueError("SSH workspace cannot include query or fragment components")
        path = unquote(parsed.path)
        if not path.startswith("/") or "\x00" in path:
            raise ValueError("SSH workspace path must be absolute")
        return parsed.hostname.casefold(), path

    def _has_configured_alias(self, alias: str) -> bool:
        """Find exact Host declarations, following OpenSSH Include patterns."""
        pending = [Path(self.config_path)]
        seen: set[str] = set()
        include_root = Path("~/.ssh").expanduser()
        while pending:
            current = pending.pop()
            try:
                key = os.path.normcase(str(current.resolve()))
                if key in seen:
                    continue
                seen.add(key)
                lines = current.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for raw in lines:
                try:
                    parts = shlex.split(raw, comments=True)
                except ValueError:
                    continue
                if len(parts) < 2:
                    continue
                directive, values = parts[0].casefold(), parts[1:]
                if directive == "host" and any(
                    value.casefold() == alias and not any(char in value for char in "*?!")
                    for value in values
                ):
                    return True
                if directive != "include":
                    continue
                for value in values:
                    pattern = Path(os.path.expandvars(value)).expanduser()
                    base = Path(pattern.anchor) if pattern.anchor else include_root
                    relative = Path(*pattern.parts[1:]) if pattern.anchor else pattern
                    pending.extend(
                        Path(match) for match in glob.glob(str(base / relative))
                        if os.path.isfile(match)
                    )
        return False

    @staticmethod
    def _normalized_files(values: Any) -> tuple[str, ...]:
        if values is None:
            return ()
        if isinstance(values, (str, os.PathLike)):
            values = (values,)
        return tuple(
            os.path.normcase(os.path.abspath(os.path.expanduser(os.path.expandvars(str(path)))))
            for path in values
        )

    @staticmethod
    def _file_content_digest(paths: tuple[str, ...]) -> list[tuple[str, str]]:
        digests: list[tuple[str, str]] = []
        for path in paths:
            try:
                content = Path(path).read_bytes()
            except OSError:
                content = b"<unavailable>"
            digests.append((path, hashlib.sha256(content).hexdigest()))
        return digests

    @staticmethod
    def _canonical_options(config_options: dict[str, Any]) -> str:
        return json.dumps(config_options, sort_keys=True, separators=(",", ":"), default=str)

    async def _resolve_authority_options(self, alias: str) -> tuple[SSHAuthority, Any]:
        """Build and freeze the exact effective AsyncSSH options used to connect."""
        alias = alias.casefold()
        if not os.path.isfile(self.config_path):
            raise ValueError("SSH alias config is unavailable")
        if not self._has_configured_alias(alias):
            raise ValueError(f"SSH workspace must use an exact configured alias: {alias}")
        try:
            import asyncssh
        except ImportError as exc:
            raise RuntimeError("SSH support requires asyncssh") from exc

        options_type = asyncssh.SSHClientConnectionOptions
        # Resolve OpenSSH's normal pass and then its final pass. AsyncSSH's
        # final pass starts from the first pass and reloads the same config.
        initial = await options_type.construct(
            host=alias, config=[self.config_path], reload=True, final=False,
        )
        if initial.canonicalize_hostname:
            raise ValueError("SSH CanonicalizeHostname is not supported for workspace authorities")
        final_options = await options_type.construct(
            initial, host=alias, config=[self.config_path], reload=True, final=True,
        )
        if final_options.canonicalize_hostname:
            raise ValueError("SSH CanonicalizeHostname is not supported for workspace authorities")
        # Freeze the effective options with no file reload. connect() clones this
        # snapshot; it must not re-run the final/canonical pass against changed files.
        options = await options_type.construct(
            final_options, host=alias, config=None, reload=False, final=False, canonical=False,
        )
        if options.canonicalize_hostname:
            raise ValueError("SSH CanonicalizeHostname is not supported for workspace authorities")

        config = options.config
        effective_host = str(options.host).casefold()
        try:
            port = int(options.port)
        except (TypeError, ValueError) as exc:
            raise ValueError("SSH alias has an invalid port") from exc
        if not 1 <= port <= 65535:
            raise ValueError("SSH alias has an invalid port")
        username = str(options.username)
        identity_files = self._normalized_files(config.get("IdentityFile") or ())
        known_hosts_files = self._normalized_files(options.known_hosts)
        host_key_alias = str(options.host_key_alias or config.get("HostKeyAlias") or effective_host).casefold()
        config_options = dict(getattr(config, "_options", {}))
        client_key_fingerprints = sorted(
            hashlib.sha256(bytes(getattr(key, "public_data", b""))).hexdigest()
            for key in (options.client_keys or ())
        )
        material = {
            "effective_options": config_options,
            "host": effective_host,
            "port": port,
            "username": username,
            "host_key_alias": host_key_alias,
            "identity_files": identity_files,
            "identity_file_digests": self._file_content_digest(identity_files),
            "client_key_fingerprints": client_key_fingerprints,
            "known_hosts": known_hosts_files,
            "known_hosts_digests": self._file_content_digest(known_hosts_files),
        }
        config_digest = hashlib.sha256(self._canonical_options(material).encode("utf-8")).hexdigest()
        return SSHAuthority(
            alias=alias, hostname=effective_host, port=port, username=username,
            identity_files=identity_files, host_key_alias=host_key_alias,
            known_hosts=known_hosts_files, config_digest=config_digest,
        ), options

    async def resolve_authority(self, alias: str) -> SSHAuthority:
        """Resolve the exact configured SSH alias without exposing key material."""
        authority, _ = await self._resolve_authority_options(alias)
        return authority

    async def _connect(self, host: str, *, expected_authority_id: str | None = None) -> _Connection:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_idle(), name="atlas-ssh-pool-reaper")
        try:
            import asyncssh
        except ImportError as exc:
            raise RuntimeError("SSH support requires asyncssh") from exc
        authority, options = await self._resolve_authority_options(host)
        authority_id = authority.id
        if expected_authority_id is not None and authority_id != expected_authority_id:
            raise PermissionError("SSH alias authority changed after this workspace was created")
        cached = self._pool.get(authority_id)
        is_closed = getattr(cached.client, "is_closed", None) if cached else None
        if (
            cached
            and not (callable(is_closed) and is_closed())
            and (cached.active_leases > 0 or time.monotonic() - cached.last_used < 300)
        ):
            cached.last_used = time.monotonic()
            return cached
        if cached:
            cached.client.close()
            self._pool.pop(authority_id, None)
        client = await asyncssh.connect(
            host=authority.alias, config=None, options=options,
        )
        conn = _Connection(client, time.monotonic(), authority_id=authority_id, authority=authority)
        self._pool[authority_id] = conn
        return conn

    async def _reap_idle(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                await self._reap_idle_once()
        except asyncio.CancelledError:
            return

    async def _reap_idle_once(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        for authority_id, conn in list(self._pool.items()):
            if conn.active_leases == 0 and current - conn.last_used >= 300:
                self._pool.pop(authority_id, None)
                conn.client.close()
                with suppress(Exception):
                    await conn.client.wait_closed()

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
                self._pool.pop(conn.authority_id, None)
                conn.client.close()
                if attempt:
                    raise
        raise RuntimeError("SSH connection failed")

    @staticmethod
    def _remote_path(root: str, path: Any) -> str:
        value = str(path or ".")
        # Models on Windows hosts send "D:\\Atlas\\core" or "D:/Atlas"; the workspace root is kept
        # as "/D:/Atlas", so bring those into the same form before checking containment.
        drive = re.match(r"^/?([A-Za-z]):([/\\\\]|$)", value)
        if drive:
            value = "/" + drive.group(1).upper() + ":/" + value[drive.end():]
        value = value.replace("\\", "/")
        root_drive = re.match(r"^/([A-Za-z]):(/|$)", root)
        if root_drive:
            root = "/" + root_drive.group(1).upper() + root[2:]
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
        self, name: str, arguments: dict[str, Any], workspace: str, run_id: str | None = None,
        *, observation_owner_id: str | None = None,
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
            owner_id = str(observation_owner_id or "").strip()
            if not owner_id:
                raise ValueError(f"READ_REQUIRED: read {path} before editing it")
            authority = await self.resolve_authority(host)
            connection = await self._connect(host, expected_authority_id=authority.id)
            if connection.authority_id != authority.id:
                raise PermissionError("SSH workspace authority changed before edit")
            connection.active_leases += 1
            try:
                async with connection.client.start_sftp_client() as sftp:
                    canonical_root, canonical_path = await self._canonical_workspace_target(
                        sftp, root, path,
                    )
                    observation_key = (owner_id, authority.id, canonical_path)
                    observed_digest = self._remote_file_observations.get(observation_key)
                    if observed_digest is None:
                        raise ValueError(f"READ_REQUIRED: read {path} before editing it")
                    async with sftp.open(canonical_path, "rb") as stream:
                        raw = await stream.read()
                    if hashlib.sha256(raw).hexdigest() != observed_digest:
                        self._remote_file_observations.pop(observation_key, None)
                        raise ValueError(f"STALE_FILE: content changed since read; read {path} again")
                    old, new = (
                        str(arguments.get("old_string", "")).encode(),
                        str(arguments.get("new_string", "")).encode(),
                    )
                    if not old or raw.count(old) != 1:
                        raise ValueError("remote edit requires one exact old_string match")
                    if run_id:
                        await self._checkpoint(host, root, canonical_path, run_id)
                    # Recheck after checkpoint creation so time spent preparing the
                    # backup cannot silently widen the stale-write window.
                    async with sftp.open(canonical_path, "rb") as stream:
                        current = await stream.read()
                    if hashlib.sha256(current).hexdigest() != observed_digest:
                        self._remote_file_observations.pop(observation_key, None)
                        raise ValueError(f"STALE_FILE: content changed since read; read {path} again")
                    updated = current.replace(old, new, 1)
                    async with sftp.open(canonical_path, "wb") as stream:
                        await stream.write(updated)
                    self._remote_file_observations[observation_key] = hashlib.sha256(updated).hexdigest()
                    data = {"path": canonical_path, "size": len(updated)}
            finally:
                connection.active_leases = max(0, connection.active_leases - 1)
                connection.last_used = time.monotonic()
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
                    f"Set-Location -LiteralPath {self._powershell_quote(cwd)} -ErrorAction Stop; "
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
                change_dir = f"Set-Location -LiteralPath {self._powershell_quote(cwd)} -ErrorAction Stop; "
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
                logger.debug("atlas.ssh: ignored error", exc_info=True)
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

    async def remote_os(self, host: str, *, expected_authority_id: str | None = None) -> str:
        conn = await self._connect(host, expected_authority_id=expected_authority_id)
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

    async def read_bytes(self, host: str, path: str, *,
                         expected_authority_id: str | None = None) -> bytes:
        conn = await self._connect(host, expected_authority_id=expected_authority_id)
        async with conn.client.start_sftp_client() as sftp:
            async with sftp.open(path, "rb") as stream:
                return await stream.read()

    async def _canonical_workspace_target(self, sftp: Any, root: str, target: str) -> tuple[str, str]:
        import asyncssh

        root_name = await sftp.realpath(root, check=asyncssh.FXRP_STAT_ALWAYS)
        target_name = await sftp.realpath(target, check=asyncssh.FXRP_STAT_ALWAYS)
        canonical_root = posixpath.normpath(str(getattr(root_name, "filename", root_name)))
        canonical_target = posixpath.normpath(str(getattr(target_name, "filename", target_name)))
        try:
            common_root = posixpath.commonpath((canonical_root, canonical_target))
        except ValueError as exc:
            raise PermissionError("File is outside the active SSH workspace") from exc
        if common_root != canonical_root:
            raise PermissionError("File is outside the active SSH workspace")
        return canonical_root, canonical_target

    async def read_workspace_file(
        self, workspace: str, raw_path: str, *, offset: int = 0,
        limit: int | None = None, observation_owner_id: str | None = None,
    ) -> str:
        """Read a file below an SSH workspace after pinning and rechecking its authority."""
        if isinstance(offset, bool) or int(offset) < 0:
            raise ValueError("offset must be a non-negative line number")
        if limit is not None and (
            isinstance(limit, bool) or int(limit) < 1 or int(limit) > 2000
        ):
            raise ValueError("limit must be between 1 and 2000 lines")
        if not str(raw_path).strip():
            raise ValueError("File path must not be empty")

        host, root = self.parse_workspace(workspace)
        try:
            target = self._remote_path(root, raw_path)
        except ValueError as exc:
            raise PermissionError("File is outside the active SSH workspace") from exc
        authority = await self.resolve_authority(host)
        conn = await self._connect(host, expected_authority_id=authority.id)
        if conn.authority_id != authority.id:
            raise PermissionError("SSH workspace authority changed before file read")

        conn.active_leases += 1
        try:
            async with conn.client.start_sftp_client() as sftp:
                _canonical_root, canonical_target = await self._canonical_workspace_target(
                    sftp, root, target,
                )
                attrs = await sftp.stat(canonical_target)
                if attrs.permissions is not None and not stat.S_ISREG(attrs.permissions):
                    raise ValueError("SSH read_file target must be a regular file")
                async with sftp.open(canonical_target, "rb") as stream:
                    raw = await stream.read()
                if observation_owner_id:
                    self._remote_file_observations[
                        (str(observation_owner_id), authority.id, canonical_target)
                    ] = hashlib.sha256(raw).hexdigest()
        finally:
            conn.active_leases = max(0, conn.active_leases - 1)
            conn.last_used = time.monotonic()

        text = raw.decode("utf-8-sig", errors="replace")
        lines = text.splitlines(keepends=True)
        start = int(offset)
        end = len(lines) if limit is None else min(len(lines), start + int(limit))
        return "".join(lines[start:end])

    async def write_bytes(self, host: str, path: str, data: bytes) -> None:
        conn = await self._connect(host)
        async with conn.client.start_sftp_client() as sftp:
            async with sftp.open(path, "wb") as stream:
                await stream.write(data)

    def make_lsp_process_factory(
        self, workspace: str, owner_loop: asyncio.AbstractEventLoop, *,
        expected_authority_id: str | None = None,
    ) -> Any:
        """Return an LSP-loop callable which spawns raw SSH stdio on the SSH owner loop."""
        host, _ = self.parse_workspace(workspace)

        async def _factory(command: list[str], cwd: str, env: dict[str, str]) -> _SSHBridgeProcess:
            async def _open_on_owner() -> _SSHBridgeProcess:
                selected_host, remote_cwd = self._process_cwd(workspace, cwd)
                if selected_host != host:
                    raise PermissionError("LSP process cwd belongs to a different SSH authority")
                remote_command = await self._process_command(
                    host, remote_cwd, {"executable": command[0], "args": command[1:]},
                    expected_authority_id=expected_authority_id,
                )
                connection = await self._connect(host, expected_authority_id=expected_authority_id)
                connection.active_leases += 1
                try:
                    process = await connection.client.create_process(
                        remote_command, env=env or None, encoding=None, request_pty=False,
                    )
                except BaseException:
                    connection.active_leases = max(0, connection.active_leases - 1)
                    raise

                def _closed(adapter: _SSHBridgeProcess) -> None:
                    self._lsp_processes.discard(adapter)
                    connection.active_leases = max(0, connection.active_leases - 1)
                    connection.last_used = time.monotonic()

                adapter = _SSHBridgeProcess(owner_loop, process, _closed)
                adapter._connection = connection
                self._lsp_processes.add(adapter)
                return adapter

            # AsyncSSH may finish create_process as the LSP caller is cancelled. Shield
            # the owner-loop future so a late adapter is not orphaned with its lease.
            future = asyncio.run_coroutine_threadsafe(_open_on_owner(), owner_loop)
            wrapped = asyncio.wrap_future(future)
            try:
                return await asyncio.shield(wrapped)
            except asyncio.CancelledError:
                def _dispose_late(done: Any) -> None:
                    if done.cancelled():
                        return
                    try:
                        adapter = done.result()
                    except BaseException:
                        return
                    def _start_cleanup() -> None:
                        cleanup = owner_loop.create_task(adapter._kill_owner())
                        self._lsp_cleanup_tasks.add(cleanup)
                        cleanup.add_done_callback(self._lsp_cleanup_tasks.discard)

                    owner_loop.call_soon_threadsafe(_start_cleanup)

                future.add_done_callback(_dispose_late)
                raise

        return _factory

    async def make_lsp_workspace(self, workspace: str, *, trusted: bool) -> SSHLspWorkspace:
        owner_loop = asyncio.get_running_loop()
        host, _ = self.parse_workspace(workspace)
        authority = await self.resolve_authority(host)
        return SSHLspWorkspace(self, workspace, owner_loop, authority.id, trusted)

    async def _terminal_command(self, host: str, cwd: str, expected_authority_id: str) -> str:
        if await self.remote_os(host, expected_authority_id=expected_authority_id) == "windows":
            script = (
                "$ProgressPreference = 'SilentlyContinue'; Set-Location -LiteralPath "
                + self._powershell_quote(cwd)
                + " -ErrorAction Stop"
            )
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            return f"powershell.exe -NoLogo -NoProfile -NoExit -EncodedCommand {encoded}"
        return f"cd -- {shlex.quote(cwd)} && exec \"${{SHELL:-/bin/sh}}\" -l"

    async def _recover_terminal_start(
        self, session: _SSHTerminalSession, start_task: asyncio.Task[Any],
    ) -> None:
        try:
            process = await start_task
        except BaseException:
            session._finish(transport_closed=True)
            return
        session.process = process
        session.start_task = None
        try:
            await session.close()
        except Exception:
            # Keep the session and lease tracked until manager shutdown closes the transport.
            return

    def _schedule_terminal_recovery(
        self, session: _SSHTerminalSession, start_task: asyncio.Task[Any],
    ) -> asyncio.Task[Any]:
        if session.recovery_task is not None:
            if (
                not session.recovery_task.done()
                or session.process_cleanup_confirmed
                or session not in self._terminal_sessions
            ):
                return session.recovery_task
        cleanup = asyncio.create_task(self._recover_terminal_start(session, start_task))
        session.recovery_task = cleanup
        self._terminal_cleanup_tasks.add(cleanup)
        cleanup.add_done_callback(self._terminal_cleanup_tasks.discard)
        return cleanup

    async def open_terminal(
        self, workspace: str, *, rows: int = 24, cols: int = 80,
        term_type: str = "xterm-256color",
    ) -> _SSHTerminalSession:
        if self._closing:
            raise ConnectionError("SSH workspace manager is closing")
        host, cwd = self._process_cwd(workspace, workspace)
        authority = await self.resolve_authority(host)
        connection = await self._connect(host, expected_authority_id=authority.id)
        command = await self._terminal_command(host, cwd, authority.id)
        session = _SSHTerminalSession(self, connection, authority.id)
        connection.active_leases += 1
        self._terminal_sessions.add(session)

        async def _spawn() -> Any:
            return await connection.client.create_process(
                command, encoding=None, request_pty=True, term_type=term_type,
                term_size=(cols, rows, 0, 0),
            )

        start_task = asyncio.create_task(_spawn())
        session.start_task = start_task
        try:
            session.process = await asyncio.wait_for(asyncio.shield(start_task), timeout=10.0)
            session.start_task = None
            if self._closing:
                self._schedule_terminal_recovery(session, start_task)
                raise ConnectionError("SSH workspace manager closed during terminal startup")
            return session
        except BaseException:
            self._schedule_terminal_recovery(session, start_task)
            raise

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

    @staticmethod
    def _process_owner_allowed(record: _SSHProcessRecord, run_id: str | None) -> bool:
        return record.owner_run_id is None or (
            run_id is not None and record.owner_run_id == run_id
        )

    @staticmethod
    def _ssh_process_result(data: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
        return {
            "data": data,
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}],
            "is_error": is_error,
            "outcome": data.get("state", "unknown"),
        }

    def _process_cwd(self, workspace: str, cwd_value: Any) -> tuple[str, str]:
        host, root = self.parse_workspace(workspace)
        raw_cwd = str(cwd_value or workspace)
        if raw_cwd.startswith("ssh://"):
            cwd_host, cwd_root = self.parse_workspace(raw_cwd)
            if cwd_host != host:
                raise PermissionError("SSH process cwd belongs to a different authority")
            raw_cwd = cwd_root
        return host, self._remote_path(root, raw_cwd)

    async def _process_command(
        self, host: str, cwd: str, arguments: dict[str, Any], *,
        expected_authority_id: str | None = None,
    ) -> str:
        command = str(arguments.get("command") or "")
        executable = str(arguments.get("executable") or "")
        argv = [str(value) for value in arguments.get("args", [])]
        if not command and not executable:
            raise ValueError("SSH process start requires command or executable")
        if await self.remote_os(host, expected_authority_id=expected_authority_id) == "windows":
            body = command or "& " + " ".join(
                [self._powershell_quote(executable), *(self._powershell_quote(value) for value in argv)]
            )
            return self._powershell_command(
                f"Set-Location -LiteralPath {self._powershell_quote(cwd)} -ErrorAction Stop; {body}"
            )
        body = command or " ".join(shlex.quote(value) for value in [executable, *argv])
        return f"cd {shlex.quote(cwd)} && {body}"

    def _append_process_output(self, record: _SSHProcessRecord, stream: str, chunk: bytes) -> None:
        target = record.streams[stream]
        record.total_bytes[stream] += len(chunk)
        target.extend(chunk)
        if len(target) > self._MAX_PROCESS_STREAM_BYTES:
            del target[:len(target) - self._MAX_PROCESS_STREAM_BYTES]
        record.last_output_monotonic = time.monotonic()

    async def _read_process_stream(self, record: _SSHProcessRecord, stream: str) -> None:
        reader = getattr(record.process, stream, None)
        if reader is None:
            return
        try:
            while chunk := await reader.read(65536):
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", "replace")
                self._append_process_output(record, stream, bytes(chunk))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record.cancel_note = f"Remote {stream} stream ended unexpectedly ({type(exc).__name__})."

    def _release_process_lease(self, record: _SSHProcessRecord) -> None:
        if not record.lease_released:
            record.connection.active_leases = max(0, record.connection.active_leases - 1)
            record.lease_released = True
            record.connection.last_used = time.monotonic()

    async def _watch_process(self, record: _SSHProcessRecord) -> None:
        try:
            # stdout/stderr belong exclusively to reader_tasks. AsyncSSH wait() may
            # collect buffered output itself; wait_closed() only observes channel closure.
            await record.process.wait_closed()
            await asyncio.gather(*record.reader_tasks, return_exceptions=True)
            status = getattr(record.process, "exit_status", None)
            record.exit_code = int(status) if status is not None else None
            if status is None:
                if record.cancelled and getattr(record.process, "exit_signal", None):
                    record.state = "cancelled"
                else:
                    record.state = "unknown"
                    if not record.cancel_note:
                        record.cancel_note = "SSH channel ended without a confirmed remote exit status."
            elif record.cancel_requested:
                record.state = "cancelled"
            else:
                record.state = "completed" if record.exit_code == 0 else "failed"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record.state = "unknown"
            record.cancel_note = f"Remote process outcome is unknown ({type(exc).__name__})."
        finally:
            self._release_process_lease(record)

    async def _attach_process(self, record: _SSHProcessRecord, process: Any) -> None:
        record.process = process
        record.state = "running"
        record.start_complete.set()
        record.reader_tasks = [
            asyncio.create_task(self._read_process_stream(record, stream))
            for stream in ("stdout", "stderr")
        ]
        record.wait_task = asyncio.create_task(self._watch_process(record))
        if record.cancel_requested:
            await self._cancel_process(record)

    async def _recover_late_process_start(
        self, record: _SSHProcessRecord, start_task: asyncio.Task[Any],
    ) -> None:
        try:
            process = await asyncio.wait_for(
                asyncio.shield(start_task), timeout=self._PROCESS_START_RECOVERY_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            await self._uncertain_start_timeout(record)
            return
        except Exception as exc:
            record.state = "unknown"
            record.cancel_note = f"Cancelled start could not confirm remote process creation ({type(exc).__name__})."
            record.start_complete.set()
            self._release_process_lease(record)
            return
        await self._attach_process(record, process)

    async def _uncertain_start_timeout(self, record: _SSHProcessRecord) -> None:
        record.state = "unknown"
        record.cancel_note = "SSH process start acknowledgement timed out; outcome is unknown."
        record.start_complete.set()
        # Closing this connection bounds an unobservable channel. Other leases
        # on the same transport will transition to unknown through their waiters.
        record.connection.client.close()
        with suppress(Exception):
            await record.connection.client.wait_closed()
        if record.process is None:
            self._release_process_lease(record)

    @staticmethod
    def _sandbox_bwrap_argv(
        bwrap: str, workspace_source: str, workspace_target: str, cwd: str,
        executable: str, args: list[str], *, mode: str, network: bool,
        environment: dict[str, str],
    ) -> list[str]:
        if mode not in {"read-only", "workspace-write"}:
            raise PermissionError("Remote bwrap sandbox does not support danger-full-access.")
        if not posixpath.isabs(workspace_source) or not posixpath.isabs(workspace_target):
            raise ValueError("Remote sandbox workspace must be an absolute POSIX path.")
        if workspace_target == "/" or posixpath.normpath(workspace_target) != workspace_target:
            raise PermissionError("Remote sandbox requires a canonical, non-root workspace.")
        if not posixpath.isabs(cwd) or not executable or executable.startswith("-"):
            raise ValueError("Remote sandbox command paths are invalid.")
        if posixpath.commonpath((workspace_target, cwd)) != workspace_target:
            raise PermissionError("Remote sandbox cwd must remain inside its workspace.")

        argv = [bwrap, "--die-with-parent", "--unshare-all"]
        if network:
            argv.append("--share-net")
        for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
            argv.extend(("--ro-bind-try", path, path))
        argv.extend(("--dir", "/etc", "--dir", "/etc/ssl"))
        argv.extend(("--ro-bind-try", "/etc/ssl/certs", "/etc/ssl/certs"))
        for path in ("/etc/ld.so.cache", "/etc/passwd", "/etc/group", "/etc/nsswitch.conf"):
            argv.extend(("--ro-bind-try", path, path))
        if network:
            for path in ("/etc/hosts", "/etc/resolv.conf"):
                argv.extend(("--ro-bind-try", path, path))
        argv.extend(("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"))

        mounted = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/proc", "/dev", "/tmp")
        parents: list[str] = []
        parent = posixpath.dirname(workspace_target)
        while parent != "/" and not any(
            parent == root or parent.startswith(root.rstrip("/") + "/") for root in mounted
        ):
            parents.append(parent)
            parent = posixpath.dirname(parent)
        for path in reversed(parents):
            argv.extend(("--dir", path))

        bind = "--ro-bind" if mode == "read-only" else "--bind"
        argv.extend((bind, workspace_source, workspace_target, "--chdir", cwd, "--clearenv"))
        argv.extend(("--setenv", "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"))
        argv.extend(("--setenv", "HOME", workspace_target, "--setenv", "TMPDIR", "/tmp"))
        for key, value in environment.items():
            if (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                    or not isinstance(value, str)):
                raise ValueError("SSH process env must map environment names to string values")
            argv.extend(("--setenv", key, value))
        argv.extend(("--", executable, *args))
        return argv

    async def prepare_remote_sandbox(
        self, workspace: str, *, network: bool = False,
    ) -> dict[str, str]:
        """Resolve and probe a Linux bwrap runner through the configured SSH authority."""
        host, root = self.parse_workspace(workspace)
        deadline = asyncio.get_running_loop().time() + self._SANDBOX_PREFLIGHT_TIMEOUT_SECONDS

        async def bounded(operation: Callable[[], Any], stage: str) -> Any:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RuntimeError(f"Remote sandbox preflight timed out during {stage}.")
            try:
                return await asyncio.wait_for(operation(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise RuntimeError(f"Remote sandbox preflight timed out during {stage}.") from exc

        authority = await self.resolve_authority(host)
        conn = await bounded(
            lambda: self._connect(host, expected_authority_id=authority.id), "SSH connection",
        )
        os_name = await bounded(
            lambda: self.remote_os(host, expected_authority_id=authority.id),
            "target OS detection",
        )
        if os_name != "linux":
            raise RuntimeError("Remote bwrap sandbox is available only on Linux targets.")
        result = await bounded(
            lambda: conn.client.run(
                "command -v bwrap", check=False,
                timeout=self._SANDBOX_PREFLIGHT_TIMEOUT_SECONDS,
            ),
            "bwrap lookup",
        )
        if getattr(result, "exit_status", None) != 0:
            raise RuntimeError("Remote Linux target does not provide bubblewrap (bwrap).")
        bwrap = str(getattr(result, "stdout", "")).strip().splitlines()
        bwrap_path = bwrap[-1].strip() if bwrap else ""
        if (bwrap_path not in {"/usr/bin/bwrap", "/bin/bwrap"}
                or not re.fullmatch(r"/[A-Za-z0-9_./+-]+", bwrap_path)):
            raise RuntimeError("Remote bwrap executable path is invalid.")
        stat = await bounded(
            lambda: conn.client.run(
                f"stat -c '%u %a' {shlex.quote(bwrap_path)}", check=False,
                timeout=self._SANDBOX_PREFLIGHT_TIMEOUT_SECONDS,
            ),
            "bwrap ownership check",
        )
        try:
            owner, permissions = str(getattr(stat, "stdout", "")).strip().split()
            mode = int(permissions, 8)
        except (ValueError, TypeError):
            owner, mode = "", 0o777
        if getattr(stat, "exit_status", None) != 0 or owner != "0" or mode & 0o022:
            raise RuntimeError("Remote bwrap executable must be root-owned and not group/world writable.")
        async with conn.client.start_sftp_client() as sftp:
            canonical_root = str(await bounded(lambda: sftp.realpath(root), "workspace resolution"))
        if (not canonical_root.startswith("/") or canonical_root == "/"
                or posixpath.normpath(canonical_root) != canonical_root):
            raise PermissionError("Remote sandbox workspace must resolve to a non-root directory.")
        probe_argv = self._sandbox_bwrap_argv(
            bwrap_path, canonical_root, canonical_root, canonical_root,
            "/usr/bin/true", [], mode="read-only", network=network, environment={},
        )
        probe_command = " ".join(shlex.quote(value) for value in probe_argv)
        probe = await bounded(
            lambda: conn.client.run(
                probe_command, check=False,
                timeout=self._SANDBOX_PREFLIGHT_TIMEOUT_SECONDS,
            ),
            "workspace/namespace probe",
        )
        if getattr(probe, "exit_status", None) != 0:
            raise RuntimeError("Remote bwrap workspace/namespace probe failed; sandbox execution is disabled.")
        return {
            "host": host,
            "authority_id": authority.id,
            "bwrap": bwrap_path,
            "workspace_source": canonical_root,
            "workspace_target": canonical_root,
        }

    async def call_sandboxed_process(
        self, arguments: dict[str, Any], workspace: str, run_id: str | None, *,
        runner: dict[str, str], mode: str, network: bool,
    ) -> dict[str, Any]:
        action = str(arguments.get("action") or "start")
        if action != "start":
            execution_id = str(arguments.get("execution_id") or arguments.get("session_id") or "")
            record = self._processes.get(execution_id)
            if record is None or record.sandbox_backend != "ssh-bwrap":
                return self._ssh_process_result(
                    {"error": "Unknown sandboxed SSH execution_id."}, is_error=True,
                )
            return await self.call_process(arguments, workspace, run_id)

        host, lexical_cwd = self._process_cwd(workspace, arguments.get("cwd"))
        if host != runner.get("host"):
            raise PermissionError("Remote sandbox process authority changed during the run.")
        if mode not in {"read-only", "workspace-write"}:
            raise PermissionError("Remote bwrap sandbox does not support danger-full-access.")
        conn = await self._connect(host, expected_authority_id=runner.get("authority_id"))
        async with conn.client.start_sftp_client() as sftp:
            canonical_cwd = str(await sftp.realpath(lexical_cwd))
        canonical_root = runner["workspace_source"]
        if posixpath.commonpath((canonical_root, canonical_cwd)) != canonical_root:
            raise PermissionError("Remote sandbox cwd resolves outside its workspace.")

        command = str(arguments.get("command") or "")
        if command:
            executable, argv = "/bin/sh", ["-lc", command]
        else:
            executable = str(arguments.get("executable") or "")
            argv_value = arguments.get("args") or []
            if not executable or not isinstance(argv_value, list):
                raise ValueError("Sandboxed SSH process requires an executable and argv list.")
            argv = [str(value) for value in argv_value]
        environment = arguments.get("env") or {}
        wrapped_argv = self._sandbox_bwrap_argv(
            runner["bwrap"], canonical_root, runner["workspace_target"],
            canonical_cwd, executable, argv, mode=mode, network=network,
            environment=environment,
        )
        process_args = {key: value for key, value in arguments.items()
                        if key not in {"command", "executable", "args", "env", "sandbox_permissions",
                                       "justification", "_approval_reason", "_approval_no_always",
                                       "_reviewer_reason"}}
        process_args.update({
            "action": "start", "executable": runner["bwrap"], "args": wrapped_argv[1:],
            "cwd": lexical_cwd, "env": {},
        })
        result = await self.call_process(
            process_args, workspace, run_id,
            expected_authority_id=runner["authority_id"],
        )
        data = result.get("data")
        if isinstance(data, dict):
            record = self._processes.get(str(data.get("execution_id") or ""))
            if record is not None:
                record.sandbox_backend = "ssh-bwrap"
                record.sandbox_permissions = mode
            data["sandbox_backend"] = "ssh-bwrap"
            data["sandbox_permissions"] = mode
            data["sandbox_network"] = network
        return result

    async def _start_process(
        self, arguments: dict[str, Any], workspace: str, run_id: str | None,
        *, expected_authority_id: str | None = None,
    ) -> dict[str, Any]:
        host, cwd = self._process_cwd(workspace, arguments.get("cwd"))
        command = await self._process_command(
            host, cwd, arguments, expected_authority_id=expected_authority_id,
        )
        environment = arguments.get("env") or {}
        if not isinstance(environment, dict) or any(
            not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
            or not isinstance(value, str)
            for key, value in environment.items()
        ):
            raise ValueError("SSH process env must map environment names to string values")

        conn = await self._connect(host, expected_authority_id=expected_authority_id)
        execution_id = str(uuid.uuid4())
        record = _SSHProcessRecord(
            execution_id=execution_id, process=None, connection=conn, command=command,
            cwd=cwd, started_monotonic=time.monotonic(), started_at=datetime.now(UTC).isoformat(),
            owner_run_id=run_id, detached=bool(arguments.get("detached")),
            pty=bool(arguments.get("pty")), last_output_monotonic=time.monotonic(),
        )
        conn.active_leases += 1
        self._processes[execution_id] = record
        create_task: asyncio.Task[Any] | None = None
        try:
            options: dict[str, Any] = {"encoding": None, "env": environment or None}
            if record.pty:
                term_size = arguments.get("term_size") or (80, 24)
                options.update(
                    request_pty=True,
                    term_type=str(arguments.get("term_type") or "xterm-256color"),
                    term_size=(int(term_size[0]), int(term_size[1]), 0, 0),
                )

            async def _open_remote_process() -> Any:
                return await conn.client.create_process(command, **options)

            create_task = asyncio.create_task(_open_remote_process())
            record.start_task = create_task
            process = await asyncio.wait_for(
                asyncio.shield(create_task), timeout=self._PROCESS_START_ACK_TIMEOUT_SECONDS,
            )
            await self._attach_process(record, process)
            initial_stdin = arguments.get("stdin")
            writer = record.process.stdin
            if initial_stdin is not None and writer is not None:
                writer.write(str(initial_stdin).encode("utf-8"))
                await writer.drain()
            if writer is not None and not arguments.get("keep_stdin", True):
                writer.write_eof()
        except asyncio.CancelledError:
            record.cancel_requested = True
            record.cancel_note = "SSH process start was cancelled while awaiting remote acknowledgement."
            if record.process is not None:
                recovery = asyncio.create_task(self._cancel_process(record))
            elif create_task is not None:
                recovery = asyncio.create_task(self._recover_late_process_start(record, create_task))
                recovery.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            else:
                record.start_complete.set()
                self._release_process_lease(record)
            raise
        except TimeoutError:
            record.cancel_requested = True
            assert create_task is not None
            recovery = asyncio.create_task(self._recover_late_process_start(record, create_task))
            recovery.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            record.state = "unknown"
            record.cancel_note = "SSH process start acknowledgement timed out; recovery is pending."
            return self._ssh_process_result(record.summary())
        except Exception as exc:
            # A channel-open/transport error may arrive after the server started
            # the command. Keep its operation ID and never retry a side effect.
            record.cancel_requested = True
            record.state = "unknown"
            record.cancel_note = f"Remote start acknowledgement was lost ({type(exc).__name__})."
            record.start_complete.set()
            if record.process is not None:
                recovery = asyncio.create_task(self._cancel_process(record))
            elif create_task is not None and create_task.done() and not create_task.cancelled() and create_task.exception() is None:
                recovery = asyncio.create_task(self._recover_late_process_start(record, create_task))
                recovery.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            else:
                self._release_process_lease(record)
            return self._ssh_process_result(record.summary())
        return self._ssh_process_result(record.summary())

    def _read_process_output(
        self, record: _SSHProcessRecord, stream: str, offset: int, limit: int,
    ) -> dict[str, Any]:
        if stream not in {"stdout", "stderr"}:
            raise ValueError("stream must be stdout or stderr")
        output = record.streams[stream]
        total = record.total_bytes[stream]
        retained_start = max(0, total - len(output))
        effective = max(max(0, int(offset)), retained_start)
        local_start = min(len(output), effective - retained_start)
        end = min(len(output), local_start + max(0, min(int(limit), 1024 * 1024)))
        next_offset = retained_start + end
        return {
            "execution_id": record.execution_id,
            "stream": stream,
            "offset": effective,
            "next_offset": next_offset,
            "text": bytes(output[local_start:end]).decode("utf-8", "replace"),
            "total_bytes": total,
            "omitted_bytes": retained_start,
            "complete": record.state != "running" and next_offset >= total,
        }

    async def _cancel_process(self, record: _SSHProcessRecord) -> dict[str, Any]:
        async with record.cancel_lock:
            if record.state not in {"starting", "running", "unknown"} or (
                record.state == "unknown" and not record.cancel_requested
            ):
                return record.summary()
            record.cancel_requested = True
            record.cancel_note = (
                "Remote command was interrupted; check its output and side effects before retrying."
            )
            if record.process is None:
                record.state = "starting"
                try:
                    await asyncio.wait_for(
                        record.start_complete.wait(), timeout=self._PROCESS_STOP_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    record.state = "unknown"
                    record.cancel_note = "Remote process creation is still unconfirmed after cancel request."
                    return record.summary()
                if record.process is None:
                    record.state = "unknown"
                    return record.summary()
            try:
                record.process.terminate()
                await asyncio.wait_for(
                    asyncio.shield(record.wait_task), timeout=self._PROCESS_STOP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                try:
                    record.process.kill()
                    await asyncio.wait_for(
                        asyncio.shield(record.wait_task), timeout=self._PROCESS_STOP_TIMEOUT_SECONDS,
                    )
                except Exception:
                    record.state = "unknown"
                    record.cancel_note = "Remote process termination was requested but exit is unconfirmed."
            except Exception as exc:
                record.state = "unknown"
                record.cancel_note = f"Remote process termination acknowledgement was lost ({type(exc).__name__})."
            return record.summary()

    async def call_process(
        self, arguments: dict[str, Any], workspace: str, run_id: str | None = None, *,
        expected_authority_id: str | None = None,
    ) -> dict[str, Any]:
        action = str(arguments.get("action") or "start")
        if action == "start":
            return await self._start_process(
                arguments, workspace, run_id, expected_authority_id=expected_authority_id,
            )
        host, _ = self.parse_workspace(workspace)
        execution_id = str(arguments.get("execution_id") or arguments.get("session_id") or "")
        if action == "list":
            processes = [
                record.summary() for record in self._processes.values()
                if record.connection.authority and record.connection.authority.alias == host
                and record.state == "running"
                and (record.owner_run_id is None or record.owner_run_id == run_id)
            ]
            return self._ssh_process_result({"processes": processes})
        record = self._processes.get(execution_id)
        if record is None:
            return self._ssh_process_result({"error": "Unknown SSH execution_id."}, is_error=True)
        if not record.connection.authority or record.connection.authority.alias != host:
            return self._ssh_process_result({"error": "SSH process belongs to a different authority."}, is_error=True)
        if not self._process_owner_allowed(record, run_id):
            return self._ssh_process_result({"error": "SSH process belongs to a different run."}, is_error=True)
        if action in {"status", "poll"}:
            data = record.summary()
            if arguments.get("_native_poll"):
                for stream in ("stdout", "stderr"):
                    output = self._read_process_output(
                        record, stream, int(arguments.get(f"{stream}_offset", arguments.get("offset", 0))),
                        int(arguments.get("limit", 100)),
                    )
                    data[stream] = output["text"]
                    data[f"{stream}_next_offset"] = output["next_offset"]
                data["new_output"] = data["stdout"]
                data["new_stderr"] = data["stderr"]
            return self._ssh_process_result(data, is_error=record.state == "unknown")
        if action in {"read", "log", "output"}:
            try:
                data = self._read_process_output(
                    record, str(arguments.get("stream") or "stdout"),
                    int(arguments.get("offset", 0)), int(arguments.get("limit", 65536)),
                )
            except ValueError as exc:
                return self._ssh_process_result({"error": str(exc)}, is_error=True)
            return self._ssh_process_result(data)
        if action == "wait":
            timeout = arguments.get("timeout")
            idle_timeout = arguments.get("idle_timeout")
            deadline = time.monotonic() + max(0.0, float(timeout)) if timeout is not None else None
            while record.wait_task and not record.wait_task.done():
                if deadline is not None and time.monotonic() >= deadline:
                    break
                if idle_timeout is not None and time.monotonic() - record.last_output_monotonic >= float(idle_timeout):
                    break
                await asyncio.sleep(0.05)
            return self._ssh_process_result(record.summary(), is_error=record.state == "unknown")
        if action == "cancel":
            return self._ssh_process_result(
                await self._cancel_process(record), is_error=record.state == "unknown",
            )
        if action in {"write_stdin", "submit_stdin", "close_stdin", "write"}:
            writer = getattr(record.process, "stdin", None) if record.process else None
            if writer is None or record.state != "running":
                return self._ssh_process_result({"error": "SSH process stdin is unavailable."}, is_error=True)
            async with record.stdin_lock:
                try:
                    if action == "close_stdin":
                        writer.write_eof()
                        data = {"execution_id": execution_id, "closed": True}
                    else:
                        value = str(arguments.get("data", arguments.get("chars", "")))
                        if action == "submit_stdin":
                            value += "\n"
                        encoded = value.encode("utf-8")
                        writer.write(encoded)
                        await writer.drain()
                        data = {"execution_id": execution_id, "bytes_written": len(encoded)}
                except Exception as exc:
                    record.state = "unknown"
                    record.cancel_note = f"Remote stdin acknowledgement was lost ({type(exc).__name__})."
                    return self._ssh_process_result(record.summary(), is_error=True)
            return self._ssh_process_result(data)
        if action == "handoff":
            if record.state != "running":
                return self._ssh_process_result({"error": "Only a running process can be handed off."}, is_error=True)
            record.detached = True
            record.owner_run_id = None
            return self._ssh_process_result(record.summary())
        return self._ssh_process_result({"error": f"Unsupported SSH process action: {action}"}, is_error=True)

    async def cancel_run(self, run_id: str) -> None:
        await asyncio.gather(*(
            self._cancel_process(record) for record in self._processes.values()
            if record.owner_run_id == run_id and not record.detached
            and record.state in {"starting", "running", "unknown"}
        ), return_exceptions=True)

    async def close(self) -> None:
        self._closing = True
        if self._lsp_processes:
            await asyncio.gather(*(
                process._kill_owner() for process in list(self._lsp_processes)
            ), return_exceptions=True)
        if self._lsp_cleanup_tasks:
            await asyncio.gather(*list(self._lsp_cleanup_tasks), return_exceptions=True)
        if self._terminal_sessions:
            for session in list(self._terminal_sessions):
                if session.process is None and session.start_task is not None:
                    self._schedule_terminal_recovery(session, session.start_task)
            await asyncio.gather(*(
                session.close() for session in list(self._terminal_sessions)
            ), return_exceptions=True)
        await asyncio.gather(*(
            self._cancel_process(record) for record in self._processes.values()
            if record.state in {"starting", "running"}
            or (record.state == "unknown" and record.cancel_requested)
        ), return_exceptions=True)
        pending = [record.wait_task for record in self._processes.values() if record.wait_task]
        if pending:
            try:
                await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=3.0)
            except TimeoutError:
                for record in self._processes.values():
                    if record.state == "running":
                        record.state = "unknown"
                        record.cancel_note = "SSH manager closed before remote process exit was confirmed."
        if self._reaper:
            self._reaper.cancel()
            with suppress(asyncio.CancelledError):
                await self._reaper
            self._reaper = None
        for authority_id, conn in list(self._pool.items()):
            conn.client.close()
            try:
                await asyncio.wait_for(conn.client.wait_closed(), timeout=3.0)
            except TimeoutError:
                # Keep an unconfirmed transport and its resources tracked for a later
                # close attempt. A missing exit status remains unknown.
                continue
            self._pool.pop(authority_id, None)
            # A closed transport ends local channel ownership even if the remote exit
            # status cannot be confirmed.  Do not convert that unknown into success.
            for adapter in list(self._lsp_processes):
                if getattr(adapter, "_connection", None) is conn:
                    adapter._finish_owner()
            for session in list(self._terminal_sessions):
                if session.connection is conn:
                    session._transport_closed()
        if self._terminal_cleanup_tasks:
            tasks = set(self._terminal_cleanup_tasks)
            done, _pending = await asyncio.wait(tasks, timeout=3.0)
            for task in done:
                if not task.cancelled():
                    task.exception()
        for record in self._processes.values():
            self._release_process_lease(record)
        self._remote_file_observations.clear()


ssh_workspaces = SSHWorkspaceManager()
