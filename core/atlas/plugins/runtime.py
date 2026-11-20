"""Claude Code and Hermes plugin sources in Atlas' shared discovery/runtime."""

from __future__ import annotations

import asyncio
import contextvars
from contextlib import contextmanager
import functools
import hashlib
import inspect
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import structlog

from atlas.agent.enrichment import HOOK_POINTS
from atlas.plugins import patch_layer
from atlas.plugins.compatibility import ATLAS_VERSION, evaluate_plugin_compatibility

log = structlog.get_logger(__name__)

MANIFEST_NAMES = (".claude-plugin/plugin.json", "plugin.json")
MARKETPLACE_NAMES = (".claude-plugin/marketplace.json", "marketplace.json")
_GIT_RETRY_DELAYS = (0.25, 0.6)
_PLUGIN_MUTATION_OWNER: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "atlas_plugin_mutation_owner", default=None,
)


def _serializes_plugin_mutation(resolve_name: Any):
    def decorate(method: Any) -> Any:
        if asyncio.iscoroutinefunction(method):
            @functools.wraps(method)
            async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
                name = resolve_name(self, *args, **kwargs)
                with self._plugin_mutation(name):
                    return await method(self, *args, **kwargs)
            return async_wrapper

        @functools.wraps(method)
        def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            name = resolve_name(self, *args, **kwargs)
            with self._plugin_mutation(name):
                return method(self, *args, **kwargs)
        return sync_wrapper
    return decorate


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _manifest(root: Path) -> tuple[Path | None, dict[str, Any]]:
    for name in MANIFEST_NAMES:
        path = root / name
        if path.is_file():
            return path, _read_json(path)
    return None, {}


def _markdown_description(path: Path | None) -> str:
    """Read only a frontmatter description for plugin inventory; never execute content."""
    if path is None:
        return ""
    try:
        content = path.read_text(encoding="utf-8")[:16_384]
    except (OSError, UnicodeError):
        return ""
    match = re.match(r"\s*---\s*\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.DOTALL)
    if not match:
        return ""
    field = re.search(r"^description\s*:\s*(.*?)\s*$", match.group(1), re.MULTILINE)
    if not field:
        return ""
    value = field.group(1).strip().strip("'\"")
    return value[:500]


def _string_list(value: Any) -> list[str]:
    """Normalize declared capability names without exposing arbitrary config objects."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _named_declarations(value: Any, prefix: str) -> list[tuple[str, dict[str, Any]]]:
    """Project named manifest declarations without copying executable configuration."""
    if isinstance(value, dict):
        return [(str(name), spec if isinstance(spec, dict) else {}) for name, spec in value.items()]
    if isinstance(value, list):
        return [(str(item.get("name") or f"{prefix}-{index + 1}"), item) if isinstance(item, dict)
                else (str(item), {}) for index, item in enumerate(value)]
    if isinstance(value, str) and value.strip():
        return [(Path(value).stem or value, {"source": value})]
    return []


def _path_values(value: Any) -> list[str | Path]:
    if isinstance(value, (str, Path)):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, (str, Path))]
    return []


def _plugin_name(value: Any) -> str:
    name = str(value or "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("plugin name must be kebab-case")
    return name


def _inside(root: Path, value: str | Path) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else root / path
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def _expand_root(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
    if isinstance(value, list):
        return [_expand_root(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _expand_root(item, root) for key, item in value.items()}
    return value


class _DisposerStack:
    """Run plugin contribution cleanups once, in reverse registration order."""

    def __init__(self) -> None:
        self._items: list[Any] = []
        self._disposed = False

    def add(self, disposer: Any) -> None:
        if callable(disposer):
            self._items.append(disposer)

    def __len__(self) -> int:
        return len(self._items)

    async def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        for disposer in reversed(self._items):
            try:
                result = disposer()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - one cleanup must not block others
                log.warning("plugin.disposer_failed", error_type=type(exc).__name__)
        self._items.clear()


def plugin_of_source(source: str) -> str | None:
    """Plugin id behind a ``plugin:<name>...`` source string, else ``None``.

    Skill sources are ``plugin:<plugin>:<skill-dir>``; capability rows are
    ``plugin:<plugin>``. Everything else (atlas, claude-user, ...) has no owner.
    """
    if not isinstance(source, str) or not source.startswith("plugin:"):
        return None
    rest = source[len("plugin:"):]
    return rest.split(":", 1)[0] if rest else None


class PluginRealm:
    """A read/invoke facade that confines a run to selected plugin child rows.

    The realm is the consumption end of the agent preset's ``plugins`` rows
    (X8): every model-visible plugin contribution — capability rows, the skill
    index entries contributed by plugins, and model tools namespaced under a
    plugin-contributed MCP server — must be admitted here before the run sees
    it. ``plugin_allow_all`` (the preset default when no rows are listed)
    disables the confinement entirely.
    """

    def __init__(self, registry: Any, plugin_rows: list[str], *, allow_all: bool = False,
                 mcp_owners: dict[str, str] | None = None) -> None:
        self._registry = registry
        self._sources = {f"plugin:{name}" for name in plugin_rows if isinstance(name, str)}
        self._allow_all = allow_all
        # Model tool namespace → owning plugin. Servers absent from this map are
        # configured (atlas.toml / request-level), not plugin child rows, so the
        # realm does not confine them — that is ``mcp_servers``' job.
        self._mcp_owners = {
            str(server): str(owner) for server, owner in (mcp_owners or {}).items()
            if isinstance(server, str) and isinstance(owner, str)
        }

    def allows_plugin(self, plugin: str) -> bool:
        """Whether one plugin's child rows are visible inside this realm."""
        return self._allow_all or f"plugin:{plugin}" in self._sources

    def admits_plugin_source(self, source: str) -> bool:
        """Whether a ``plugin:<name>...`` source string is inside the realm.

        Non-plugin sources (built-in skills, user skills) are never confined.
        """
        owner = plugin_of_source(source)
        return owner is None or self.allows_plugin(owner)

    def allows_mcp_server(self, server: str) -> bool:
        """Whether tools namespaced under ``server`` are inside the realm.

        Unowned servers are always allowed; a plugin-contributed server is
        allowed only when its owning plugin row is selected.
        """
        owner = self._mcp_owners.get(str(server))
        return owner is None or self.allows_plugin(owner)

    def owns_server(self, server: str) -> bool:
        """Whether ``server`` was contributed by a plugin (realm-scoped, not config)."""
        return str(server) in self._mcp_owners

    def discover(self) -> list[dict[str, str]]:
        return [row for row in self._registry.discover()
                if row.get("source", "").startswith("plugin:")
                and (self._allow_all or row.get("source") in self._sources)]

    async def invoke(self, name: str, inputs: dict[str, Any] | None = None) -> Any:
        if not any(row["name"] == name for row in self.discover()):
            raise KeyError(name)
        return await self._registry.invoke(name, inputs)


class PluginRuntime:
    """Manage plugin sources and expose their components to Atlas registries."""

    def __init__(self, plugin_dirs: list[Path], state_path: Path) -> None:
        self._dirs = [Path(d) for d in plugin_dirs]
        # 专家模式装上的插件：每个是一个插件根目录，跟在普通插件后面。
        self.extra_roots: list[Path] = []
        self._state_path = Path(state_path)
        self._state: dict[str, Any] = {}
        self._enabled: dict[str, bool] = {}
        self._loaded: dict[str, dict[str, Any]] = {}
        self._disposers: dict[str, _DisposerStack] = {}
        #: Bound dependencies remembered from ``load_all`` so ``reload`` can
        #: re-attach the same hook bus / capability registry without the caller
        #: having to pass them again.
        self._wiring: dict[str, Any] = {}
        self._install_operations: dict[str, dict[str, Any]] = {}
        self._install_tasks: dict[str, asyncio.Task[None]] = {}
        self._install_processes: dict[str, asyncio.subprocess.Process] = {}
        self._install_cancel_events: dict[str, asyncio.Event] = {}
        self._install_done_events: dict[str, asyncio.Event] = {}
        self._install_approval_events: dict[str, asyncio.Event] = {}
        self._install_transaction_lock = asyncio.Lock()
        self._install_request_args: dict[str, tuple[Any, ...]] = {}
        self._runtime_epoch = uuid.uuid4().hex
        self._install_target_guard = threading.Lock()
        self._install_target_busy: dict[str, tuple[object, int]] = {}
        self._load_state()

    def _load_state(self) -> None:
        self._state = _read_json(self._state_path)
        enabled = self._state.get("enabled")
        self._enabled = enabled if isinstance(enabled, dict) else {}
        self._state["enabled"] = self._enabled
        if not isinstance(self._state.get("marketplaces"), dict):
            self._state["marketplaces"] = {}
        if not isinstance(self._state.get("sources"), dict):
            self._state["sources"] = {}
        if not isinstance(self._state.get("compatibility_exemptions"), dict):
            self._state["compatibility_exemptions"] = {}
        if not isinstance(self._state.get("script_approvals"), dict):
            self._state["script_approvals"] = {}
        if not isinstance(self._state.get("install_requests"), dict):
            self._state["install_requests"] = {}

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state["enabled"] = self._enabled
        self._state_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def _compatibility_issue(self, manifest: dict[str, Any]) -> dict[str, Any] | None:
        raw = self._state.get("compatibility_exemptions")
        exemptions = raw if isinstance(raw, dict) else {}
        try:
            return evaluate_plugin_compatibility(manifest, ATLAS_VERSION, exemptions)
        except ValueError:
            return {
                "name": str(manifest.get("name") or ""),
                "version": str(manifest.get("version") or ""),
                "runtime_version": ATLAS_VERSION,
                "peers": {"peerDependencies": "invalid"},
                "exempted": False,
            }

    def _require_compatible_manifest(self, manifest: dict[str, Any]) -> None:
        issue = self._compatibility_issue(manifest)
        if issue and not issue.get("exempted"):
            raise ValueError(f"Atlas peer compatibility check failed: {issue['peers']}")

    @staticmethod
    def _approval_timestamp(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return parsed.astimezone(timezone.utc)

    def grant_script_approval(self, package_name: str, *, expires_at: str, request_id: str) -> dict[str, str]:
        if not re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", package_name):
            raise ValueError("package_name is invalid")
        pending = self._install_operations.get(request_id)
        if (
            pending is None or pending.get("status") != "awaiting_approval"
            or package_name not in pending.get("approvalRequired", [])
        ):
            raise ValueError("script approval is stale or not requested by this install")
        expiry = self._approval_timestamp(expires_at)
        record = {"expires_at": expiry.isoformat().replace("+00:00", "Z")}
        self._state.setdefault("script_approvals", {})[package_name] = record
        self._save_state()
        for request_id, operation in self._install_operations.items():
            if operation.get("status") == "awaiting_approval" and package_name in operation.get("approvalRequired", []):
                self._install_operations[request_id]["approvalRequired"] = [
                    item for item in operation["approvalRequired"] if item != package_name
                ]
                self._install_operations[request_id]["status"] = (
                    "running" if not self._install_operations[request_id]["approvalRequired"] else "awaiting_approval"
                )
                self._install_operations[request_id]["updatedAt"] = datetime.now(timezone.utc).isoformat()
                event = self._install_approval_events.get(request_id)
                if event is not None:
                    event.set()
        return {"packageName": package_name, "expiresAt": record["expires_at"]}

    def script_approval_status(self, package_name: str, *, now: str | None = None) -> str:
        record = self._state.get("script_approvals", {}).get(package_name)
        if not isinstance(record, dict) or not isinstance(record.get("expires_at"), str):
            return "not_approved"
        try:
            expiry = self._approval_timestamp(record["expires_at"])
            current = self._approval_timestamp(now) if now else datetime.now(timezone.utc)
        except ValueError:
            return "not_approved"
        return "approved" if expiry > current else "expired"

    async def start_install_operation(
        self, source: str, *, ref: str | None = None, registry: str | None = None, request_id: str | None = None,
        on_complete: Any = None, source_type: str | None = None, marketplace: str | None = None,
        plugin_name: str | None = None,
    ) -> dict[str, Any]:
        request_id = request_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id):
            raise ValueError("requestId is invalid")
        source_type = source_type or self._infer_install_source_type(source)
        args = (source, ref, registry, source_type, marketplace, plugin_name)
        previous = self._install_request_args.get(request_id)
        if previous is not None:
            if previous != args:
                raise ValueError("requestId already belongs to a different install request")
            return self._install_snapshot(request_id)
        request_records = self._state.setdefault("install_requests", {})
        previous_record = request_records.get(request_id)
        request_digest = hashlib.sha256(json.dumps(args, ensure_ascii=True).encode("utf-8")).hexdigest()
        if isinstance(previous_record, dict):
            if previous_record.get("digest") != request_digest:
                raise ValueError("requestId already belongs to a different install request")
            raise ValueError("requestId belongs to an earlier runtime; install status is unknown")
        request_records[request_id] = {"digest": request_digest, "epoch": self._runtime_epoch}
        while len(request_records) > 256:
            request_records.pop(next(iter(request_records)))
        self._save_state()
        loop = asyncio.get_running_loop()
        self._install_operations[request_id] = {
            "requestId": request_id, "source": source, "status": "queued",
            "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat(),
            "approvalRequired": [],
        }
        self._install_cancel_events[request_id] = asyncio.Event()
        self._install_done_events[request_id] = asyncio.Event()
        self._install_approval_events[request_id] = asyncio.Event()
        self._install_request_args[request_id] = args
        task = loop.create_task(self._run_install_operation(
            request_id, source, ref, registry, on_complete, source_type, marketplace, plugin_name,
        ))
        self._install_tasks[request_id] = task
        return self._install_snapshot(request_id)

    def _install_snapshot(self, request_id: str) -> dict[str, Any]:
        operation = self._install_operations.get(request_id)
        if operation is None:
            return {"requestId": request_id, "status": "unknown"}
        return {key: value for key, value in operation.items() if key != "source"}

    def _claim_install_target(self, name: str, *, owner: object | None = None) -> object:
        owner = owner or object()
        with self._install_target_guard:
            current = self._install_target_busy.get(name)
            if current is not None and current[0] is not owner:
                raise ValueError(f"plugin mutation already in progress: {name}")
            self._install_target_busy[name] = (owner, current[1] + 1 if current else 1)
        return owner

    def _release_install_target(self, name: str, *, owner: object | None = None) -> None:
        with self._install_target_guard:
            current = self._install_target_busy.get(name)
            if current is None or (owner is not None and current[0] is not owner):
                return
            if current[1] > 1:
                self._install_target_busy[name] = (current[0], current[1] - 1)
            else:
                self._install_target_busy.pop(name, None)

    @contextmanager
    def _plugin_mutation(self, name: str):
        owner = _PLUGIN_MUTATION_OWNER.get()
        context_token = None
        if owner is None:
            owner = object()
            context_token = _PLUGIN_MUTATION_OWNER.set(owner)
        claimed = False
        try:
            self._claim_install_target(name, owner=owner)
            claimed = True
            yield
        finally:
            if claimed:
                self._release_install_target(name, owner=owner)
            if context_token is not None:
                _PLUGIN_MUTATION_OWNER.reset(context_token)

    def _ensure_install_target_idle(self, name: str) -> None:
        with self._install_target_guard:
            if name in self._install_target_busy:
                raise ValueError(f"plugin mutation already in progress: {name}")

    async def wait_install_operation(self, request_id: str, *, wait_seconds: float = 0) -> dict[str, Any]:
        if request_id not in self._install_operations:
            previous = self._state.get("install_requests", {}).get(request_id)
            response = {"requestId": request_id, "status": "unknown"}
            if isinstance(previous, dict):
                response["previousRuntime"] = True
            return response
        if wait_seconds > 0:
            try:
                await asyncio.wait_for(self._install_done_events[request_id].wait(), timeout=min(wait_seconds, 30))
            except asyncio.TimeoutError:
                pass
        return self._install_snapshot(request_id)

    async def cancel_install_operation(self, request_id: str) -> dict[str, Any]:
        operation = self._install_operations.get(request_id)
        if operation is None:
            return {"requestId": request_id, "status": "unknown"}
        if operation["status"] in {"completed", "failed", "cancelled", "too_late"} or operation.get("phase") in {"committing", "legacy_install"}:
            return {"requestId": request_id, "status": "too_late"}
        operation["status"] = "cancelling"
        operation["updatedAt"] = datetime.now(timezone.utc).isoformat()
        self._install_cancel_events[request_id].set()
        self._install_approval_events[request_id].set()
        try:
            await asyncio.wait_for(self._install_done_events[request_id].wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
        status = self._install_operations[request_id]["status"]
        return {"requestId": request_id, "status": status if status == "cancelled" else "cancelling"}

    async def close_install_operations(self) -> None:
        """Stop cancellable package-manager jobs and drain legacy installs before shutdown."""
        active = [request_id for request_id, task in self._install_tasks.items() if not task.done()]
        await asyncio.gather(
            *(self.cancel_install_operation(request_id) for request_id in active),
            return_exceptions=True,
        )
        tasks = [self._install_tasks[request_id] for request_id in active if request_id in self._install_tasks]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._install_tasks.clear()
        self._install_processes.clear()

    async def _run_package_manager(
        self, request_id: str, cwd: Path, registry: str | None, args: list[str],
    ) -> tuple[int, str]:
        node = shutil.which("node")
        pnpm_entry = self._pnpm_entry()
        if not node or pnpm_entry is None or not pnpm_entry.is_file():
            raise FileNotFoundError("Node.js and pnpm are required for plugin dependency installation")
        support = cwd.parent
        isolated_userconfig = support / "atlas-pnpm-user.npmrc"
        isolated_userconfig.write_text("", encoding="utf-8")
        command = [node, str(pnpm_entry), *args, "--ignore-pnpmfile", "--store-dir", str(support / ".pnpm-store"),
                   "--state-dir", str(support / ".pnpm-state")]
        if registry:
            command.append(f"--registry={registry}")
        isolated_env = {
            "PATH": os.environ.get("PATH", ""),
            "CI": "1",
            "NPM_CONFIG_USERCONFIG": str(isolated_userconfig),
            "APPDATA": str(support / ".appdata"),
            "LOCALAPPDATA": str(support / ".local-appdata"),
            "USERPROFILE": str(support / ".home"),
            "HOME": str(support / ".home"),
            "TEMP": str(support / ".tmp"),
            "TMP": str(support / ".tmp"),
        }
        for key in ("SystemRoot", "WINDIR", "ComSpec"):
            if os.environ.get(key):
                isolated_env[key] = os.environ[key]
        return await self._run_managed_command(request_id, cwd, command, isolated_env)

    async def _run_managed_command(
        self, request_id: str, cwd: Path, command: list[str], env: dict[str, str], *, timeout: float | None = None,
    ) -> tuple[int, str]:
        with tempfile.TemporaryFile(prefix="atlas-pnpm-") as output_file:
            process = await asyncio.create_subprocess_exec(
                *command, cwd=str(cwd), stdout=output_file,
                stderr=subprocess.STDOUT, env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            self._install_processes[request_id] = process
            exit_task = asyncio.create_task(process.wait())
            cancel_task = asyncio.create_task(self._install_cancel_events[request_id].wait())
            loop = asyncio.get_running_loop()
            deadline = loop.time() + float(timeout or getattr(self, "_package_manager_timeout", 600))
            try:
                while not exit_task.done():
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise RuntimeError("package_manager_timeout")
                    done, _ = await asyncio.wait(
                        {exit_task, cancel_task}, timeout=min(0.25, remaining),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancel_task in done and self._install_cancel_events[request_id].is_set():
                        await self._terminate_install_process_tree(process, deadline=deadline)
                        await asyncio.wait_for(exit_task, timeout=max(0.01, deadline - loop.time()))
                        output_file.flush()
                        output_file.seek(0, os.SEEK_END)
                        size = output_file.tell()
                        output_file.seek(max(0, size - 4000))
                        return -1, output_file.read(4000).decode("utf-8", errors="replace")
                    output_file.flush()
                    if os.fstat(output_file.fileno()).st_size > 8_000_000:
                        raise RuntimeError("package_manager_output_limit")
                await exit_task
                output_file.flush()
                output_file.seek(0, os.SEEK_END)
                size = output_file.tell()
                output_file.seek(max(0, size - 4000))
                output = output_file.read(4000).decode("utf-8", errors="replace")
                return int(process.returncode or 0), output
            except asyncio.CancelledError:
                if process.returncode is None:
                    try:
                        await self._terminate_install_process_tree(process, deadline=deadline)
                    except asyncio.TimeoutError:
                        process.kill()
                if not exit_task.done():
                    exit_task.cancel()
                await asyncio.gather(exit_task, return_exceptions=True)
                raise
            except Exception:
                if process.returncode is None:
                    try:
                        await self._terminate_install_process_tree(process, deadline=deadline)
                    except asyncio.TimeoutError:
                        process.kill()
                if not exit_task.done():
                    exit_task.cancel()
                await asyncio.gather(exit_task, return_exceptions=True)
                raise
            finally:
                cancel_task.cancel()
                self._install_processes.pop(request_id, None)

    @staticmethod
    def _pnpm_entry() -> Path | None:
        configured = os.environ.get("ATLAS_PNPM_ENTRY")
        if configured:
            return Path(configured)
        appdata = os.environ.get("APPDATA")
        candidate = Path(appdata) / "npm" / "node_modules" / "pnpm" / "bin" / "pnpm.mjs" if appdata else None
        return candidate

    @staticmethod
    def _infer_install_source_type(source: str) -> str:
        value = source.strip()
        if Path(value).expanduser().exists() or value.startswith((".\\", "./", "../")):
            return "local"
        if value.startswith("npm:") or re.fullmatch(r"@[a-z0-9._-]+/[a-z0-9._-]+(?:@[^\s]+)?", value, re.IGNORECASE):
            return "npm"
        if value.startswith(("https://", "http://", "ssh://", "git+https://", "git+ssh://", "git@")):
            return "git"
        if "/" in value and ":" not in value:
            return "git"
        if re.fullmatch(r"[a-z0-9._-]+(?:@[^\s]+)?", value, re.IGNORECASE):
            return "npm"
        return "local"

    @staticmethod
    def _normalize_git_source(source: str) -> str:
        value = source.strip()
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            return PluginRuntime._github_url(value)
        if value.startswith(("git+https://", "git+ssh://")):
            return value[4:]
        return value

    @staticmethod
    def _npm_package_name(spec: str) -> str:
        value = spec.removeprefix("npm:")
        if value.startswith("@"):
            scope, separator, rest = value.partition("/")
            if not separator:
                raise ValueError("invalid scoped npm package spec")
            name = rest.split("@", 1)[0]
            return f"{scope}/{name}"
        return value.split("@", 1)[0]

    @staticmethod
    def _npm_entry() -> Path | None:
        configured = os.environ.get("ATLAS_NPM_ENTRY")
        if configured:
            return Path(configured)
        appdata = os.environ.get("APPDATA")
        node = shutil.which("node")
        candidates = [
            Path(appdata) / "npm" / "node_modules" / "npm" / "bin" / "npm-cli.js" if appdata else None,
            Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js" if node else None,
        ]
        return next((path for path in candidates if path is not None and path.is_file()), None)

    async def _run_npm_pack(
        self, request_id: str, spec: str, cwd: Path, registry: str | None,
    ) -> tuple[int, str]:
        node = shutil.which("node")
        npm_entry = self._npm_entry()
        if not node or npm_entry is None:
            raise FileNotFoundError("Node.js and npm are required to fetch an npm plugin package")
        support = cwd
        userconfig = support / "atlas-npm-user.npmrc"
        userconfig.write_text("", encoding="utf-8")
        command = [node, str(npm_entry), "pack", spec.removeprefix("npm:"), "--ignore-scripts",
                   "--pack-destination", str(cwd), "--cache", str(support / ".npm-cache")]
        if registry:
            command.append(f"--registry={registry}")
        env = {
            "PATH": os.environ.get("PATH", ""), "CI": "1",
            "NPM_CONFIG_USERCONFIG": str(userconfig),
            "NPM_CONFIG_CACHE": str(support / ".npm-cache"),
            "APPDATA": str(support / ".appdata"), "LOCALAPPDATA": str(support / ".local-appdata"),
            "USERPROFILE": str(support / ".home"), "HOME": str(support / ".home"),
            "TEMP": str(support / ".tmp"), "TMP": str(support / ".tmp"),
        }
        for key in ("SystemRoot", "WINDIR", "ComSpec"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        return await self._run_managed_command(request_id, cwd, command, env, timeout=180)

    async def _run_git_clone_operation(
        self, request_id: str, url: str, target: Path, *, ref: str | None = None,
    ) -> tuple[int, str]:
        git = shutil.which("git")
        if not git:
            raise FileNotFoundError("Git is required for this plugin source")
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [git, "clone", "--depth", "1"]
        if ref:
            command.extend(["--branch", ref])
        command.extend([url, str(target)])
        env = {"PATH": os.environ.get("PATH", ""), "GIT_TERMINAL_PROMPT": "0"}
        for key in ("SystemRoot", "WINDIR", "ComSpec", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        return await self._run_managed_command(request_id, target.parent, command, env, timeout=180)

    @staticmethod
    def _extract_npm_package(archive: Path, destination: Path) -> Path:
        import tarfile

        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            for member in members:
                parts = Path(member.name).parts
                if Path(member.name).is_absolute() or ".." in parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                    raise ValueError("npm package archive contains an unsafe entry")
            bundle.extractall(destination, members=members)
        package_root = destination / "package"
        if not package_root.resolve().is_relative_to(root) or not package_root.is_dir():
            raise ValueError("npm package archive has no package root")
        return package_root

    @staticmethod
    async def _terminate_install_process_tree(
        process: asyncio.subprocess.Process, *, deadline: float | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()

        def remaining() -> float:
            if deadline is None:
                return 3.0
            value = deadline - loop.time()
            if value <= 0:
                raise asyncio.TimeoutError
            return value

        if process.returncode is not None:
            return
        if os.name == "nt" and process.pid:
            killer = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "taskkill.exe", "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                ),
                timeout=remaining(),
            )
            await asyncio.wait_for(killer.wait(), timeout=remaining())
        else:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=remaining())
        except asyncio.TimeoutError:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=remaining())

    @staticmethod
    def _blocked_build_packages(output: str) -> list[str]:
        packages: set[str] = set()
        for line in output.splitlines():
            value = line.strip().lstrip("├└─* ").strip("`'\" ")
            match = re.search(r"(@[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+|[a-zA-Z0-9._-]+)@[^\s]+", value)
            if match:
                packages.add(match.group(1))
        return sorted(packages)

    async def _run_install_operation(
        self, request_id: str, source: str, ref: str | None, registry: str | None, on_complete: Any,
        source_type: str, marketplace: str | None, requested_plugin_name: str | None,
    ) -> None:
        async with self._install_transaction_lock:
            await self._run_install_operation_locked(
                request_id, source, ref, registry, on_complete, source_type, marketplace, requested_plugin_name,
            )

    async def _run_install_operation_locked(
        self, request_id: str, source: str, ref: str | None, registry: str | None, on_complete: Any,
        source_type: str, marketplace: str | None, requested_plugin_name: str | None,
    ) -> None:
        operation = self._install_operations[request_id]
        cancel_event = self._install_cancel_events[request_id]
        stage: Path | None = None
        prepared: Path | None = None
        transaction_dir: Path | None = None
        target: Path | None = None
        backup: Path | None = None
        plugin_name = ""
        prior_source: Any = None
        had_prior_source = False
        prior_enabled: Any = None
        had_prior_enabled = False
        committed = False
        claimed_target = False
        source_workspace: Path | None = None
        source_record: dict[str, Any] = {}
        source_checkout_target: Path | None = None
        source_checkout_prepared: Path | None = None
        source_checkout_backup: Path | None = None
        source_checkout_committed = False
        target_owner: object | None = None
        terminal_status = "failed"
        terminal_error: str | None = None
        terminal_phase = "failed"
        try:
            operation.update(status="running", phase="prepare", updatedAt=datetime.now(timezone.utc).isoformat())
            if cancel_event.is_set():
                raise asyncio.CancelledError
            source_path = Path(source).expanduser()
            source_root: Path | None = None
            if source_type == "marketplace":
                if not marketplace or not requested_plugin_name:
                    raise ValueError("marketplace and plugin are required")
                record = self._state.get("marketplaces", {}).get(marketplace)
                if not isinstance(record, dict):
                    raise KeyError(marketplace)
                entry = next((item for item in self.list_marketplace_plugins(marketplace)
                              if item.get("name") == requested_plugin_name), None)
                if entry is None:
                    raise KeyError(requested_plugin_name)
                local, url, market_ref, subdir = self._resolve_plugin_source(record, entry)
                ref = ref or market_ref
                source_record = {"source": "marketplace", "marketplace": marketplace,
                                 "plugin_source": entry.get("source"), "entry": entry,
                                 "plugin_name": requested_plugin_name}
                if local is not None:
                    source_root = self._plugin_root(local)
                elif url:
                    source_workspace = Path(tempfile.mkdtemp(prefix="ag-"))
                    checkout = source_workspace / "r"
                    operation.update(status="running", phase="source_fetch")
                    code, _ = await self._run_git_clone_operation(request_id, url, checkout, ref=ref)
                    if cancel_event.is_set():
                        raise asyncio.CancelledError
                    if code != 0:
                        raise RuntimeError("source_fetch_failed")
                    source_root = self._plugin_root(checkout / subdir if subdir else checkout)
                    source_record.update({"subdir": subdir, "ref": ref})
                    source_checkout_target = self._installed_base() / ".sources" / requested_plugin_name
                else:
                    raise ValueError("unsupported marketplace plugin source")
                plugin_name = _plugin_name(requested_plugin_name)
            elif source_type == "git":
                url = self._normalize_git_source(source)
                source_workspace = Path(tempfile.mkdtemp(prefix="ag-"))
                checkout = source_workspace / "r"
                operation.update(status="running", phase="source_fetch")
                code, _ = await self._run_git_clone_operation(request_id, url, checkout, ref=ref)
                if cancel_event.is_set():
                    raise asyncio.CancelledError
                if code != 0:
                    raise RuntimeError("source_fetch_failed")
                source_root = self._plugin_root(checkout)
                plugin_name = _plugin_name(Path(url.rstrip("/")).name.removesuffix(".git"))
                source_record = {"source": "git", "url": url, "ref": ref, "plugin_name": plugin_name}
                source_checkout_target = self._installed_base() / ".sources" / plugin_name
            elif source_type == "npm":
                spec = source.removeprefix("npm:")
                source_workspace = Path(tempfile.mkdtemp(prefix="an-"))
                operation.update(status="running", phase="source_fetch")
                code, _ = await self._run_npm_pack(request_id, spec, source_workspace, registry)
                if cancel_event.is_set():
                    raise asyncio.CancelledError
                if code != 0:
                    raise RuntimeError("source_fetch_failed")
                archives = sorted(source_workspace.glob("*.tgz"))
                if len(archives) != 1:
                    raise ValueError("npm source did not resolve to exactly one package")
                source_root = self._extract_npm_package(archives[0], source_workspace / "unpacked")
                source_record = {"source": "npm", "spec": spec}
            else:
                if self._marketplace_root(source_path):
                    raise ValueError("register a marketplace before installing one of its plugins")
                source_root = self._plugin_root(source_path)
                if source_root is None:
                    raise ValueError("plugin manifest/components not found in local source")
                manifest = self._effective_manifest_for_root(source_root)
                plugin_name = str(manifest.get("name") or source_root.name)
                source_record = {"source": "local", "path": str(source_root.resolve()), "plugin_name": plugin_name}

            if source_root is None:
                raise ValueError("plugin manifest/components not found in source")
            _, base_manifest = _manifest(source_root)
            manifest = self._effective_manifest(source_root, base_manifest, source_record)
            self._require_compatible_manifest(manifest)
            validation = await asyncio.to_thread(self.validate, source_root, source_record=source_record)
            if not validation.get("valid"):
                raise ValueError("plugin manifest validation failed")
            plugin_name = _plugin_name(str(source_record.get("plugin_name") or manifest.get("name") or plugin_name))
            source_record["plugin_name"] = plugin_name
            target_owner = object()
            self._claim_install_target(plugin_name, owner=target_owner)
            claimed_target = True
            base = self._installed_base()
            transaction_root = base / ".transactions"
            transaction_id = uuid.uuid4().hex[:16]
            transaction_dir = transaction_root / transaction_id
            stage = Path(tempfile.mkdtemp(prefix="ap-")) / "p"
            prepared = base / f".prepared-{transaction_id}"
            target_dir = source_root.name if source_type == "local" else (requested_plugin_name if source_type == "marketplace" else plugin_name)
            target = base / target_dir
            backup = transaction_root / transaction_id / "previous"
            shutil.copytree(source_root, stage, ignore=shutil.ignore_patterns(".git"))
            package_file = stage / "package.json"
            package = _read_json(package_file) if package_file.is_file() else {}
            if package_file.is_file() and any(package.get(field) for field in ("dependencies", "optionalDependencies", "devDependencies")):
                import yaml

                operation.update(status="running", phase="dependencies", approvalRequired=[])
                original_package = package_file.read_bytes()
                workspace_file = stage / "pnpm-workspace.yaml"
                original_workspace = workspace_file.read_bytes() if workspace_file.is_file() else None
                workspace_value = yaml.safe_load(original_workspace) if original_workspace else {}
                safe_workspace = dict(workspace_value) if isinstance(workspace_value, dict) else {}
                for field in (
                    "pnpmfile", "allowBuilds", "onlyBuiltDependencies", "ignoredBuiltDependencies",
                    "dangerouslyAllowAllBuilds",
                ):
                    safe_workspace.pop(field, None)
                safe_workspace["dangerouslyAllowAllBuilds"] = False
                nested_pnpm = safe_workspace.get("pnpm")
                if isinstance(nested_pnpm, dict):
                    nested_pnpm = dict(nested_pnpm)
                    for field in (
                        "configDependencies", "onlyBuiltDependencies", "ignoredBuiltDependencies",
                        "neverBuiltDependencies", "allowBuilds", "dangerouslyAllowAllBuilds",
                    ):
                        nested_pnpm.pop(field, None)
                    nested_pnpm["dangerouslyAllowAllBuilds"] = False
                    safe_workspace["pnpm"] = nested_pnpm
                safe_package = dict(package)
                safe_package.pop("scripts", None)
                pnpm_config = safe_package.get("pnpm")
                if isinstance(pnpm_config, dict):
                    pnpm_config = dict(pnpm_config)
                    for field in (
                        "configDependencies", "onlyBuiltDependencies", "ignoredBuiltDependencies",
                        "neverBuiltDependencies", "allowBuilds", "dangerouslyAllowAllBuilds",
                    ):
                        pnpm_config.pop(field, None)
                    pnpm_config["dangerouslyAllowAllBuilds"] = False
                    safe_package["pnpm"] = pnpm_config
                try:
                    package_file.write_text(json.dumps(safe_package, ensure_ascii=False, indent=2), encoding="utf-8")
                    workspace_file.write_text(yaml.safe_dump(safe_workspace, allow_unicode=True, sort_keys=False), encoding="utf-8")
                    code, install_output = await self._run_package_manager(
                        request_id, stage, registry, ["install", "--reporter=append-only"],
                    )
                    if cancel_event.is_set():
                        raise asyncio.CancelledError
                    blocked = self._blocked_build_packages(install_output)
                    if code != 0 and not ("ERR_PNPM_IGNORED_BUILDS" in install_output and blocked):
                        raise RuntimeError("package_manager_failed")
                    if code == 0 and blocked:
                        raise RuntimeError("unexpected_blocked_build_report")
                    operation["blockedPackages"] = blocked
                    missing = [name for name in blocked if self.script_approval_status(name) != "approved"]
                    while missing:
                        if cancel_event.is_set():
                            raise asyncio.CancelledError
                        operation.update(status="awaiting_approval", phase="script_approval", approvalRequired=missing,
                                         updatedAt=datetime.now(timezone.utc).isoformat())
                        event = self._install_approval_events[request_id]
                        await event.wait()
                        event.clear()
                        missing = [name for name in blocked if self.script_approval_status(name) != "approved"]
                    if blocked:
                        operation.update(status="running", phase="approved_build", approvalRequired=[])
                        safe_workspace["allowBuilds"] = {name: True for name in blocked}
                        workspace_file.write_text(yaml.safe_dump(safe_workspace, allow_unicode=True, sort_keys=False), encoding="utf-8")
                        code, approved_output = await self._run_package_manager(
                            request_id, stage, registry, ["install", "--reporter=append-only"],
                        )
                        if cancel_event.is_set():
                            raise asyncio.CancelledError
                        if code != 0:
                            raise RuntimeError("approved_build_failed")
                        operation["executedBuildPackages"] = blocked
                        if "ERR_PNPM_IGNORED_BUILDS" in approved_output:
                            raise RuntimeError("approved_build_failed")
                finally:
                    package_file.write_bytes(original_package)
                    if original_workspace is None:
                        workspace_file.unlink(missing_ok=True)
                    else:
                        workspace_file.write_bytes(original_workspace)
            if cancel_event.is_set():
                raise asyncio.CancelledError
            operation.update(status="running", phase="committing", updatedAt=datetime.now(timezone.utc).isoformat())
            await asyncio.to_thread(self._copy_replace, stage, prepared, previous=target)
            sources = self._state.setdefault("sources", {})
            had_prior_source = plugin_name in sources
            prior_source = sources.get(plugin_name)
            enabled = self._enabled
            had_prior_enabled = plugin_name in enabled
            prior_enabled = enabled.get(plugin_name)
            if source_checkout_target is not None and source_workspace is not None:
                checkout = source_workspace / "r"
                source_checkout_prepared = source_checkout_target.parent / f".prepared-{transaction_id}"
                source_checkout_backup = transaction_dir / "previous-source"
                source_checkout_target.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copytree, checkout, source_checkout_prepared)
                if source_checkout_target.exists():
                    source_checkout_backup.parent.mkdir(parents=True, exist_ok=True)
                    source_checkout_target.replace(source_checkout_backup)
                source_checkout_prepared.replace(source_checkout_target)
                source_checkout_committed = True
                source_record["checkout"] = str(source_checkout_target)
            if target.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.replace(backup)
            prepared.replace(target)
            committed = True
            sources[plugin_name] = source_record
            if source_type == "marketplace":
                self._enabled.setdefault(plugin_name, manifest.get("defaultEnabled", True) is not False)
            await asyncio.to_thread(self._save_state)
            operation["result"] = {"name": plugin_name, "path": str(target)}
            if on_complete is not None:
                report = on_complete()
                if inspect.isawaitable(report):
                    report = await report
                operation["report"] = report
            terminal_status = "completed"
            terminal_phase = "complete"
            if committed and backup is not None and backup.exists():
                await asyncio.to_thread(self._rmtree, backup)
        except asyncio.CancelledError:
            terminal_status = "cancelled"
            terminal_phase = "cancelled"
        except Exception as exc:
            operation["failureType"] = type(exc).__name__
            terminal_error = str(exc) if isinstance(exc, ValueError) else (
                str(exc) if isinstance(exc, RuntimeError) and str(exc) in {
                    "package_manager_failed", "approved_build_failed", "package_manager_timeout",
                    "package_manager_output_limit", "source_fetch_failed",
                } else "package_manager_failed" if isinstance(exc, RuntimeError) else type(exc).__name__
            )
            terminal_phase = "failed"
            operation["rollback"] = ["package.json", "pnpm-lock.yaml"]
            if backup is not None and backup.exists() and target is not None:
                if target.exists():
                    await asyncio.to_thread(self._rmtree, target)
                backup.replace(target)
            elif committed and target is not None and target.exists():
                await asyncio.to_thread(self._rmtree, target)
            if source_checkout_backup is not None and source_checkout_backup.exists() and source_checkout_target is not None:
                if source_checkout_target.exists():
                    await asyncio.to_thread(self._rmtree, source_checkout_target)
                source_checkout_backup.replace(source_checkout_target)
            elif source_checkout_committed and source_checkout_target is not None and source_checkout_target.exists():
                await asyncio.to_thread(self._rmtree, source_checkout_target)
            if committed and target is not None:
                sources = self._state.setdefault("sources", {})
                if had_prior_source:
                    sources[plugin_name] = prior_source
                else:
                    sources.pop(plugin_name, None)
                if had_prior_enabled:
                    self._enabled[plugin_name] = prior_enabled
                else:
                    self._enabled.pop(plugin_name, None)
                await asyncio.to_thread(self._save_state)
                if on_complete is not None:
                    try:
                        refreshed = on_complete()
                        if inspect.isawaitable(refreshed):
                            await refreshed
                    except Exception:
                        pass
        finally:
            if stage is not None and stage.parent.exists():
                await asyncio.to_thread(self._rmtree, stage.parent)
            if prepared is not None and prepared.exists():
                await asyncio.to_thread(self._rmtree, prepared)
            if source_checkout_prepared is not None and source_checkout_prepared.exists():
                await asyncio.to_thread(self._rmtree, source_checkout_prepared)
            if transaction_dir is not None and transaction_dir.exists():
                await asyncio.to_thread(self._rmtree, transaction_dir)
            if source_workspace is not None and source_workspace.exists():
                await asyncio.to_thread(self._rmtree, source_workspace)
            if claimed_target:
                self._release_install_target(plugin_name, owner=target_owner)
            operation["updatedAt"] = datetime.now(timezone.utc).isoformat()
            operation["status"] = terminal_status
            operation["phase"] = terminal_phase
            if terminal_error is not None:
                operation["error"] = terminal_error
            self._install_done_events[request_id].set()

    def grant_compatibility_exemption(
        self, name: str, version: str, runtime_version: str, *, accept_risk: bool,
    ) -> dict[str, Any] | None:
        """Grant an exact plugin/runtime exemption after explicit risk acceptance."""
        if accept_risk is not True:
            raise ValueError("acceptRisk=true is required to bypass the peer compatibility block")
        if runtime_version != ATLAS_VERSION:
            raise ValueError("compatibility exemption runtime version is stale")
        plugin = next((item for item in self.discover() if item["name"] == name), None)
        if plugin is None:
            raise ValueError(f"plugin not found: {name}")
        root = Path(plugin["path"])
        _, base_manifest = _manifest(root)
        source = self._state.get("sources", {}).get(name) or self._state.get("sources", {}).get(root.name, {})
        manifest = self._effective_manifest(root, base_manifest, source)
        if str(manifest.get("version") or "") != version:
            raise ValueError("compatibility exemption plugin version is stale")
        if self._compatibility_issue(manifest) is None:
            raise ValueError("plugin has no Atlas peer compatibility mismatch to exempt")
        key = f"{name}@{version}"
        exemptions = self._state.setdefault("compatibility_exemptions", {})
        runtimes = set(exemptions.get(key, [])) if isinstance(exemptions.get(key), list) else set()
        runtimes.add(runtime_version)
        if runtimes:
            exemptions[key] = sorted(runtimes)
        self._save_state()
        return self._compatibility_issue(manifest)

    def revoke_compatibility_exemption(
        self, name: str, version: str, runtime_version: str,
    ) -> dict[str, Any] | None:
        """Revoke only this exact plugin-version/runtime-version exemption."""
        if runtime_version != ATLAS_VERSION:
            raise ValueError("compatibility exemption runtime version is stale")
        plugin = next((item for item in self.discover() if item["name"] == name), None)
        if plugin is None:
            raise ValueError(f"plugin not found: {name}")
        root = Path(plugin["path"])
        _, base_manifest = _manifest(root)
        source = self._state.get("sources", {}).get(name) or self._state.get("sources", {}).get(root.name, {})
        manifest = self._effective_manifest(root, base_manifest, source)
        if str(manifest.get("version") or "") != version:
            raise ValueError("compatibility exemption plugin version is stale")
        key = f"{name}@{version}"
        exemptions = self._state.setdefault("compatibility_exemptions", {})
        runtimes = set(exemptions.get(key, [])) if isinstance(exemptions.get(key), list) else set()
        runtimes.discard(runtime_version)
        if runtimes:
            exemptions[key] = sorted(runtimes)
        else:
            exemptions.pop(key, None)
        self._save_state()
        return self._compatibility_issue(manifest)

    @staticmethod
    def _plugin_root(path: Path) -> Path | None:
        if _manifest(path)[0] is not None:
            return path
        if any((path / item).exists() for item in ("skills", "commands", "agents", "hooks", ".mcp.json")):
            return path
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_dir() and PluginRuntime._plugin_root(child) == child:
                    return child
        return None

    def _all_plugin_roots(self) -> list[Path]:
        roots: list[Path] = []
        for base in self._dirs:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if child.name.startswith("."):
                    continue
                root = self._plugin_root(child)
                if root is not None and root not in roots:
                    roots.append(root)
        for extra in self.extra_roots:
            root = self._plugin_root(extra) if extra.is_dir() else None
            if root is not None and root not in roots:
                roots.append(root)
        return roots

    def discover(self) -> list[dict[str, Any]]:
        """List available plugin bundles, preferring user-installed copies."""
        plugins: dict[str, dict[str, Any]] = {}
        for root in self._all_plugin_roots():
            manifest_path, base_manifest = _manifest(root)
            # Source records are keyed by plugin name; marketplace/git installs
            # use the installed directory name, local installs the manifest name.
            source = self._source_for_root(root, base_manifest)
            manifest = self._effective_manifest(root, base_manifest, source)
            try:
                name = _plugin_name(source.get("plugin_name") or manifest.get("name") or root.name)
            except ValueError:
                continue  # unaddressable directory; never fail the whole listing
            enabled = self._enabled.get(name, manifest.get("defaultEnabled", True)) is not False
            loaded = name in self._loaded
            try:
                installed = root.resolve().is_relative_to(self._installed_base().resolve())
            except (OSError, ValueError):
                installed = False
            # There is no verified official-source trust store yet. Preserve an
            # upstream/source claim as an attestation field, but never label it
            # "official" without a verifier.
            official_attestation = source.get("official") if isinstance(source, dict) else None
            if not isinstance(official_attestation, bool):
                official_attestation = None
            overrides = patch_layer.list_patches(root).get("patches", [])
            plugin_info = {
                "name": name,
                "display_name": str(manifest.get("displayName") or name),
                "version": str(manifest.get("version", "0.0.0")),
                "description": str(manifest.get("description", "")),
                "author": manifest.get("author", {}),
                "homepage": str(manifest.get("homepage", "")),
                "repository": str(manifest.get("repository", "")),
                "license": str(manifest.get("license", "")),
                "keywords": manifest.get("keywords", []),
                "metadata": manifest.get("metadata", {}),
                "manifest": str(manifest_path) if manifest_path else None,
                "path": str(root),
                "source": source.get("source", "local") if isinstance(source, dict) else "local",
                "official": None,
                "official_attestation": official_attestation,
                "availability": {"available": True, "reason": "plugin manifest discovered"},
                "installed": installed,
                "overrides": [
                    {key: patch.get(key) for key in ("path", "row_id", "order", "note")}
                    for patch in overrides
                ],
                "marketplace": source.get("marketplace") if isinstance(source, dict) else None,
                "skills": [path.name for path in self._component_paths(root, manifest, "skills", root / "skills", directories=True)],
                "commands": [item["name"] for item in self._commands(root, manifest)],
                "agents": [path.stem for path in self._component_paths(root, manifest, "agents", root / "agents", files=True)],
                "hooks": len(self._claude_hook_specs(root, manifest)) + len([
                    spec for spec in self._legacy_hook_specs(root)
                    if str(spec.get("point", "")) in HOOK_POINTS
                ]),
                "mcp_servers": sorted(self._mcp_configs(root, manifest)),
                "compatibility": self._compatibility_issue(manifest),
                "enabled": enabled,
                "loaded": loaded,
                "update_available": bool(source.get("update_available", False)) if isinstance(source, dict) else False,
                "update_error": str(source.get("update_error") or "") if isinstance(source, dict) else "",
            }
            plugin_info["capability_groups"] = self._capability_projection(
                root, manifest, loaded_state=self._loaded.get(name) if enabled else None,
                plugin_source=plugin_info["source"],
            )
            plugins[name] = plugin_info
        return list(plugins.values())

    def put_config_layer(self, kind: str, name: str, rows: dict[str, Any]) -> None:
        """Persist a named profile/bundle or ordered row-id patch layer."""
        if kind not in {"profile", "bundle", "patches"}:
            raise ValueError("kind must be profile, bundle, or patches")
        if not isinstance(name, str) or not name.strip() or not isinstance(rows, dict):
            raise ValueError("a non-empty layer name and object rows are required")
        layers = self._state.setdefault("config_layers", {})
        layers.setdefault(kind, {})[name.strip()] = rows
        self._save_state()

    def config_layers(self, profile: str | None = None, bundle: str | None = None) -> dict[str, Any]:
        """Compose profile, bundle, then row-id patches into an inspectable snapshot."""
        layers = self._state.get("config_layers", {})
        if not isinstance(layers, dict):
            layers = {}
        selected: dict[str, dict[str, Any]] = {}
        for kind, name in (("profile", profile), ("bundle", bundle)):
            candidates = layers.get(kind, {})
            value = candidates.get(name, {}) if name and isinstance(candidates, dict) else {}
            selected[kind] = value if isinstance(value, dict) else {}
        patches = layers.get("patches", {})
        patch_rows: dict[str, Any] = {}
        if isinstance(patches, dict):
            for patchset in patches.values():
                if isinstance(patchset, dict):
                    patch_rows.update(patchset)
        selected["patches"] = patch_rows
        merged: dict[str, Any] = {}
        for kind in ("profile", "bundle", "patches"):
            for key, value in selected[kind].items():
                row_id = key[4:] if key.startswith("row:") else None
                if row_id:
                    if value is None:
                        merged.pop(row_id, None)
                    else:
                        merged[row_id] = value
                elif isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
        return {"profile": selected["profile"], "bundle": selected["bundle"],
                "patches": selected["patches"], "merged": merged}

    def _capability_projection(
        self, root: Path, manifest: dict[str, Any], *, loaded_state: Any, plugin_source: str,
    ) -> list[dict[str, Any]]:
        """Describe installed contributions and risk without loading or executing them."""
        permissions = manifest.get("permissions") if isinstance(manifest.get("permissions"), dict) else {}
        requested_tools = _string_list(permissions.get("tools"))
        network_declared = permissions.get("network")
        package_loaded = loaded_state is not None
        if network_declared is False or network_declared is None:
            network_label = "未声明"
        elif network_declared is True:
            network_label = "声明可联网（范围未限定）"
        else:
            scopes = []
            for scope in _string_list(network_declared):
                host = urlsplit(scope).hostname if "://" in scope else None
                scopes.append(host or scope[:100])
            network_label = "声明范围：" + ("、".join(scopes) if scopes else "已声明")

        def capability(kind: str, name: str, description: str, source_path: str | Path | None,
                       *, execution: str = "runtime", network: str | None = None,
                       tools: list[str] | None = None, item_loaded: bool | None = None) -> dict[str, Any]:
            relative = "清单未提供来源路径"
            if source_path:
                try:
                    relative = Path(source_path).resolve().relative_to(root.resolve()).as_posix()
                except (OSError, ValueError):
                    relative = "插件目录外来源"
            return {
                "kind": kind, "name": name[:160], "description": description[:500],
                "source": relative, "source_type": str(plugin_source),
                "loaded": (package_loaded if item_loaded is None else item_loaded) and execution == "runtime",
                "execution": execution, "requested_tools": list(tools if tools is not None else requested_tools),
                "network_access": network or network_label,
                "approval": "无插件能力逐项审批；按 Atlas 当前运行策略执行",
            }

        groups: list[dict[str, Any]] = []
        skills = self._component_paths(root, manifest, "skills", root / "skills", directories=True)
        loaded_skills = set(loaded_state.get("skills", [])) if isinstance(loaded_state, dict) else set()
        skill_items = [capability("skill", path.name, _markdown_description(path / "SKILL.md"), path / "SKILL.md",
                                  item_loaded=path.name in loaded_skills) for path in skills]
        groups.append({"kind": "skill", "label": "技能", "count": len(skill_items), "items": skill_items})

        commands = self._commands(root, manifest)
        command_items = [
            capability("command", item["name"],
                       str(item.get("metadata", {}).get("description") or _markdown_description(Path(item["path"]) if item.get("path") else None)),
                       item.get("path"),
                       item_loaded=isinstance(loaded_state, dict) and item["name"] in set(loaded_state.get("commands", [])))
            for item in commands
        ]
        groups.append({"kind": "command", "label": "命令", "count": len(command_items), "items": command_items})

        agents = self._component_paths(root, manifest, "agents", root / "agents", files=True)
        agent_items = [capability("agent", path.stem, _markdown_description(path), path) for path in agents]
        groups.append({"kind": "agent", "label": "Agent", "count": len(agent_items), "items": agent_items})

        claude_hook_specs = self._claude_hook_specs(root, manifest)
        legacy_hook_specs = [spec for spec in self._legacy_hook_specs(root) if str(spec.get("point", "")) in HOOK_POINTS]
        hook_specs = [(spec, True) for spec in claude_hook_specs] + [(spec, False) for spec in legacy_hook_specs]
        declared_hooks = manifest.get("hooks")
        hook_source: str | Path = "hooks/hooks.json"
        if isinstance(declared_hooks, str):
            hook_source = declared_hooks
        elif isinstance(declared_hooks, list):
            hook_source = next((item for item in declared_hooks if isinstance(item, str)), ".claude-plugin/plugin.json")
        elif isinstance(declared_hooks, dict):
            hook_source = ".claude-plugin/plugin.json" if (root / ".claude-plugin/plugin.json").is_file() else "plugin.json"
        hook_items = []
        loaded_hook_count = int(loaded_state.get("hooks", 0)) if isinstance(loaded_state, dict) else 0
        for index, (spec, claude_hook) in enumerate(hook_specs):
            point = str(spec.get("point") or spec.get("event") or "Hook")
            matcher = str(spec.get("matcher") or "")
            name = f"{point}: {matcher}" if matcher else point
            hook_items.append(capability("hook", f"{name} #{index + 1}", "插件 Hook 配置；触发时可运行插件命令。",
                                         hook_source, network="运行命令的网络能力未静态限定",
                                         item_loaded=package_loaded if claude_hook else index - len(claude_hook_specs) < loaded_hook_count))
        groups.append({"kind": "hook", "label": "Hook", "count": len(hook_items), "items": hook_items})

        servers = self._mcp_configs(root, manifest)
        manifest_source = ".claude-plugin/plugin.json" if (root / ".claude-plugin/plugin.json").is_file() else "plugin.json"
        mcp_source = ".mcp.json" if (root / ".mcp.json").is_file() else (
            manifest_source
        )
        mcp_items = []
        for server_name, spec in sorted(servers.items()):
            endpoint = str(spec.get("url") or "")
            host = urlsplit(endpoint).hostname if endpoint else None
            network = f"远程端点 {host}" if host else "stdio 进程的网络能力未静态限定"
            mcp_items.append(capability("mcp", server_name, str(spec.get("description") or "MCP server 提供运行时工具。"),
                                        mcp_source, network=network,
                                        tools=_string_list(spec.get("tools")) or ["MCP 工具由服务端运行时提供"],
                                        item_loaded=server_name in (loaded_state.get("mcp", []) if isinstance(loaded_state, dict) else [])))
        groups.append({"kind": "mcp", "label": "MCP", "count": len(mcp_items), "items": mcp_items})

        tool_entries = _named_declarations(manifest.get("tools"), "tool")
        tool_items = [capability("tool", name, str(spec.get("description") or "Atlas 当前不会执行插件 tools 声明。"),
                                 spec.get("source") or manifest_source, execution="metadata-only",
                                 tools=_string_list(spec.get("tools"))) for name, spec in tool_entries]
        groups.append({"kind": "tool", "label": "工具声明", "count": len(tool_items), "items": tool_items})

        for field, kind, label in (("outputStyles", "output-style", "输出样式"), ("lspServers", "lsp-server", "语言服务")):
            declarations = _named_declarations(manifest.get(field), kind)
            items = [capability(kind, name, str(spec.get("description") or f"Atlas 当前仅展示 {label} 声明，不会从插件目录启动它。"),
                                spec.get("source") or manifest_source, execution="metadata-only",
                                tools=_string_list(spec.get("tools"))) for name, spec in declarations]
            groups.append({"kind": kind, "label": label, "count": len(items), "items": items})
        return groups

    def validate(
        self, source: str | Path, *, source_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate a plugin manifest and explain path, contribution and name conflicts."""
        diagnostics: list[dict[str, str]] = []

        def add(severity: str, code: str, message: str, path: str = "") -> None:
            diagnostics.append({"severity": severity, "code": code, "message": message, "path": path})

        source_path = Path(source).expanduser()
        root = self._plugin_root(source_path)
        if root is None:
            add("error", "plugin_root_missing", "没有找到 plugin.json 或插件组件目录；请检查来源路径。", str(source_path))
            return {"valid": False, "source": str(source_path), "plugin": None, "diagnostics": diagnostics,
                    "summary": {"errors": 1, "warnings": 0}, "policy": {"status": "not_configured", "diagnostics": []}}

        manifest_path, manifest = _manifest(root)
        if manifest_path is None:
            add("warning", "manifest_missing", "未找到 plugin.json；Atlas 会按默认目录发现组件。可添加 plugin.json 声明版本和组件。", str(root))
            manifest = {"name": root.name, "version": "0.0.0"}
        else:
            try:
                parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                add("error", "manifest_parse", f"清单无法解析：{type(exc).__name__}。请修正 JSON 格式。", str(manifest_path))
                parsed = None
            if not isinstance(parsed, dict):
                if parsed is not None:
                    add("error", "manifest_type", "清单顶层必须是 JSON 对象。", str(manifest_path))
                manifest = {}
            else:
                manifest = parsed

        if source_record is None:
            source_record = self._source_for_root(root, manifest)
        manifest = self._effective_manifest(root, manifest, source_record)

        raw_name = manifest.get("name")
        try:
            name = _plugin_name(raw_name or root.name)
        except ValueError as exc:
            name = str(raw_name or root.name)
            add("error", "invalid_name", f"{exc}；名称需使用小写字母、数字和连字符。", "name")
        version = manifest.get("version", "0.0.0")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
            add("error", "invalid_version", "version 必须是 MAJOR.MINOR.PATCH 版本字符串。", "version")

        allowed = {"name", "version", "description", "displayName", "author", "homepage", "repository",
                   "license", "keywords", "metadata", "defaultEnabled", "skills", "commands", "agents",
                   "hooks", "mcpServers", "tools", "permissions", "outputStyles", "lspServers",
                   "peerDependencies"}
        for key in sorted(set(manifest) - allowed):
            add("warning", "unknown_field", f"字段 {key} 不在 Atlas 支持清单中，会被忽略。", key)
        for key in ("description", "displayName", "homepage", "repository", "license"):
            if key in manifest and not isinstance(manifest[key], str):
                add("error", "invalid_field_type", f"{key} 必须是文本。", key)
        for key in ("skills", "agents", "commands"):
            value = manifest.get(key)
            if value is not None and not isinstance(value, (str, list, dict)):
                add("error", "invalid_component_declaration", f"{key} 必须是路径、路径数组或命令映射。", key)
            if isinstance(value, list) and any(not isinstance(item, str) for item in value):
                add("error", "invalid_component_declaration", f"{key} 数组成员必须是路径文本。", key)
            if key in {"skills", "agents"} and isinstance(value, dict):
                add("error", "invalid_component_declaration", f"{key} 只接受路径或路径数组。", key)
        commands_declared = manifest.get("commands")
        if isinstance(commands_declared, dict):
            for command_name, spec in commands_declared.items():
                if not isinstance(command_name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", command_name):
                    add("error", "command_name_invalid", f"命令名 {command_name!r} 无效。", "commands")
                if not isinstance(spec, dict) or not (isinstance(spec.get("source"), str) or isinstance(spec.get("content"), str)):
                    add("error", "command_definition_invalid", f"命令 {command_name} 必须提供 source 路径或 content 文本。", "commands")
        hooks_declared = manifest.get("hooks")
        if hooks_declared is not None:
            hook_values = hooks_declared if isinstance(hooks_declared, list) else [hooks_declared]
            if not isinstance(hooks_declared, (str, list, dict)) or any(not isinstance(item, (str, dict)) for item in hook_values):
                add("error", "hooks_declaration_invalid", "hooks 必须是配置路径、路径/配置数组或 Hook 对象。", "hooks")
        mcp_declared = manifest.get("mcpServers")
        if mcp_declared is not None and not isinstance(mcp_declared, (str, list, dict)):
            add("error", "mcp_declaration_invalid", "mcpServers 必须是配置路径、路径数组或服务映射。", "mcpServers")
        for key, expected in (("keywords", list), ("metadata", dict), ("author", (str, dict)), ("defaultEnabled", bool)):
            if key in manifest and not isinstance(manifest[key], expected):
                add("error", "invalid_field_type", f"{key} 类型不符合 manifest schema。", key)
        if "tools" in manifest and not isinstance(manifest["tools"], (str, list, dict)):
            add("error", "invalid_component_declaration", "tools 必须是名称、数组或映射；Atlas 目前只显示该声明，不会执行插件工具。", "tools")
        if "permissions" in manifest and not isinstance(manifest["permissions"], dict):
            add("error", "invalid_field_type", "permissions 必须是对象；其中工具/网络声明用于风险投影。", "permissions")
        peer_dependencies = manifest.get("peerDependencies")
        if peer_dependencies is not None and (
            not isinstance(peer_dependencies, dict)
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in peer_dependencies.items())
        ):
            add("error", "peer_dependencies_invalid", "peerDependencies 必须是包名到版本范围的文本映射。", "peerDependencies")
        compatibility = self._compatibility_issue(manifest)
        if compatibility and not compatibility["exempted"]:
            add("error", "atlas_peer_incompatible",
                f"插件要求的 Atlas peer 范围与当前运行时 {ATLAS_VERSION} 不兼容；需升级插件，或显式接受风险后为此精确版本豁免。",
                "peerDependencies")
        elif compatibility:
            add("warning", "atlas_peer_exemption_active",
                f"此插件版本已对 Atlas {ATLAS_VERSION} 启用精确版本兼容豁免。",
                "peerDependencies")

        for field in ("skills", "agents", "commands"):
            value = manifest.get(field)
            refs = ([*value.keys()] if field == "commands" and isinstance(value, dict) else _path_values(value))
            if field == "commands" and isinstance(value, dict):
                refs = [spec.get("source") for spec in value.values() if isinstance(spec, dict) and spec.get("source")]
            for ref in refs:
                if not isinstance(ref, (str, Path)):
                    continue
                try:
                    target = _inside(root, ref)
                    if not target.exists():
                        add("error", "component_path_missing", f"声明的 {field} 路径不存在：{ref}。", field)
                except (OSError, ValueError):
                    add("error", "component_path_escape", f"声明的 {field} 路径无效或越出插件目录：{ref}。", field)
        mcp_declared = manifest.get("mcpServers")
        mcp_refs = mcp_declared if isinstance(mcp_declared, list) else [mcp_declared]
        for ref in mcp_refs:
            if isinstance(ref, str):
                try:
                    target = _inside(root, ref)
                    if not target.is_file():
                        add("error", "mcp_path_missing", f"MCP 配置文件不存在：{ref}。", "mcpServers")
                except (OSError, ValueError):
                    add("error", "mcp_path_escape", f"MCP 配置路径无效或越出插件目录：{ref}。", "mcpServers")

        mcp_config_paths = [root / ".mcp.json"]
        for ref in mcp_refs:
            if isinstance(ref, str):
                try:
                    candidate = _inside(root, ref)
                    if candidate.is_file():
                        mcp_config_paths.append(candidate)
                except (OSError, ValueError):
                    pass
        seen_mcp_names: set[str] = set()
        for config_path in mcp_config_paths:
            if not config_path.is_file():
                continue
            try:
                config_data = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                add("error", "mcp_config_parse", f"MCP 配置无法解析：{config_path.name}。", "mcpServers")
                continue
            servers = config_data.get("mcpServers") if isinstance(config_data, dict) else None
            if not isinstance(servers, dict):
                add("error", "mcp_config_schema", f"{config_path.name} 必须包含 mcpServers 对象。", "mcpServers")
                continue
            for server_name, spec in servers.items():
                if server_name in seen_mcp_names:
                    add("error", "mcp_duplicate_name", f"插件内 MCP 服务名 {server_name} 被重复定义。", "mcpServers")
                seen_mcp_names.add(str(server_name))
                if not isinstance(server_name, str) or not isinstance(spec, dict):
                    add("error", "mcp_definition_invalid", f"MCP 服务 {server_name} 必须是名称到对象的映射。", "mcpServers")
                    continue
                has_command = isinstance(spec.get("command"), str) and bool(spec["command"].strip())
                has_url = isinstance(spec.get("url"), str) and bool(spec["url"].strip())
                if not (has_command or has_url):
                    add("error", "mcp_transport_missing", f"MCP 服务 {server_name} 必须提供 command 或 url。", "mcpServers")
                if "args" in spec and (not isinstance(spec["args"], list) or any(not isinstance(arg, str) for arg in spec["args"])):
                    add("error", "mcp_args_invalid", f"MCP 服务 {server_name} 的 args 必须是字符串数组。", "mcpServers")

        command_names: list[str] = []
        try:
            declared_commands = manifest.get("commands")
            if isinstance(declared_commands, dict):
                command_names = [str(name) for name in declared_commands]
            else:
                command_refs = _path_values(declared_commands) if declared_commands is not None else ["commands"]
                for ref in command_refs:
                    try:
                        command_path = _inside(root, ref)
                    except (OSError, ValueError):
                        continue  # The path diagnostic above is more useful than aborting remaining checks.
                    command_files = [command_path] if command_path.is_file() else sorted(command_path.glob("*.md")) if command_path.is_dir() else []
                    command_names.extend(item.stem for item in command_files if item.is_file() and item.suffix.lower() == ".md")
            duplicates = sorted({item for item in command_names if command_names.count(item) > 1})
            for command in duplicates:
                add("error", "duplicate_command", f"插件内部命令 {command} 重复定义。", "commands")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            add("error", "commands_invalid", f"命令定义无法读取：{type(exc).__name__}。", "commands")
        for plugin in self.discover():
            if plugin["name"] == name:
                continue
            conflicts = sorted(set(command_names) & set(plugin.get("commands", [])))
            for command in conflicts:
                add("error", "command_conflict", f"命令 /{command} 与插件 {plugin['name']} 冲突；请重命名其中一个命令。", "commands")

        mcp_names: list[str] = []
        try:
            mcp_names = sorted(self._mcp_configs(root, manifest))
            own_mcp = manifest.get("mcpServers")
            if isinstance(own_mcp, dict) and "mcpServers" not in own_mcp:
                own_mcp = own_mcp.get("mcpServers", own_mcp)
            if isinstance(own_mcp, dict):
                for server_name, spec in own_mcp.items():
                    if server_name in seen_mcp_names:
                        add("error", "mcp_duplicate_name", f"插件内 MCP 服务名 {server_name} 被重复定义。", "mcpServers")
                    seen_mcp_names.add(str(server_name))
                    if not isinstance(spec, dict):
                        add("error", "mcp_definition_invalid", f"MCP 服务 {server_name} 必须是对象。", "mcpServers")
                        continue
                    has_command = isinstance(spec.get("command"), str) and bool(spec["command"].strip())
                    has_url = isinstance(spec.get("url"), str) and bool(spec["url"].strip())
                    if not (has_command or has_url):
                        add("error", "mcp_transport_missing", f"MCP 服务 {server_name} 必须提供 command 或 url。", "mcpServers")
                    if "args" in spec and (not isinstance(spec["args"], list) or any(not isinstance(arg, str) for arg in spec["args"])):
                        add("error", "mcp_args_invalid", f"MCP 服务 {server_name} 的 args 必须是字符串数组。", "mcpServers")
            for plugin in self.discover():
                if plugin["name"] == name:
                    continue
                for server_name in sorted(set(mcp_names) & set(plugin.get("mcp_servers", []))):
                    add("error", "mcp_name_conflict", f"MCP 服务名 {server_name} 与插件 {plugin['name']} 冲突；请重命名服务。", "mcpServers")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            add("error", "mcp_invalid", f"MCP 服务声明无法读取：{type(exc).__name__}。", "mcpServers")

        try:
            from atlas.runtime.hooks import CLAUDE_HOOK_EVENTS
            for hook_path in [root / "hooks" / "hooks.json"]:
                if not hook_path.is_file():
                    continue
                try:
                    hook_data = json.loads(hook_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    add("error", "hook_parse", f"Hook 文件无法解析：{type(exc).__name__}。", str(hook_path.relative_to(root)))
                    continue
                events = hook_data.get("hooks", hook_data) if isinstance(hook_data, dict) else {}
                if isinstance(events, dict):
                    for event in events:
                        if event not in CLAUDE_HOOK_EVENTS:
                            add("error", "hook_event_unknown", f"Hook 事件 {event} 未被 Atlas 支持；请使用支持的 Claude Hook 事件名。", "hooks")
                legacy = hook_data.get("hooks") if isinstance(hook_data, dict) else None
                if isinstance(legacy, list):
                    from atlas.agent.enrichment import HOOK_POINTS
                    for hook in legacy:
                        point = hook.get("point") if isinstance(hook, dict) else None
                        if point and point not in HOOK_POINTS:
                            add("error", "hook_event_unknown", f"Atlas Hook 事件 {point} 未被支持；请使用有效 hook point。", "hooks")
            declared_hooks = manifest.get("hooks")
            hook_values = declared_hooks if isinstance(declared_hooks, list) else [declared_hooks]
            for value in hook_values:
                if isinstance(value, str):
                    try:
                        hook_path = _inside(root, value)
                        if not hook_path.is_file():
                            add("error", "hook_path_missing", f"Hook 配置文件不存在：{value}。", "hooks")
                    except (OSError, ValueError):
                        add("error", "hook_path_escape", f"Hook 配置路径无效或越出插件目录：{value}。", "hooks")
                elif isinstance(value, dict):
                    events = value.get("hooks", value)
                    if isinstance(events, dict):
                        for event in events:
                            if event not in CLAUDE_HOOK_EVENTS:
                                add("error", "hook_event_unknown", f"Hook 事件 {event} 未被 Atlas 支持。", "hooks")
        except ImportError:
            add("warning", "hook_validator_unavailable", "Hook 事件校验器不可用。", "hooks")

        errors = sum(item["severity"] == "error" for item in diagnostics)
        warnings = sum(item["severity"] == "warning" for item in diagnostics)
        return {"valid": errors == 0, "source": str(root), "plugin": {"name": name, "version": version,
                "commands": sorted(set(command_names)), "mcp_servers": mcp_names,
                "compatibility": compatibility}, "diagnostics": diagnostics,
                "summary": {"errors": errors, "warnings": warnings},
                "policy": {"status": "not_configured", "diagnostics": [],
                           "message": "组织策略适配器尚未配置；当前无组织策略跳过项。"}}

    def validate_source(
        self, source: str | Path, *, ref: str | None = None, subdir: str | None = None,
        source_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate local sources directly and inspect Git sources in a temporary checkout."""
        path = Path(source).expanduser()
        if path.exists():
            return self.validate(path, source_record=source_record)
        url = str(source)
        if not url.startswith(("https://", "http://", "ssh://", "git@")):
            if "/" in url and ":" not in url:
                url = self._github_url(url)
            else:
                return self.validate(path, source_record=source_record)
        with tempfile.TemporaryDirectory(prefix="atlas-plugin-validate-") as directory:
            checkout = Path(directory) / "source"
            try:
                self._git_clone(url, checkout, ref)
            except subprocess.CalledProcessError as exc:
                return {"valid": False, "source": url, "plugin": None,
                        "diagnostics": [{"severity": "error", "code": "source_unavailable",
                                         "message": f"无法读取插件来源：{(exc.stderr or exc.stdout or 'git clone failed')[:500]}", "path": "source"}],
                        "summary": {"errors": 1, "warnings": 0},
                        "policy": {"status": "not_configured", "diagnostics": [],
                                   "message": "组织策略适配器尚未配置；当前无组织策略跳过项。"}}
            selected = checkout / subdir if subdir else checkout
            root = self._plugin_root(selected)
            result = self.validate(root or checkout, source_record=source_record)
            return {**result, "source": url}

    def validate_marketplace_plugin(self, marketplace: str, plugin_name: str) -> dict[str, Any]:
        record = self._state.get("marketplaces", {}).get(marketplace)
        if not isinstance(record, dict):
            raise KeyError(marketplace)
        entry = next((item for item in self.list_marketplace_plugins(marketplace) if item.get("name") == plugin_name), None)
        if entry is None:
            raise KeyError(plugin_name)
        local, url, ref, subdir = self._resolve_plugin_source(record, entry)
        source_record = {"entry": entry, "plugin_name": plugin_name}
        if local is not None:
            return self.validate(local, source_record=source_record)
        if url is None:
            raise ValueError("unsupported plugin source")
        return self.validate_source(url, ref=ref, subdir=subdir, source_record=source_record)

    @staticmethod
    def _component_paths(
        root: Path, manifest: dict[str, Any], field: str, default: Path,
        *, directories: bool = False, files: bool = False,
    ) -> list[Path]:
        declared = manifest.get(field)
        values = ([default, *_path_values(declared)] if field == "skills" and declared is not None
                  else _path_values(declared) if declared is not None else [default])
        paths: list[Path] = []
        for value in values:
            path = _inside(root, value)
            if directories and path.is_dir():
                if (path / "SKILL.md").is_file():
                    paths.append(path)
                else:
                    paths.extend(sorted(item for item in path.iterdir() if item.is_dir() and (item / "SKILL.md").is_file()))
            elif files:
                if path.is_file() and path.suffix.lower() == ".md":
                    paths.append(path)
                elif path.is_dir():
                    paths.extend(sorted(item for item in path.glob("*.md") if item.is_file()))
        unique: list[Path] = []
        for path in paths:  # a declared skills dir equal to the default must not register twice
            if path not in unique:
                unique.append(path)
        return unique

    @staticmethod
    def _commands(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        declared = manifest.get("commands")
        if declared is None:
            paths = sorted((root / "commands").glob("*.md")) if (root / "commands").is_dir() else []
            return [{"name": path.stem, "path": str(path), "content": None, "metadata": {}} for path in paths]
        result: list[dict[str, Any]] = []
        for value in _path_values(declared):
            path = _inside(root, value)
            paths = [path] if path.is_file() else sorted(path.glob("*.md")) if path.is_dir() else []
            result.extend({"name": item.stem, "path": str(item), "content": None, "metadata": {}} for item in paths if item.is_file() and item.suffix.lower() == ".md")
        if isinstance(declared, dict):
            for name, value in declared.items():
                if not isinstance(value, dict):
                    continue
                content = value.get("content")
                source = value.get("source")
                path = _inside(root, source) if isinstance(source, str) else None
                result.append({"name": str(name), "path": str(path) if path else None, "content": content if isinstance(content, str) else None, "metadata": value})
        return result

    @staticmethod
    def _legacy_hook_specs(root: Path) -> list[dict[str, Any]]:
        data = _read_json(root / "hooks" / "hooks.json")
        hooks = data.get("hooks")
        return [item for item in hooks if isinstance(item, dict)] if isinstance(hooks, list) else []

    @staticmethod
    def _claude_hook_specs(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        from atlas.runtime.hooks import parse_claude_hooks

        configs: list[dict[str, Any]] = []
        seen_paths: set[Path] = set()
        hook_file = root / "hooks" / "hooks.json"
        if hook_file.is_file():
            seen_paths.add(hook_file.resolve())
            configs.append(_read_json(hook_file))
        declared = manifest.get("hooks")
        values = declared if isinstance(declared, list) else [declared]
        for value in values:
            if isinstance(value, dict):
                configs.append(value)
            elif isinstance(value, str):
                path = _inside(root, value)
                if path.is_file() and path.resolve() not in seen_paths:
                    seen_paths.add(path.resolve())
                    configs.append(_read_json(path))
        return [hook for config in configs for hook in parse_claude_hooks(config, source=str(root))]

    @staticmethod
    def _codex_hook_specs(root: Path) -> list[dict[str, Any]]:
        """Translate the supported Codex ``.codex/hooks.json`` subset.

        Atlas exposes equivalent lifecycle points through ``HookBus``. Events
        without an equivalent are ignored rather than attached to a misleading
        hook point.
        """
        event_points = {
            "UserPromptSubmit": "before_model",
            "PreToolUse": "before_tool",
            "PostToolUse": "after_tool",
            "PreCompact": "before_compact",
            "PostCompact": "after_compact",
            "Stop": "agent_stop",
            "SubagentStart": "subagent_start",
            "SubagentStop": "subagent_end",
        }
        data = _read_json(root / ".codex" / "hooks.json")
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return []
        specs: list[dict[str, Any]] = []
        for event, point in event_points.items():
            groups = hooks.get(event)
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    continue
                matcher = group.get("matcher")
                matcher = matcher.strip() if isinstance(matcher, str) else ""
                for hook in group["hooks"]:
                    if not isinstance(hook, dict) or hook.get("type") != "command":
                        continue
                    command = hook.get("command")
                    if not isinstance(command, str) or not command.strip():
                        continue
                    expanded = command.replace("${CLAUDE_PLUGIN_ROOT}", root.resolve().as_posix())
                    try:
                        argv = shlex.split(expanded, posix=True)
                    except ValueError:
                        continue
                    if argv:
                        specs.append({"point": point, "command": argv, "matcher": matcher})
        return specs

    @staticmethod
    def _mcp_configs(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result = _read_json(root / ".mcp.json").get("mcpServers", {})
        result = dict(result) if isinstance(result, dict) else {}
        declared = manifest.get("mcpServers")
        values = declared if isinstance(declared, list) else [declared]
        for value in values:
            if isinstance(value, dict):
                result.update(value.get("mcpServers", value))
            elif isinstance(value, str):
                path = _inside(root, value)
                servers = _read_json(path).get("mcpServers", {}) if path.is_file() else {}
                if isinstance(servers, dict):
                    result.update(servers)
        return {
            str(name): _expand_root(spec, root)
            for name, spec in result.items() if isinstance(spec, dict)
        }

    def _source_for_root(self, root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        sources = self._state.get("sources", {})
        if not isinstance(sources, dict):
            return {}
        for key in (root.name, str(manifest.get("name") or root.name)):
            source = sources.get(key)
            if isinstance(source, dict):
                return source
        return {}

    def _effective_manifest_for_root(self, root: Path) -> dict[str, Any]:
        _, base_manifest = _manifest(root)
        return self._effective_manifest(root, base_manifest, self._source_for_root(root, base_manifest))

    @staticmethod
    def _effective_manifest(root: Path, manifest: dict[str, Any], source: Any) -> dict[str, Any]:
        result = dict(manifest)
        if not isinstance(source, dict):
            return result
        entry = source.get("entry")
        if isinstance(entry, dict):
            for field in ("displayName", "description", "author", "homepage", "repository", "license", "keywords",
                          "peerDependencies", "tools", "permissions", "outputStyles", "lspServers"):
                if field in entry:
                    result[field] = entry[field]
            if entry.get("strict") is False:
                for field in ("skills", "commands", "agents", "hooks", "mcpServers"):
                    if field in entry:
                        result[field] = entry[field]
        result["name"] = source.get("plugin_name", result.get("name") or root.name)
        return result

    def enabled_contributions(self) -> list[dict[str, Any]]:
        """Return source paths and parsed hooks for the shared Atlas registries."""
        output: list[dict[str, Any]] = []
        for plugin in self.discover():
            if not plugin["enabled"]:
                continue
            root = Path(plugin["path"])
            _, base_manifest = _manifest(root)
            source = self._source_for_root(root, base_manifest)
            manifest = self._effective_manifest(root, base_manifest, source)
            try:
                self._require_compatible_manifest(manifest)
            except ValueError:
                continue
            hooks = self._claude_hook_specs(root, manifest)
            for hook in hooks:
                hook["plugin_root"] = str(root)
            command_sources = []
            declared_commands = manifest.get("commands")
            command_values = _path_values(declared_commands) if declared_commands is not None else ["commands"]
            if isinstance(declared_commands, dict):
                command_values = ["commands"]
            for value in command_values:
                path = Path(value)
                path = path if path.is_absolute() else root / path
                if path.is_dir():
                    command_sources.append(str(path))
                elif path.is_file() and path.suffix.lower() == ".md":
                    command_sources.append(str(path.parent))
            output.append({
                "id": plugin["name"], "name": plugin["name"], "root": str(root),
                "version": plugin["version"], "description": plugin["description"],
                "skills": [str(path) for path in self._component_paths(root, manifest, "skills", root / "skills", directories=True)],
                "commands": self._commands(root, manifest),
                "command_sources": sorted(set(command_sources)),
                "agents": [str(path) for path in self._component_paths(root, manifest, "agents", root / "agents", files=True)],
                "hooks": hooks,
                "mcp_servers": self._mcp_configs(root, manifest),
            })
        return output

    def _installed_base(self) -> Path:
        return self._dirs[-1] if self._dirs else Path("data") / "plugins"

    @staticmethod
    def _rmtree(path: Path) -> None:
        """rmtree that clears git's read-only object bits (required on Windows)."""
        def _force(func, item, _exc):
            os.chmod(item, stat.S_IWRITE)
            func(item)

        # ``onexc`` replaced ``onerror`` in 3.12; Atlas runs on 3.11 (see the
        # requires-python floor in pyproject.toml), where passing it raises
        # TypeError and an upgrade can never remove the old install.
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_force)
        else:
            shutil.rmtree(path, onerror=_force)

    @staticmethod
    def _copy_replace(source: Path, target: Path, *, previous: Path | None = None) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        incoming = target.with_name(target.name + ".incoming")
        if incoming.exists():
            PluginRuntime._rmtree(incoming)
        # Installed copies are deploy snapshots; history stays in the checkout.
        shutil.copytree(source, incoming, ignore=shutil.ignore_patterns(".git"))
        # Lift the existing patch layer out of the directory that is about to be
        # deleted. Without this an upgrade silently deletes every local edit —
        # the shipped file is replaced, so ``reload`` cannot recover it either.
        soup = None
        previous_root = previous if previous is not None and previous.exists() else target
        if previous_root.exists():
            carried = patch_layer.carry_over(previous_root, incoming)
            if carried["had_patches"]:
                soup = carried
        if target.exists():
            PluginRuntime._rmtree(target)
        incoming.replace(target)
        if soup is not None:
            # New files have landed; copy the patches back over them.
            reapplied = patch_layer.reapply(target)
            log.info(
                "plugin.patches_carried",
                path=str(target), carried=soup["carried"], applied=reapplied["count"],
            )

    @staticmethod
    def _run_git_with_retry(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        """Retry transient remote Git operations twice without echoing credentialed URLs."""
        # Git for Windows parses file:///C:/... as /C:/... when launched from a
        # Git Bash process that exports MSYS_NO_PATHCONV=1. That switch is for
        # MSYS argument rewriting, not for native git.exe; inheriting it breaks
        # local plugin sources while ordinary path arguments still appear valid.
        git_env = os.environ.copy()
        git_env.pop("MSYS_NO_PATHCONV", None)
        for attempt in range(len(_GIT_RETRY_DELAYS) + 1):
            try:
                return subprocess.run(args, check=True, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=timeout,
                                      env=git_env)
            except (OSError, subprocess.SubprocessError) as exc:
                if attempt == len(_GIT_RETRY_DELAYS):
                    raise ValueError(
                        f"Git 来源访问失败（已重试 2 次，{type(exc).__name__}）。请检查网络、代理或仓库权限。"
                    ) from exc
                time.sleep(_GIT_RETRY_DELAYS[attempt])
        raise AssertionError("unreachable")

    @staticmethod
    def _git_clone(url: str, target: Path, ref: str | None = None) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        args = ["git", "clone", "--depth", "1"]
        if ref:
            args.extend(["--branch", ref])
        args.extend([url, str(target)])
        PluginRuntime._run_git_with_retry(args, timeout=180)

    def _mutation_name_for_source(self, source: str | Path) -> str:
        source_root = self._plugin_root(Path(source))
        if source_root is None:
            raise ValueError(f"no plugin.json or plugin components found under {source}")
        manifest = self._effective_manifest_for_root(source_root)
        return str(manifest.get("name") or source_root.name)

    @_serializes_plugin_mutation(lambda self, source: self._mutation_name_for_source(source))
    def install_local(self, source: str | Path) -> dict[str, Any]:
        source_root = self._plugin_root(Path(source))
        if source_root is None:
            raise ValueError(f"no plugin.json or plugin components found under {source}")
        manifest = self._effective_manifest_for_root(source_root)
        self._require_compatible_manifest(manifest)
        name = str(manifest.get("name") or source_root.name)
        # Installed layout convention: keep the source directory name; the
        # manifest name is only the plugin identity in state/discovery.
        target = self._installed_base() / source_root.name
        self._copy_replace(source_root, target)
        self._state.setdefault("sources", {})[name] = {"source": "local", "path": str(Path(source_root).resolve())}
        self._save_state()
        return {"name": name, "path": str(target)}

    def add_marketplace(self, source: str | Path, *, name: str | None = None, ref: str | None = None) -> dict[str, Any]:
        source_path = Path(source).expanduser()
        slug = name or source_path.name.removesuffix(".git") or "marketplace"
        target = self._installed_base() / ".marketplaces" / slug
        if source_path.exists():
            root = self._marketplace_root(source_path)
            if root is None:
                raise ValueError(f"no marketplace.json found under {source}")
            record = {"type": "local", "source": str(root.resolve()), "path": str(root.resolve())}
        else:
            if target.exists():
                PluginRuntime._rmtree(target)
            self._git_clone(str(source), target, ref)
            root = self._marketplace_root(target)
            if root is None:
                raise ValueError(f"no marketplace.json found in {source}")
            record = {"type": "git", "source": str(source), "path": str(root.resolve()), "ref": ref}
        catalog = _read_json(root / next(item for item in MARKETPLACE_NAMES if (root / item).is_file()))
        market_name = str(name or catalog.get("name") or slug)
        self._state.setdefault("marketplaces", {})[market_name] = record | {"name": market_name}
        self._save_state()
        return {"name": market_name, "path": str(root), "plugins": len(catalog.get("plugins", []))}

    def list_marketplaces(self) -> list[dict[str, Any]]:
        return [dict(record) for _name, record in sorted(self._state.get("marketplaces", {}).items())]

    @staticmethod
    def _marketplace_root(path: Path) -> Path | None:
        if any((path / item).is_file() for item in MARKETPLACE_NAMES):
            return path
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_dir() and any((child / item).is_file() for item in MARKETPLACE_NAMES):
                    return child
        return None

    def list_marketplace_plugins(self, marketplace: str) -> list[dict[str, Any]]:
        record = self._state.get("marketplaces", {}).get(marketplace)
        if not isinstance(record, dict):
            raise KeyError(marketplace)
        root = Path(record["path"])
        manifest_file = next((root / item for item in MARKETPLACE_NAMES if (root / item).is_file()), None)
        catalog = _read_json(manifest_file) if manifest_file else {}
        entries = catalog.get("plugins", [])
        return [dict(item, marketplace=marketplace) for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []

    @staticmethod
    def _github_url(repo: str) -> str:
        return f"https://github.com/{repo.removesuffix('.git')}.git"

    def _resolve_plugin_source(self, record: dict[str, Any], entry: dict[str, Any]) -> tuple[Path | None, str | None, str | None, str | None]:
        market_root = Path(record["path"])
        source = entry.get("source")
        if isinstance(source, str):
            path = market_root / source
            return (path if path.is_dir() else None, None, None, str(path))
        if not isinstance(source, dict):
            raise ValueError("unsupported plugin source")
        kind = source.get("source")
        ref = source.get("ref")
        if kind == "github":
            url = self._github_url(str(source["repo"]))
            return None, url, str(ref) if ref else None, None
        if kind == "url":
            return None, str(source["url"]), str(ref) if ref else None, None
        if kind == "git-subdir":
            return None, str(source["url"]), str(ref) if ref else None, str(source["path"])
        raise ValueError(f"unsupported plugin source type: {kind}")

    @_serializes_plugin_mutation(lambda self, marketplace, plugin_name: plugin_name)
    def install_marketplace_plugin(self, marketplace: str, plugin_name: str) -> dict[str, Any]:
        record = self._state.get("marketplaces", {}).get(marketplace)
        if not isinstance(record, dict):
            raise KeyError(marketplace)
        entry = next((item for item in self.list_marketplace_plugins(marketplace) if item.get("name") == plugin_name), None)
        if entry is None:
            raise KeyError(plugin_name)
        local, url, ref, subdir = self._resolve_plugin_source(record, entry)
        target = self._installed_base() / plugin_name
        source_record: dict[str, Any] = {
            "source": "marketplace", "marketplace": marketplace,
            "plugin_source": entry.get("source"), "entry": entry,
            "plugin_name": plugin_name,
        }
        if local is not None:
            if self._plugin_root(local) is None:
                raise ValueError(f"plugin path not found: {local}")
            plugin_root = self._plugin_root(local)
            _, manifest = _manifest(plugin_root)
            manifest = self._effective_manifest(plugin_root, manifest, source_record)
            self._require_compatible_manifest(manifest)
            self._copy_replace(plugin_root, target)
        else:
            clone = self._installed_base() / ".sources" / plugin_name
            if clone.exists():
                PluginRuntime._rmtree(clone)
            self._git_clone(str(url), clone, ref)
            plugin_root = clone / subdir if subdir else clone
            plugin_root = self._plugin_root(plugin_root)
            if plugin_root is None:
                raise ValueError(f"plugin manifest/components not found in {url}")
            _, manifest = _manifest(plugin_root)
            manifest = self._effective_manifest(plugin_root, manifest, source_record)
            self._require_compatible_manifest(manifest)
            self._copy_replace(plugin_root, target)
            source_record["checkout"] = str(clone)
            source_record["subdir"] = subdir
            source_record["ref"] = ref
        source_record.update({"plugin_name": plugin_name, "entry": entry})
        self._state.setdefault("sources", {})[plugin_name] = source_record
        self._enabled.setdefault(plugin_name, entry.get("defaultEnabled", True) is not False)
        self._save_state()
        return {"name": plugin_name, "path": str(target), "marketplace": marketplace}

    @_serializes_plugin_mutation(lambda self, url, *, name=None, ref=None, subdir=None:
                                 _plugin_name(name or Path(url.rstrip("/")).name.removesuffix(".git")))
    def install_git(self, url: str, *, name: str | None = None, ref: str | None = None, subdir: str | None = None) -> dict[str, Any]:
        plugin_name = _plugin_name(name or Path(url.rstrip("/")).name.removesuffix(".git"))
        clone = self._installed_base() / ".sources" / plugin_name
        if clone.exists():
            PluginRuntime._rmtree(clone)
        self._git_clone(url, clone, ref)
        root = self._plugin_root(clone / subdir if subdir else clone)
        if root is None:
            raise ValueError(f"plugin manifest/components not found in {url}")
        _, manifest = _manifest(root)
        self._require_compatible_manifest(manifest)
        target = self._installed_base() / plugin_name
        self._copy_replace(root, target)
        self._state.setdefault("sources", {})[plugin_name] = {"source": "git", "plugin_name": plugin_name, "url": url, "ref": ref, "subdir": subdir, "checkout": str(clone)}
        self._save_state()
        return {"name": plugin_name, "path": str(target)}

    def install(self, source: str | Path, *, name: str | None = None, ref: str | None = None) -> dict[str, Any]:
        path = Path(source).expanduser()
        if path.exists():
            if self._marketplace_root(path):
                return self.add_marketplace(path, name=name, ref=ref)
            return self.install_local(path)
        if str(source).startswith(("https://", "http://", "ssh://", "git@")):
            return self.install_git(str(source), name=name, ref=ref)
        if "/" in str(source) and ":" not in str(source):
            return self.install_git(self._github_url(str(source)), name=name, ref=ref)
        raise ValueError(f"unsupported plugin source: {source}")

    @_serializes_plugin_mutation(lambda self, name, enabled: name)
    async def set_enabled(self, name: str, enabled: bool) -> bool:
        """Record the toggle and, when disabling, actually withdraw the plugin.

        Popping ``_loaded`` only forgets the Python-side record. The capabilities
        and hook handlers the plugin registered live in shared registries owned by
        the agent, so without this the plugin keeps working after it has been
        switched off — the exact opposite of what the switch promises. The
        registries are reached through the wiring captured by the last
        ``load_all``, which is the only handle this object has on them.
        """
        if enabled:
            plugin = next((item for item in self.discover() if item["name"] == name), None)
            if plugin is None:
                raise ValueError(f"plugin not found: {name}")
            manifest = self._effective_manifest_for_root(Path(plugin["path"]))
            self._require_compatible_manifest(manifest)
        self._enabled[name] = enabled
        self._save_state()
        if not enabled:
            await self._forget_plugin(
                name,
                capabilities=self._wiring.get("capabilities"),
                hook_bus=self._wiring.get("hook_bus"),
            )
            self._loaded.pop(name, None)
        return True

    # --- patch layer -------------------------------------------------------
    #
    # These four are the whole public surface of ``patch_layer`` at runtime
    # level. They exist because an installed plugin is a deploy snapshot that
    # gets replaced wholesale on upgrade, so the only durable place for a local
    # tweak is a patch directory that ``_copy_replace`` knows to carry over.

    def _root_for(self, name: str) -> Path:
        """Resolve a plugin name to its root, or raise ``KeyError``."""
        plugin = next((item for item in self.discover() if item["name"] == name), None)
        if plugin is None:
            raise KeyError(name)
        return Path(plugin["path"])

    def list_patches(self, name: str) -> dict[str, Any]:
        """Every local override installed on this plugin."""
        return patch_layer.list_patches(self._root_for(name))

    def patch_file(self, name: str, relative: str, content: str, *, note: str = "") -> dict[str, Any]:
        """Store a local edit as a patch, leaving the shipped file recoverable."""
        return patch_layer.write(self._root_for(name), relative, content, note=note)

    def revert_patch(self, name: str, relative: str | None = None) -> dict[str, Any]:
        """Drop one override, or all of them when ``relative`` is omitted."""
        root = self._root_for(name)
        if relative is None:
            return patch_layer.revert_all(root)
        return patch_layer.revert(root, relative)

    def effective_text(self, name: str, relative: str) -> str:
        """Read a plugin file with any patch applied."""
        return patch_layer.effective_text(self._root_for(name), relative)

    @_serializes_plugin_mutation(lambda self, name: name)
    def uninstall(self, name: str) -> bool:
        plugin = next((item for item in self.discover() if item["name"] == name), None)
        if plugin is None:
            return False
        root = Path(plugin["path"])
        if root.parent.resolve() == self._installed_base().resolve():
            PluginRuntime._rmtree(root)
        source = self._state.get("sources", {}).pop(name, {})
        checkout = source.get("checkout") if isinstance(source, dict) else None
        if checkout and Path(checkout).exists():
            PluginRuntime._rmtree(Path(checkout))
        self._enabled.pop(name, None)
        self._loaded.pop(name, None)
        self._save_state()
        return True

    @staticmethod
    def _git_repo(path: Path) -> Path | None:
        repo = Path(path)
        while repo != repo.parent:
            if (repo / ".git").exists():
                return repo
            repo = repo.parent
        return None

    def _git_update_available(self, path: Path) -> bool:
        """True when the checkout's upstream advanced past local HEAD. Failures mean no update."""
        repo = self._git_repo(path)
        if repo is None:
            return False
        try:
            self._run_git_with_retry(["git", "-C", str(repo), "fetch", "--quiet"])
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
            upstream = subprocess.run(["git", "-C", str(repo), "rev-parse", "@{upstream}"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
            for source in self._state.get("sources", {}).values():
                if isinstance(source, dict) and source.get("checkout") and Path(source["checkout"]) == path:
                    source.pop("update_error", None)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            source_error = (f"Git 来源更新检查失败（已重试 2 次）：{exc}" if isinstance(exc, ValueError)
                            else "Git 来源更新检查失败：本地仓库状态无法读取。")
            for source in self._state.get("sources", {}).values():
                if isinstance(source, dict) and source.get("checkout") and Path(source["checkout"]) == path:
                    source["update_error"] = source_error
            return False
        return bool(head) and bool(upstream) and head != upstream

    def check_updates(self, name: str | None = None) -> dict[str, bool]:
        """Refresh ``update_available`` in state for git/marketplace-sourced plugins.

        Local-directory plugins have no remote to compare and are skipped.
        """
        results: dict[str, bool] = {}
        sources = self._state.get("sources", {})
        for plugin_name, source in sources.items():
            if not isinstance(source, dict):
                continue
            if name is not None and plugin_name != name:
                continue
            if source.get("source") == "git":
                checkout = source.get("checkout")
                available = self._git_update_available(Path(checkout)) if checkout else False
            elif source.get("source") == "marketplace":
                record = self._state.get("marketplaces", {}).get(source.get("marketplace"))
                checkout = source.get("checkout") or (
                    record.get("path") if isinstance(record, dict) and record.get("type") == "git" else None
                )
                available = self._git_update_available(Path(checkout)) if checkout else False
            else:
                continue
            source["update_available"] = available
            results[plugin_name] = available
        self._save_state()
        return results

    def update_marketplace(self, name: str) -> dict[str, Any]:
        record = self._state.get("marketplaces", {}).get(name)
        if not isinstance(record, dict):
            raise KeyError(name)
        if record["type"] == "local":
            return {"name": name, "updated": False, "reason": "local"}
        repo = self._git_repo(Path(record["path"]))
        if repo is None:
            raise ValueError(f"marketplace checkout is not a git repository: {name}")
        self._run_git_with_retry(["git", "-C", str(repo), "pull", "--ff-only"])
        record["path"] = str(self._marketplace_root(repo) or repo)
        self._save_state()
        return {"name": name, "updated": True}

    @_serializes_plugin_mutation(lambda self, name: name)
    def update(self, name: str) -> dict[str, Any]:
        source = self._state.get("sources", {}).get(name, {})
        if source.get("source") == "local":
            path = Path(source["path"])
            result = self.install_local(path)
            self._state["sources"][name] = source
            self._save_state()
            return result
        if source.get("source") == "marketplace":
            self.update_marketplace(source["marketplace"])
            result = self.install_marketplace_plugin(source["marketplace"], name)
            self._enabled[name] = self._enabled.get(name, True)
            self._save_state()
            return result
        if source.get("source") == "git":
            checkout = Path(source["checkout"])
            self._run_git_with_retry(["git", "-C", str(checkout), "pull", "--ff-only"])
            root = self._plugin_root(checkout / source["subdir"] if source.get("subdir") else checkout)
            if root is None:
                raise ValueError(f"plugin components missing after update: {name}")
            _, manifest = _manifest(root)
            self._require_compatible_manifest(manifest)
            target = self._installed_base() / name
            self._copy_replace(root, target)
            source["update_available"] = False
            self._save_state()
            return {"name": name, "path": str(target)}
        raise ValueError(f"plugin has no update source: {name}")

    async def load_all(
        self, *, hook_bus: Any = None, mcp_client: Any = None, capabilities: Any = None,
    ) -> dict[str, Any]:
        """Load Atlas/Hermes compatibility contributions; Claude hooks go via HookStore.

        This runs on every enable/disable toggle, so it has to be idempotent.
        ``self._loaded.clear()`` alone only forgets the Python-side record: the
        capabilities and hook handlers those plugins registered in the shared
        registries stay behind. The next load then hits a duplicate-capability
        rejection (which is caught and reported per plugin, so the plugin looks
        broken) and adds a second copy of every hook closure (which is not
        caught at all, so hooks silently run twice). Clearing both registries by
        source first is what makes a toggle actually replace the previous
        generation instead of stacking on it.
        """
        report: dict[str, Any] = {
            "loaded": [], "skipped": [], "errors": {},
            "capabilities_removed": 0, "hooks_cleared": 0,
        }
        self._wiring = {
            "hook_bus": hook_bus, "mcp_client": mcp_client, "capabilities": capabilities,
        }
        for previous_name in list(self._loaded):
            removed, hooks_cleared = await self._forget_plugin(
                previous_name, capabilities=capabilities, hook_bus=hook_bus,
            )
            report["capabilities_removed"] += removed
            report["hooks_cleared"] += hooks_cleared
        self._loaded.clear()
        for plugin in self.discover():
            name = plugin["name"]
            if not plugin["enabled"]:
                report["skipped"].append({"name": name, "reason": "disabled"})
                continue
            compatibility = plugin.get("compatibility")
            if compatibility and not compatibility.get("exempted"):
                report["skipped"].append({"name": name, "reason": "incompatible peerDependencies",
                                          "compatibility": compatibility})
                continue
            try:
                self._loaded[name] = await self._load_one(
                    Path(plugin["path"]), plugin_name=name,
                    hook_bus=hook_bus, mcp_client=mcp_client, capabilities=capabilities,
                )
                report["loaded"].append(name)
            except Exception as exc:
                report["errors"][name] = str(exc)
        return report

    async def _forget_plugin(
        self, name: str, *, capabilities: Any = None, hook_bus: Any = None,
    ) -> tuple[int, int]:
        """Drop everything one plugin registered; returns ``(capabilities, hooks)``."""
        owner = f"plugin:{name}"
        loaded = self._loaded.get(name)
        disposer_stack = self._disposers.pop(name, None)
        disposer = disposer_stack.dispose if disposer_stack is not None else None
        if callable(disposer) and isinstance(loaded, dict):
            removed = len(loaded.get("skills", [])) + len(loaded.get("commands", []))
            hooks_cleared = int(loaded.get("hooks", 0) or 0)
            await disposer()
            # Keep owner cleanup as a fail-safe for contributions registered by
            # older plugin runtimes that did not provide individual disposers.
            if capabilities is not None and hasattr(capabilities, "unregister_source"):
                capabilities.unregister_source(owner)
            if hook_bus is not None and hasattr(hook_bus, "forget_owner"):
                hook_bus.forget_owner(owner)
        else:
            removed = 0
            if capabilities is not None and hasattr(capabilities, "unregister_source"):
                removed = capabilities.unregister_source(owner)
            hooks_cleared = 0
            if hook_bus is not None and hasattr(hook_bus, "forget_owner"):
                hooks_cleared = hook_bus.forget_owner(owner)
        return removed, hooks_cleared

    async def reload(
        self, name: str, *, hook_bus: Any = None, mcp_client: Any = None,
        capabilities: Any = None,
    ) -> dict[str, Any]:
        """Re-read one plugin from disk without restarting the backend.

        Why this exists: ``load_all`` clears and reloads *everything*, so a plugin
        author editing a ``SKILL.md`` had to restart the whole backend to see the
        change. Reloading one plugin is the operation they actually want.

        The three things that can leak are handled explicitly:

        * capabilities — ``register`` rejects duplicates, so the plugin's entries
          are removed **by source** before loading (a plugin can contribute fewer
          skills after an edit, so removing the known names is not enough);
        * hooks — the previous generation is cleared through
          ``HookBus.forget_owner`` (handlers are tagged with the plugin name at
          registration, because a reload creates new closure objects whose
          ``__qualname__`` is shared by every plugin);
        * MCP servers — already-connected servers are reused by ``_load_one``.

        Unchanged plugins are re-read anyway: the point is to pick up edits, and
        comparing mtimes would make "I edited it but nothing happened" possible.
        """
        hook_bus = hook_bus if hook_bus is not None else self._wiring.get("hook_bus")
        mcp_client = mcp_client if mcp_client is not None else self._wiring.get("mcp_client")
        capabilities = (
            capabilities if capabilities is not None else self._wiring.get("capabilities")
        )

        plugin = next((item for item in self.discover() if item["name"] == name), None)
        if plugin is None:
            return {"ok": False, "name": name, "error": "plugin not found"}

        compatibility = plugin.get("compatibility")
        if compatibility and not compatibility.get("exempted"):
            removed, hooks_cleared = await self._forget_plugin(
                name, capabilities=capabilities, hook_bus=hook_bus,
            )
            self._loaded.pop(name, None)
            return {
                "ok": False, "name": name,
                "error": f"Atlas peer compatibility check failed: {compatibility['peers']}",
                "capabilities_removed": removed, "hooks_cleared": hooks_cleared,
            }

        # ``_read_json`` is deliberately forgiving elsewhere (a corrupt manifest
        # must not break discovery), but during an explicit reload a file that does
        # not parse is exactly the case the user needs told about: loading it would
        # produce an empty plugin and look like the edit "worked".
        manifest_path, _ = _manifest(Path(plugin["path"]))
        if manifest_path is not None:
            try:
                json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                return {
                    "ok": False,
                    "name": name,
                    "error": f"清单无法解析（{manifest_path.name}）：{exc}",
                }

        removed, hooks_cleared = await self._forget_plugin(
            name, capabilities=capabilities, hook_bus=hook_bus,
        )

        previous = self._loaded.pop(name, None)
        try:
            loaded = await self._load_one(
                Path(plugin["path"]), plugin_name=name, hook_bus=hook_bus,
                mcp_client=mcp_client, capabilities=capabilities,
            )
        except Exception as exc:  # noqa: BLE001 - a bad edit must not kill the app
            # Restore the previous entry so a broken edit leaves the runtime in the
            # state it was in, rather than dropping the plugin entirely.
            if previous is not None:
                self._loaded[name] = previous
            return {"ok": False, "name": name, "error": f"{type(exc).__name__}: {exc}"}

        self._loaded[name] = loaded
        return {
            "ok": True,
            "name": name,
            "capabilities_removed": removed,
            "hooks_cleared": hooks_cleared,
            "loaded": loaded,
        }

    async def _load_one(
        self, root: Path, *, plugin_name: str, hook_bus: Any,
        mcp_client: Any, capabilities: Any,
    ) -> dict[str, Any]:
        _, manifest = _manifest(root)
        manifest = self._effective_manifest(root, manifest, self._source_for_root(root, manifest))
        self._require_compatible_manifest(manifest)
        disposers = _DisposerStack()
        loaded: dict[str, Any] = {
            "skills": [], "commands": [], "hooks": 0, "mcp": [],
        }
        if capabilities is not None:
            for skill in self._component_paths(root, manifest, "skills", root / "skills", directories=True):
                content = (skill / "SKILL.md").read_text(encoding="utf-8", errors="replace")
                loaded["skills"].append(skill.name)
                capability_name = f"plugin.{plugin_name}.skill.{skill.name}"
                capabilities.register(
                    capability_name, description=f"Skill from plugin {plugin_name}.",
                    handler=lambda _inputs, _content=content: {"content": _content}, source=f"plugin:{plugin_name}",
                )
                disposers.add(lambda _name=capability_name: capabilities.unregister(_name))
            for command in self._commands(root, manifest):
                loaded["commands"].append(command["name"])
                content = command["content"]
                if content is None and command["path"]:
                    content = Path(command["path"]).read_text(encoding="utf-8", errors="replace")
                capability_name = f"plugin.{plugin_name}.command.{command['name']}"
                capabilities.register(
                    capability_name, description=str(command["metadata"].get("description") or f"Command prompt from plugin {plugin_name}."),
                    handler=lambda _inputs, _content=content: {"prompt": _content}, source=f"plugin:{plugin_name}",
                )
                disposers.add(lambda _name=capability_name: capabilities.unregister(_name))
        for spec in [*self._legacy_hook_specs(root), *self._codex_hook_specs(root)]:
            point = str(spec.get("point", ""))
            command = spec.get("command")
            if point not in HOOK_POINTS or not isinstance(command, list) or not command:
                continue
            argv = [str(arg) for arg in command]
            matcher = str(spec.get("matcher") or "").strip()

            def _handler(_argv: list[str] = argv, _matcher: str = matcher,
                         **payload: Any) -> None:
                if _matcher:
                    tool_name = payload.get("tool_name", payload.get("toolName", payload.get("tool")))
                    if tool_name != _matcher:
                        return
                subprocess.run(_argv, input=json.dumps(payload, ensure_ascii=False, default=str), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)

            # Tagged so ``reload`` can clear exactly this plugin's previous
            # generation: the closure is a new object each load, and its
            # ``__qualname__`` is identical across plugins.
            _handler.__atlas_owner__ = f"plugin:{plugin_name}"
            if hook_bus is not None:
                hook_bus.register(point, _handler)
                disposers.add(lambda _point=point, _handler=_handler: hook_bus.unregister(_point, _handler))
            loaded["hooks"] += 1
        if mcp_client is not None:
            from atlas.tools.mcp_client import MCPServerConfig

            for server_name, server in self._mcp_configs(root, manifest).items():
                if server_name in mcp_client.get_server_names():
                    loaded["mcp"].append(server_name)
                    continue
                transport = str(server.get("transport", server.get("type", "stdio")))
                config = MCPServerConfig(
                    name=server_name, transport=transport,
                    command=server.get("command"), args=[str(arg) for arg in server.get("args", [])],
                    env={str(k): str(v) for k, v in (server.get("env") or {}).items()},
                    cwd=str(server.get("cwd") or root), url=server.get("url"), enabled=True,
                )
                await mcp_client._connect_server(config)
                loaded["mcp"].append(server_name)
                async def _disconnect(_name: str = server_name) -> None:
                    await mcp_client.disconnect_server(_name)
                disposers.add(_disconnect)
        loaded["disposer_count"] = len(disposers)
        self._disposers[plugin_name] = disposers
        return loaded
