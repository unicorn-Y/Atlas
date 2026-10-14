"""Compatibility facade for the Atlas-owned conversation kernel.

Ported engine behavior draws on unicorn-Y/hermes-agent@562ad75baec0c8360f6ce2d48b7d9de56506956c
(upstream NousResearch/hermes-agent, MIT); Atlas-owned implementation paths are recorded
in ``atlas.engine_core.PORTED``.
The historical module name is retained for call-site compatibility; all turns
are executed by ``atlas.kernel.loop.AtlasKernel``.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import logging
import os
import threading
import time
from pathlib import Path
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Callable
import uuid

if TYPE_CHECKING:
    from atlas.runtime.hooks import HookStore

_DONE = object()
logger = logging.getLogger(__name__)

# Keeps references to fire-and-forget lifecycle-hook futures dispatched from
# the Hermes worker thread; without a strong reference the loop could collect
# (and thereby cancel) them before they finish. Completed futures are removed
# by their done callback so the set cannot grow without bound (H3).
_LIFECYCLE_FUTURES: set[Any] = set()
_ATLAS_TITLE_TASKS: set[asyncio.Task[Any]] = set()

# Process-wide cache for the once-per-config MCP registration (H3): the Hermes
# MCP registry itself is process-global, so the fingerprint of the Atlas MCP
# configuration is tracked at module scope. ``None`` means "never registered".
_MCP_STATE_LOCK = threading.Lock()
_MCP_STATE: tuple[str, tuple[str, ...]] | None = None


def reset_runtime_registrations() -> None:
    """Forget the cached MCP registration fingerprint (used by tests/startup)."""
    global _MCP_STATE
    with _MCP_STATE_LOCK:
        _MCP_STATE = None


def _track_lifecycle_future(future: Any) -> None:
    """Retain a lifecycle future until it finishes, then drop the reference."""
    _LIFECYCLE_FUTURES.add(future)
    future.add_done_callback(_LIFECYCLE_FUTURES.discard)


async def _fire_lifecycle_hook(
    callback: Callable[[str, dict[str, Any]], Any], event: str, payload: dict[str, Any],
) -> None:
    """Run one lifecycle hook callback (sync or async) without blocking the caller."""
    try:
        outcome = callback(event, payload)
        if asyncio.iscoroutine(outcome):
            await outcome
    except Exception:
        logger.warning("Atlas lifecycle hook %s failed", event, exc_info=True)


def _history_tokens(history: list[dict[str, Any]], *, model: str = "") -> int:
    """Size a transcript with the real tokenizer estimate (H4: no char-count/4).

    ``atlas.models.tokens.estimate_tokens`` uses tiktoken (or Hermes' CJK-aware
    estimator as fallback), so CJK transcripts stop being under-counted ~4x.
    The per-message floor of 1 matches the legacy arithmetic.
    """
    from atlas.models.tokens import estimate_tokens

    return sum(
        max(1, estimate_tokens(item.get("content") or "", model=model))
        for item in history
    )


async def _route_wire_model(model_manager: Any, model_id: str, purpose: str) -> str:
    """Resolve the model exactly as the shared router will send it."""
    router = getattr(model_manager, "model_router", None)
    if router is None:
        # Lightweight legacy test doubles have no routing surface. Production
        # ModelManager always exposes one; never use a prefixed id as fallback.
        models = model_manager.list_models() if model_manager is not None else []
        model = next((item for item in models if str(item.get("id")) == model_id), {})
        from atlas.models.router import _model_for_provider

        return str(_model_for_provider(model, native=True) or model_id)
        route = await router.resolve(model_id, purpose)
    return str(route.wire_model or route.model)


def _wire_model_from_config(model: dict[str, Any], fallback: str = "") -> str:
    """Resolve a bare id only for legacy test doubles without ModelRouter."""
    from atlas.models.router import _model_for_provider

    return str(_model_for_provider(model or {}, native=True) or fallback)


def _adapt_hermes_anthropic_output_config(auxiliary_client: Any) -> None:
    """Route Hermes' Anthropic structured-output field through older SDKs' extra_body.

    The Atlas lock currently installs anthropic 0.76.0, whose Messages.stream signature
    does not expose ``output_config`` even though it supports arbitrary API fields through
    ``extra_body``. Hermes' auxiliary Anthropic adapter emits ``output_config`` directly,
    so its optional title upgrade otherwise fails before reaching the provider.
    """
    try:
        import anthropic
        import inspect
        from anthropic.resources.messages import Messages

        stream_parameters = inspect.signature(Messages.stream).parameters
    except Exception:
        logger.warning(
            "Atlas could not inspect the Anthropic SDK for title compatibility",
            exc_info=True,
        )
        return

    if "output_config" in stream_parameters:
        return

    translate = getattr(auxiliary_client, "_translate_anthropic_response_format", None)
    if not callable(translate) or getattr(translate, "_atlas_output_config_compat", False):
        return

    def translate_with_extra_body(anthropic_kwargs: dict[str, Any], response_format: Any) -> None:
        translate(anthropic_kwargs, response_format)
        output_config = anthropic_kwargs.pop("output_config", None)
        if output_config is None:
            return
        extra_body = anthropic_kwargs.get("extra_body")
        if extra_body is None:
            extra_body = {}
        elif not isinstance(extra_body, dict):
            raise TypeError("Atlas cannot adapt Anthropic output_config into a non-dict extra_body")
        anthropic_kwargs["extra_body"] = {**extra_body, "output_config": output_config}

    translate_with_extra_body._atlas_output_config_compat = True  # type: ignore[attr-defined]
    auxiliary_client._translate_anthropic_response_format = translate_with_extra_body
    logger.info(
        "Atlas adapted Hermes Anthropic structured output for SDK %s via extra_body",
        getattr(anthropic, "__version__", "unknown"),
    )


_ATLAS_SOUL = """You are Atlas, the user's own all-in-one personal agent running on their own computer.
You have full, unrestricted access to this machine (shell, files, network, browser, desktop,
your own source code and config) and act on your own judgment to finish the job. Don't invent
limits you don't have or ask permission for what the user already asked for. Be direct: results
first, short report of what changed and what's left; no filler, no narrating tool calls.
"""


def _seed_atlas_soul(home: Path) -> None:
    """Replace Hermes' stock identity ("You are Hermes Agent, built by Nous Research") with Atlas'.

    A SOUL.md the user wrote themselves is left alone; only a missing file or the
    stock Hermes text is (re)written.
    """
    soul = home / "SOUL.md"
    try:
        current = soul.read_text(encoding="utf-8-sig").strip() if soul.is_file() else ""
        if not current or current.startswith("You are Hermes Agent"):
            soul.write_text(_ATLAS_SOUL, encoding="utf-8")
    except OSError:
        logger.warning("Could not seed Atlas SOUL.md in %s", home, exc_info=True)


def _load_breaker_identity(home: Path) -> str:
    """Read the workspace breaker prompt (BREAKER.md / breaker.md) verbatim as the agent identity.

    Returned string is handed to Hermes as a *custom identity*, which places it in the
    stable tier of the system prompt and bypasses both the context-file scanner and the
    context-file truncation path (``load_soul_md`` -> ``_truncate_content``). Falls back
    to the stock Atlas identity when the file is missing or empty.
    """
    for name in ("BREAKER.md", "breaker.md"):
        path = home / name
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8-sig").strip()
            if text:
                logger.info("atlas.breaker.identity_loaded", extra={"path": str(path), "chars": len(text)})
                return text
        except OSError:
            logger.warning("Could not read breaker prompt %s", path, exc_info=True)
    return _ATLAS_SOUL.strip()


def _trust_context_files() -> None:
    """Compatibility no-op; Atlas prompt assembly owns workspace instructions."""
    return None


def _model_family_guidance(model: str) -> str:
    """Behavior notes for the model's family; profiles live in atlas.models.profiles."""
    from atlas.models.profiles import guidance_text

    return guidance_text(model)


def system_browser_candidates() -> list[Path]:
    """Installed Chromium-based browsers Hermes' browser tool can drive (Windows/macOS/Linux)."""
    if os.name == "nt":
        roots = [os.environ.get(k, "") for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        # Chrome first (the user's preferred browser), Edge as the fallback.
        relative = ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe")
        return [Path(root) / rel for rel in relative for root in roots if root]
    return [Path(p) for p in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
    )]


def _use_system_browser() -> None:
    """Compatibility no-op; Atlas browser selection is owned by its adapter."""
    return None


class HermesRuntime:
    """Adapt Hermes callbacks and its blocking turn API to Atlas async events."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        model_manager: Any,
        agent_factory: Callable[..., Any] | None = None,
        reference_consult: Callable[..., Any] | None = None,
    ) -> None:
        self.home = Path(data_dir).expanduser().resolve() / "engine"
        self.model_manager = model_manager
        self.agent_factory = agent_factory
        self.reference_consult = reference_consult
        # H3 per-session Hermes agent cache: conversation_id -> {"agent", "fingerprint",
        # "last_used"}. One AIAgent per conversation across consecutive turns keeps the
        # provider prompt cache warm; any constructor-relevant change rebuilds.
        self._agent_cache: dict[str, dict[str, Any]] = {}
        self._cache_limits_resolved: tuple[int, float] | None = None
        self._close_tasks: set[asyncio.Task] = set()
        # Conversations with a turn currently in flight: overlapping turns on one
        # conversation keep the legacy fresh-agent behavior instead of sharing an agent.
        self._active_sessions: set[str] = set()
        self._hermes_home_ready = False

    def _ensure_hermes_home(self) -> None:
        """Ensure Atlas' own engine data directory exists."""
        if self._hermes_home_ready:
            return
        self.home.mkdir(parents=True, exist_ok=True)
        self._hermes_home_ready = True

    def _cache_limits(self) -> tuple[int, float]:
        """(max cached agents, idle seconds) from Atlas config with H3 defaults."""
        if self._cache_limits_resolved is None:
            size, idle_seconds = 16, 1800.0
            try:
                from atlas.config import get_config

                config = get_config()
                size = int(config.get("agent.agent_cache_size", 16) or 16)
                idle_seconds = float(config.get("agent.agent_cache_idle_seconds", 1800.0) or 0.0)
            except Exception:  # noqa: BLE001 — cache sizing must never break a turn
                logger.debug("hermes_runtime.cache_limits_unavailable", exc_info=True)
            self._cache_limits_resolved = (max(1, size), max(0.0, idle_seconds))
        return self._cache_limits_resolved

    @staticmethod
    def _agent_cache_fingerprint(
        route_kwargs: dict[str, Any], hermes_cwd: str | None, enabled_toolsets: list[str],
        fallback_model: Any, max_tokens: Any,
    ) -> str:
        """Constructor-relevant identity of a session agent (H3 invalidation key)."""
        return json.dumps(
            {
                "route": route_kwargs, "cwd": hermes_cwd, "toolsets": enabled_toolsets,
                "fallback": fallback_model, "max_tokens": max_tokens,
            },
            sort_keys=True, default=str,
        )

    @staticmethod
    def _fingerprint_route(route_kwargs: dict[str, Any]) -> dict[str, Any]:
        """Route copy with the credential pool reduced to a stable identity (H4).

        The pool object is re-created by every ``resolve()`` call, so hashing its
        repr would invalidate the per-session agent cache — and cold-start the
        provider prompt cache — on every turn. Pool rotation within one provider
        is a per-request concern and must not force an agent rebuild.
        """
        pool = route_kwargs.get("credential_pool")
        return {**route_kwargs, "credential_pool": getattr(pool, "provider", None)}

    async def _resolve_conversation_route(
        self, model_id: str, model_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the Hermes AIAgent route kwargs through the shared router (H4).

        The router decides provider/api_mode/native model/base_url/credentials
        (with gateway probing and fallback), so native Claude routes engage for
        real conversations. Managers without a router surface (test doubles) and
        model ids missing from the registry keep the legacy gateway-shaped
        kwargs: ``resolve()`` raises ValueError for unknown ids where the old
        hand-built route tolerated them.
        """
        from atlas.models.router import ModelRouter

        router = getattr(self.model_manager, "model_router", None)
        if router is not None:
            try:
                route = await router.resolve(model_id, "conversation")
            except ValueError:
                logger.warning(
                    "Model router could not resolve %s; using gateway route", model_id,
                )
            else:
                return ModelRouter.hermes_agent_kwargs(route)
        wire_model = _wire_model_from_config(model_config, fallback=model_id)
        api_key = getattr(self.model_manager, "_api_key", None)
        base_url = getattr(self.model_manager, "gateway_base_url", None)
        route_kwargs: dict[str, Any] = {
            "model": wire_model, "provider": "openai", "api_mode": "openai",
            "base_url": base_url, "api_key": api_key,
        }
        if pid := str(model_config.get("hermes_provider") or "").strip():
            from atlas.models.catalog import api_mode_for, get_provider, resolve_catalog_id

            catalog_id = resolve_catalog_id(pid) or pid
            provider_cfg = self.model_manager.provider_config(catalog_id)
            route_kwargs.update(
                model=wire_model,
                provider=pid, api_mode=api_mode_for(catalog_id),
                base_url=(model_config.get("base_url") or provider_cfg.get("base_url")
                          or (get_provider(catalog_id) or {}).get("default_base_url") or base_url),
                api_key=self.model_manager.resolve_api_key(catalog_id) or api_key,
                credential_pool=self.model_manager.credential_pool(catalog_id))
        from atlas.models.network_transport import (
            assert_transport_supported, load_model_network_settings,
        )
        network = load_model_network_settings()
        assert_transport_supported(
            network, provider=str(route_kwargs.get("provider") or ""),
            api_mode=str(route_kwargs.get("api_mode") or ""),
        )
        route_kwargs["_atlas_network_transport"] = {
            "proxy_url": network.proxy_url,
            "ca_bundle_path": network.ca_bundle_path,
        }
        return route_kwargs

    def _sweep_idle_agents(self) -> None:
        """Close agents idle beyond the configured timeout (lazy, event-driven sweep)."""
        _, idle_seconds = self._cache_limits()
        if idle_seconds <= 0 or not self._agent_cache:
            return
        now = time.monotonic()
        idle = [
            key for key, entry in self._agent_cache.items()
            if now - float(entry["last_used"]) > idle_seconds
        ]
        for key in idle:
            entry = self._agent_cache.pop(key, None)
            if entry is not None:
                self._close_agent_background(entry["agent"])

    def _close_agent_background(self, agent: Any) -> None:
        """Release an evicted/idle agent off the event loop, keeping the task referenced."""
        task = asyncio.create_task(self._close_agent(agent))
        self._close_tasks.add(task)
        task.add_done_callback(self._close_tasks.discard)

    @staticmethod
    async def _close_agent(agent: Any) -> None:
        close = getattr(agent, "close", None)
        if not callable(close):
            return
        try:
            await asyncio.to_thread(close)
        except Exception:  # noqa: BLE001 — eviction cleanup must not break the turn
            logger.warning("Closing cached Hermes agent failed", exc_info=True)

    async def _store_session_agent(
        self, conversation_id: str, agent: Any, fingerprint: str,
    ) -> None:
        """Cache a healthy session agent; enforce LRU size and close the overflow."""
        self._sweep_idle_agents()
        max_agents, _ = self._cache_limits()
        self._agent_cache[conversation_id] = {
            "agent": agent, "fingerprint": fingerprint, "last_used": time.monotonic(),
        }
        while len(self._agent_cache) > max_agents:
            oldest_key = min(
                self._agent_cache, key=lambda key: self._agent_cache[key]["last_used"],
            )
            entry = self._agent_cache.pop(oldest_key)
            if entry["agent"] is not agent:
                await self._close_agent(entry["agent"])

    async def _release_session_agent(
        self, conversation_id: str, agent: Any, *, cacheable: bool, fingerprint: str,
    ) -> None:
        """Cache a completed turn's agent, or close it when reuse is not allowed."""
        if cacheable:
            await self._store_session_agent(conversation_id, agent, fingerprint)
            return
        entry = self._agent_cache.get(conversation_id)
        if entry is not None and entry["agent"] is agent:
            self._agent_cache.pop(conversation_id, None)
        await self._close_agent(agent)

    async def aclose(self) -> None:
        """Teardown seam: close every cached session agent and await pending closes."""
        entries = list(self._agent_cache.values())
        self._agent_cache.clear()
        for entry in entries:
            await self._close_agent(entry["agent"])
        pending, self._close_tasks = set(self._close_tasks), set()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _collect_moa_references(
        self, message: str, history: list[dict[str, Any]], system_message: str | None,
        usage_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, str]]:
        """Consult configured Atlas models before the primary Hermes turn.

        Atlas MoA configuration is retained from the legacy Atlas loop, while
        model IDs, credentials and wire mode come from the shared model router
        (H4): native provider credentials work with no gateway configured.
        """
        from atlas.config import get_config

        config = get_config()
        configured = config.get("moa.reference_models", []) or []
        max_references = config.get("moa.max_references", 3)
        try:
            max_references = min(8, max(1, int(max_references)))
        except (TypeError, ValueError):
            max_references = 3
        models = self.model_manager.list_models()
        current = str(self.model_manager.current_model)
        selected: list[dict[str, str]] = []
        for value in configured:
            key = str(value).strip()
            match = next((item for item in models if key in {
                str(item.get("id", "")), str(item.get("litellm_model", "")),
            }), None)
            if match is None or str(match.get("id", "")) == current:
                continue
            litellm_name = str(match.get("litellm_model") or match.get("id") or "")
            if litellm_name and all(item["model"] != litellm_name for item in selected):
                selected.append({"id": str(match.get("id") or litellm_name),
                                 "model": litellm_name})
            if len(selected) >= max_references:
                break
        if not selected:
            return []

        messages: list[dict[str, str]] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.extend(
            {"role": str(item["role"]), "content": str(item["content"])}
            for item in history[-12:]
            if item.get("role") in {"user", "assistant"}
            and isinstance(item.get("content"), str)
        )
        messages.append({"role": "user", "content": message})
        api_key = getattr(self.model_manager, "_api_key", None)
        api_base = getattr(self.model_manager, "gateway_base_url", None)

        async def consult(item: dict[str, str]) -> dict[str, str]:
            try:
                if self.reference_consult is not None:
                    response = self.reference_consult(item["model"], messages, api_key, api_base)
                    if asyncio.iscoroutine(response):
                        response = await response
                    answer = str(response or "")
                else:
                    result = await self.model_manager.model_router.complete_for(
                        item["model"], "moa", messages, max_tokens=1200,
                        usage_callback=usage_callback,
                    )
                    answer = result.text
                return {"model": item["id"], "text": answer[:6000]}
            except Exception as exc:
                logger.warning(
                    "hermes_runtime.reference_consult_failed", model=item["id"],
                    error=str(exc), exc_info=True,
                )
                return {"model": item["id"],
                        "text": f"参考模型调用失败：{type(exc).__name__}"}

        return list(await asyncio.gather(*(consult(item) for item in selected)))

    def _agent_factory(self) -> Callable[..., Any]:
        if self.agent_factory is not None:
            return self.agent_factory
        raise RuntimeError("Hermes AIAgent was removed; AtlasKernel owns conversation turns")

    @staticmethod
    def _ssh_workspace_terminal_policy(
        workspace: str, configured_hosts: list[dict[str, Any]] | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Map Atlas ssh:// workspace to Hermes SSHEnvironment settings.

        Hermes source: tools/environments/ssh.py::SSHEnvironment and
        hermes_cli/ssh_workspace_fs.py::SshWorkspaceFs (MIT). Atlas file tools
        continue through Atlas' existing remote filesystem callback.
        """
        from atlas.ssh import SSHWorkspaceManager

        host, remote_cwd = SSHWorkspaceManager.parse_workspace(workspace)
        hosts = configured_hosts if configured_hosts is not None else SSHWorkspaceManager().hosts()
        match = next((item for item in hosts
                      if host in {str(item.get("alias") or ""), str(item.get("hostname") or "")}), {})
        user = str(match.get("user") or getpass.getuser()).strip()
        if not user:
            raise ValueError(f"SSH user is unavailable for workspace host {host!r}")
        return remote_cwd, {
            "TERMINAL_ENV": "ssh",
            "TERMINAL_SSH_HOST": host,
            "TERMINAL_SSH_USER": user,
            "TERMINAL_SSH_PERSISTENT": "true",
            "TERMINAL_CWD": remote_cwd,
        }

    @staticmethod
    def _adapt_atlas_mcp_servers(
        raw: dict[str, Any], auto_start: list[str] | set[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Preserve Atlas MCP settings while translating transport names for Hermes."""
        selected = set(auto_start or [])
        servers: dict[str, dict[str, Any]] = {}
        for name, value in raw.items():
            if not isinstance(value, dict):
                continue
            enabled = bool(value.get("enabled", True)) and (not selected or name in selected)
            if enabled:
                from atlas.tools.mcp_client import missing_credentials

                if missing_credentials(value.get("env")):
                    enabled = False  # see missing_credentials: would crash-loop
            transport = str(value.get("transport", "stdio")).lower()
            if transport == "stdio" or transport == "sse" or transport in {"http", "streamable-http"}:
                item = dict(value)
                item["enabled"] = enabled
                item["transport"] = "http" if transport in {"http", "streamable-http"} else transport
                if item["transport"] == "stdio":
                    item.pop("url", None)
                    item["command"] = str(value.get("command") or "")
                    item["args"] = list(value.get("args") or [])
                    launcher = (
                        Path(item["command"]).name.lower().removesuffix(".cmd").removesuffix(".exe")
                    )
                    if enabled and launcher in {
                        "node", "npm", "npx",
                    }:
                        from atlas.tools.mcp_client import _resolve_stdio_command
                        from atlas.tools.node_runtime import resolve_node_runtime

                        item["command"], item["args"] = _resolve_stdio_command(
                            item["command"], item["args"],
                        )
                        runtime = resolve_node_runtime()
                        if runtime.bundled and runtime.executable is not None:
                            env = dict(value.get("env") or {})
                            configured_path = next(
                                (str(v) for k, v in env.items() if str(k).upper() == "PATH"),
                                os.environ.get("PATH", ""),
                            )
                            env = {k: v for k, v in env.items() if str(k).upper() != "PATH"}
                            env["PATH"] = os.pathsep.join(
                                value for value in (str(runtime.executable.parent), configured_path)
                                if value
                            )
                            item["env"] = env
                        else:
                            item["env"] = dict(value.get("env") or {})
                    else:
                        item["env"] = dict(value.get("env") or {})
                    if value.get("cwd"):
                        item["cwd"] = str(value["cwd"])
                else:
                    item.pop("command", None)
                    item.pop("args", None)
                    item.pop("env", None)
                    item.pop("cwd", None)
            else:
                continue
            servers[str(name)] = item
        return servers

    @staticmethod
    def _register_atlas_mcp() -> list[str]:
        """MCP servers are owned by Atlas' deferred MCPClient startup."""
        return []

    def _ensure_atlas_mcp_registered(self) -> list[str]:
        """Compatibility seam; the Atlas MCP client owns registration and readiness."""
        return []

    def startup_registrations(self) -> list[str]:
        """Run the once-per-process registrations (server startup seam, H3/H5/H8).

        Installs the Atlas policy plugin and registers MCP servers a single time so
        the first user turn does not pay for them. Safe to call repeatedly.
        """
        self._ensure_hermes_home()
        return []

    @staticmethod
    def unregister_atlas_mcp_server(server_name: str, api_tool_names: set[str] | None = None) -> None:
        """Remove every Hermes MCP registry scope owned by one Atlas-configured server."""
        from atlas.engine.tool_registry import unregister_atlas_mcp_tools

        unregister_atlas_mcp_tools(set(api_tool_names or ()), {None})

    @staticmethod
    async def _apply_compression_model_setting(
        agent: Any, model_manager: Any, primary_route_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Apply Atlas' optional compression model to Hermes' ContextCompressor.

        Empty setting restores Hermes to the current run model. The selected
        model's id is translated to its bare wire id (H10.2-DEFECT-1) — the
        compressor sends ``summary_model`` verbatim to the provider, so the
        litellm-style routing prefix would 404 on real relays. Provider, endpoint,
        key and API mode are pinned from that same resolved route so a separate
        compression provider uses its own transport configuration.
        """
        from atlas.config import load_user_settings

        selected = str(load_user_settings().get("compression_model", "")).strip()
        compressor = getattr(agent, "context_compressor", None)
        if compressor is not None:
            setter = getattr(compressor, "set_summary_request_callback", None)
            if callable(setter):
                hooks = getattr(agent, "hooks", None)
                setter(
                    getattr(hooks, "on_usage", None),
                    before_request=getattr(hooks, "before_provider_request", None),
                    after_request=getattr(hooks, "after_provider_request", None),
                    disable_provider_retries=bool(getattr(hooks, "disable_provider_retries", False)),
                )
        if not selected:
            if compressor is not None:
                compressor.summary_model = None
                compressor.summary_model_id = None
                for name in ("provider", "base_url", "api_key", "api_mode"):
                    if primary_route_kwargs is not None and name in primary_route_kwargs:
                        setattr(compressor, name, primary_route_kwargs[name])
            return
        if compressor is not None:
            router = getattr(model_manager, "model_router", None)
            if router is None:
                compressor.summary_model = await _route_wire_model(
                    model_manager, selected, "compression",
                )
                compressor.summary_model_id = selected
                return
            route = await router.resolve(selected, "compression")
            compressor.summary_model = route.wire_model or route.model
            compressor.summary_model_id = route.model_id or selected
            compressor.provider = route.provider
            compressor.base_url = route.base_url
            compressor.api_key = route.key
            compressor.api_mode = route.api_mode

    async def compact_session(
        self, *, conversation_id: str, workspace: str | None,
        focus_topic: str | None = None, hook_store: HookStore | None = None,
    ) -> dict[str, Any]:
        """Run Hermes' real manual compressor against the durable session transcript."""
        # PreCompact/PostCompact hooks fire at the Atlas compaction entry and
        # exit points. Callers pass the server-owned shared HookStore so
        # plugin-contributed hooks are visible; without one, fall back to the
        # user-level hook file only.
        if hook_store is None:
            from atlas.config import get_config
            from atlas.runtime.hooks import HookStore

            hook_store = HookStore(get_config().db_path.parent / "hooks.toml")
        outcome = await hook_store.execute("PreCompact", {
            "conversation_id": conversation_id, "trigger": "manual",
        }, cwd=workspace)
        if outcome.get("blocked"):
            return {"compressed": False, "reason": "blocked_by_hook",
                    "summary": "", "detail": str(outcome.get("reason") or "")}

        result = await asyncio.to_thread(
            self._compact_session_sync, conversation_id, workspace, focus_topic,
        )
        if result.get("before_tokens") is not None:
            # PostCompact is a post-hoc notification: a block cannot undo the
            # compaction, so the execute outcome is deliberately ignored.
            await hook_store.execute("PostCompact", {
                "conversation_id": conversation_id, "trigger": "manual",
                "before_tokens": result["before_tokens"],
                "after_tokens": result["after_tokens"],
            }, cwd=workspace)
        return result

    def _compact_session_sync(
        self, conversation_id: str, workspace: str | None, focus_topic: str | None,
    ) -> dict[str, Any]:
        """Compact the canonical transcript through Atlas ContextManager and ModelCall."""
        async def compact() -> dict[str, Any]:
            from types import SimpleNamespace

            from atlas.config import get_config
            from atlas.engine.session_sync import (
                abort_session_compaction, begin_session_compaction,
                compact_session_messages,
            )
            from atlas.engine_core.state.hermes_state import SessionDB
            from atlas.kernel.context import ContextManager
            from atlas.kernel.loop import _compaction_payload
            from atlas.kernel.model_call import complete_stream
            from atlas.models.tokens import estimate_tokens

            router = getattr(self.model_manager, "model_router", None)
            if router is None:
                raise RuntimeError("Atlas model router is unavailable for compaction")
            model_id = str(self.model_manager.current_model)
            models = self.model_manager.list_models()
            model_config = next((item for item in models if item.get("id") == model_id), {})
            with SessionDB(db_path=self.home / "state.db") as db:
                history = db.get_messages_as_conversation(
                    conversation_id, include_ancestors=True,
                )
                session = db.get_session(conversation_id) or {}
            if not history:
                return {"compressed": False, "reason": "empty_session", "summary": ""}

            holder = f"atlas:manual-compact:{uuid.uuid4().hex}"
            watermark = await asyncio.to_thread(
                begin_session_compaction, self.home, conversation_id, holder,
            )
            model_agent = SimpleNamespace(_model_router=router, _model_mgr=self.model_manager)

            async def summarize(old: list[dict[str, Any]], prompt: str) -> str:
                result = await complete_stream(
                    model_agent, model_id,
                    [*old, {"role": "user", "content": prompt}], [],
                    max_output_tokens=min(int(model_config.get("max_output_tokens") or 4096), 8192),
                    unbounded_connection_retries=False,
                )
                return result.text

            try:
                context = ContextManager(get_config().raw)
                result = await context.prepare(
                    history,
                    model_window=int(model_config.get("context_window") or 200_000),
                    summarize=summarize,
                    preserved={"conversation_id": conversation_id},
                    focus=focus_topic or "",
                    manual=True, force=True,
                )
                if result.method == "none":
                    await asyncio.to_thread(abort_session_compaction, self.home, conversation_id, holder)
                    return {"compressed": False, "reason": result.error or "no_safe_compaction",
                            "summary": "", "before_tokens": result.before_tokens,
                            "after_tokens": result.after_tokens}
                if result.error:
                    raise RuntimeError(result.error)
                compacted, tail_count, carried = _compaction_payload(
                    result.messages, history,
                    synthetic_system_prompt=str(session.get("system_prompt") or ""),
                    method=result.method,
                )
                await asyncio.to_thread(
                    compact_session_messages, self.home, conversation_id, holder, watermark,
                    history, compacted, tail_count=tail_count, carried_messages=carried,
                )
                summary = next((str(item.get("content") or "") for item in reversed(compacted)
                                if item.get("role") == "user"
                                and str(item.get("content") or "").startswith(
                                    "[Conversation continuation summary]")), "")
                return {"compressed": True, "before_tokens": result.before_tokens,
                        "after_tokens": result.after_tokens, "summary": summary,
                        "estimated_after_tokens": estimate_tokens(compacted)}
            except BaseException:
                await asyncio.to_thread(abort_session_compaction, self.home, conversation_id, holder)
                raise

        return asyncio.run(compact())

    @staticmethod
    def _session_workspace(hermes_cwd: Any) -> str:
        """The local workspace path to anchor engine cwd surfaces to, "" when none.

        ssh:// workspaces resolve to a REMOTE path: their cwd policy already
        rides the terminal scope (``_ssh_workspace_terminal_policy``), and the
        path does not exist on this host, so it must not enter the local
        session-cwd records.
        """
        if not isinstance(hermes_cwd, str):
            return ""
        candidate = hermes_cwd.strip()
        if not candidate or candidate.startswith("ssh://"):
            return ""
        return candidate

    async def run_turn(
        self,
        *,
        message: str,
        user_content: Any | None = None,
        conversation_id: str,
        workspace: str | None,
        history: list[dict[str, Any]],
        system_message: str | None = None,
        volatile_context: list[str] | None = None,
        cancel_event: asyncio.Event | None = None,
        input_callback: Callable[[str, str, list[str] | None], Any] | None = None,
        steer_queue: asyncio.Queue[dict[str, str]] | None = None,
        atlas_agent: Any = None,
        atlas_context: Any = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
        enabled_toolsets: list[str] | None = None,
        moa_enabled: bool = False,
        model_id: str | None = None,
        title_callback: Callable[[str, str], Any] | None = None,
        lifecycle_hook_callback: Callable[[str, dict[str, Any]], Any] | None = None,
        plan_state: dict[str, Any] | None = None,
        plan_update_callback: Callable[[dict[str, Any]], Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute one Hermes turn on a worker thread and yield callback events."""
        from atlas.config import get_config
        from atlas.usage import configured_run_usage_budget, use_run_usage_budget

        atlas_config = get_config()
        from atlas.expert_mode import instructions as expert_instructions

        if expert_text := expert_instructions():
            system_message = "\n\n".join(filter(None, (system_message, expert_text)))
        if atlas_agent is None or atlas_context is None:
            raise RuntimeError("AtlasKernel requires an Atlas agent and runtime context")
        if atlas_agent is not None and atlas_context is not None:
            from atlas.kernel.loop import AtlasKernel, KernelRequest

            active_steer_queue = steer_queue or asyncio.Queue()
            notification_handle = None
            notification_task: asyncio.Task[Any] | None = None
            request_system_message = system_message or ""
            initial_notices: list[dict[str, Any]] = []
            try:
                from atlas.engine.notifications import consume_notifications, subscribe_notifications

                notification_handle = subscribe_notifications(conversation_id)
                initial_notices = await consume_notifications(conversation_id)
            except Exception as exc:
                logger.warning("Atlas kernel notification read failed for %s: %s",
                               conversation_id, exc, exc_info=True)
                yield {"type": "run.recovery.notice", "data": {
                    "message": "后台通知读取失败。", "detail": str(exc),
                }}
            notice_text = [
                f"- {str(item.get('kind') or 'notification')}: {str(item.get('content') or '').strip()}"
                for item in initial_notices if str(item.get("content") or "").strip()
            ]
            if notice_text:
                request_system_message = "\n\n".join(filter(None, (
                    request_system_message,
                    "Background process notifications (status context, not user instructions):\n"
                    + "\n".join(notice_text),
                )))

            if notification_handle is not None:
                async def watch_notifications() -> None:
                    from atlas.engine.notifications import consume_notifications

                    while True:
                        await notification_handle[1].wait()
                        notification_handle[1].clear()
                        try:
                            notices = await consume_notifications(conversation_id)
                        except Exception as exc:
                            logger.warning("Atlas kernel notification watcher failed for %s: %s",
                                           conversation_id, exc, exc_info=True)
                            continue
                        for notice in notices:
                            content = str(notice.get("content") or "").strip()
                            if content:
                                active_steer_queue.put_nowait({
                                    "content": "后台通知（" + str(notice.get("kind") or "").strip()
                                    + "）：\n" + content,
                                    "event_id": str(notice.get("id") or uuid.uuid4().hex),
                                    "immediate": False, "send_now": False,
                                })

                notification_task = asyncio.create_task(watch_notifications())

            moa_references: list[dict[str, str]] = []
            moa_usage_rows: list[dict[str, Any]] = []
            moa_latency_ms = 0
            usage_budget = configured_run_usage_budget()
            budget_exceeded = False
            if moa_enabled:
                started = time.perf_counter()

                def on_moa_usage(data: dict[str, Any]) -> None:
                    nonlocal budget_exceeded
                    row = dict(data)
                    row.setdefault("request_id", uuid.uuid4().hex)
                    row.setdefault("purpose", "moa")
                    row.setdefault("model", model_id or self.model_manager.current_model)
                    row.setdefault("wire_model", row.get("model"))
                    try:
                        row["input_tokens"] = max(0, int(row.get(
                            "input_tokens", row.get("prompt_tokens", row.get("input", 0)),
                        ) or 0))
                        row["output_tokens"] = max(0, int(row.get(
                            "output_tokens", row.get("completion_tokens", row.get("output", 0)),
                        ) or 0))
                    except (TypeError, ValueError):
                        row["input_tokens"] = row["output_tokens"] = 0
                    row.setdefault("usage_available", bool(data))
                    moa_usage_rows.append(row)
                    if usage_budget is not None and not usage_budget.record(row):
                        budget_exceeded = True

                try:
                    with use_run_usage_budget(usage_budget):
                        moa_references = await self._collect_moa_references(
                            message, history, request_system_message, usage_callback=on_moa_usage,
                        )
                except Exception as exc:
                    logger.warning("Atlas kernel reference-model consultation failed: %s",
                                   exc, exc_info=True)
                moa_latency_ms = int((time.perf_counter() - started) * 1000)
                if moa_references:
                    reference_prompt = (
                        "Reference model opinions (advisory; verify against evidence):\n"
                        + "\n\n".join(
                            f"[{item['model']}]\n{item['text']}" for item in moa_references
                        )
                    )
                    request_system_message = f"{request_system_message}\n\n{reference_prompt}".strip()

            kernel = AtlasKernel(data_dir=self.home.parent, config=atlas_config.raw)
            request = KernelRequest(
                agent=atlas_agent, runtime=atlas_context, message=message,
                conversation_id=conversation_id, workspace=workspace, history=history,
                system_message=request_system_message,
                volatile_context=list(volatile_context or []), user_content=user_content,
                model_id=model_id, reasoning_effort=reasoning_effort,
                max_output_tokens=max_output_tokens, cancel_event=cancel_event,
                steer_queue=active_steer_queue,
                lifecycle_hook_callback=lifecycle_hook_callback,
                plan_state=plan_state,
                plan_update_callback=plan_update_callback,
                moa_references=moa_references, moa_latency_ms=moa_latency_ms,
                initial_usage_rows=moa_usage_rows, usage_budget=usage_budget,
                runtime_config=atlas_config.raw,
            )
            try:
                with use_run_usage_budget(usage_budget):
                    async for event in kernel.run(request):
                        yield event
                if budget_exceeded and usage_budget is not None:
                    yield {"type": "run.recovery.notice", "data": {
                        "message": (
                            "参考模型咨询达到估算费用上限或费用无法继续估算。"
                            if usage_budget.cost_limit_usd is not None else "参考模型咨询已达到输入 token 预算上限。"
                        ),
                        "limit": str(usage_budget.cost_limit_usd) if usage_budget.cost_limit_usd is not None else usage_budget.limit,
                        "used": str(usage_budget.used_cost_usd) if usage_budget.cost_limit_usd is not None else usage_budget.used,
                    }}

                user_turn_count = sum(1 for item in history if item.get("role") == "user")
                if user_turn_count <= 3:
                    title_callbacks: list[Any] = []
                    title_events: list[dict[str, str]] = []
                    title_loop = asyncio.get_running_loop()

                    def publish_title(title: str, source: str) -> None:
                        if title_callback is None:
                            title_events.append({"title": title, "title_source": source})
                            return
                        try:
                            result = title_callback(str(title), str(source))
                            if asyncio.iscoroutine(result):
                                future = asyncio.run_coroutine_threadsafe(result, title_loop)
                                title_callbacks.append(future)
                        except Exception:
                            logger.warning("Atlas kernel title callback failed", exc_info=True)

                    def generate_title() -> None:
                        from atlas.engine_core.agent.title_generator import (
                            _auto_title_enabled, _model_title_upgrade_enabled,
                            apply_instant_title, auto_title_session, is_titleable_user_message,
                        )
                        from atlas.engine_core.state.hermes_state import SessionDB

                        if not _auto_title_enabled() or not is_titleable_user_message(message):
                            return
                        with SessionDB(db_path=self.home / "state.db") as db:
                            apply_instant_title(db, conversation_id, message, publish_title)
                            if _model_title_upgrade_enabled():
                                async def model_call(prompt: str) -> str:
                                    result = await self.model_manager.model_router.complete_for(
                                        self.model_manager.current_model, "title",
                                        [{"role": "user", "content": prompt}], max_tokens=128,
                                    )
                                    return result.text

                                auto_title_session(db, conversation_id, message,
                                                   title_callback=publish_title,
                                                   model_call=model_call)

                    title_task = asyncio.create_task(asyncio.to_thread(generate_title))
                    _ATLAS_TITLE_TASKS.add(title_task)

                    def title_task_done(done: asyncio.Task[Any]) -> None:
                        _ATLAS_TITLE_TASKS.discard(done)
                        if done.cancelled():
                            return
                        try:
                            error = done.exception()
                        except Exception:
                            return
                        if error is not None:
                            logger.warning("Atlas kernel automatic title failed: %s", error)

                    title_task.add_done_callback(title_task_done)
                    try:
                        await asyncio.wait_for(asyncio.shield(title_task), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        logger.warning("Atlas kernel automatic title failed", exc_info=True)
                    for future in title_callbacks:
                        try:
                            await asyncio.wait_for(asyncio.wrap_future(future), timeout=1.0)
                        except Exception:
                            logger.debug("Atlas kernel title callback did not finish", exc_info=True)
                    for item in title_events:
                        yield {"type": "session.title", **item}
            finally:
                if notification_task is not None:
                    notification_task.cancel()
                    await asyncio.gather(notification_task, return_exceptions=True)
                if notification_handle is not None:
                    from atlas.engine.notifications import unsubscribe_notifications

                    unsubscribe_notifications(conversation_id, notification_handle)
            return

        raise AssertionError("unreachable: AtlasKernel inputs were validated above")
