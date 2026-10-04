"""Deferred startup components (H8 §10.2 S2).

The server lifespan's critical path ends at ``yield``; this module then starts
everything whose completion the first requests do not require. Each component
is registered on ``StartupComponents`` (S1) as ``starting`` by the critical
path and flips to ``ready``/``failed`` here, so /api/health (S4) reports
progress and a component failure never kills the server (H6 style: bounded,
logged, degraded — visible recovery on the run path via S3).

Independent components start as parallel tasks on the loop; documented W10
dependencies stay explicit (automation waits for the ``dbos`` component; the
plugin index refresh follows the initial skill scan).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from atlas.api.startup_components import StartupComponents

log = structlog.get_logger()

# Background mcp warmups (no-configured-servers fast path); shutdown awaits
# them so a lifespan restart never leaks an import task across loops.
_MCP_WARMUP_TASKS: set[asyncio.Task] = set()


async def await_mcp_warmups(timeout: float = 10.0) -> None:
    """Wait for pending mcp warmups (bounded; used by server shutdown)."""
    if _MCP_WARMUP_TASKS:
        await asyncio.wait(_MCP_WARMUP_TASKS, timeout=timeout)


async def _component(
    components: StartupComponents, name: str, step: Callable[[], Awaitable[None]],
) -> None:
    """Run one component step; success marks ready, failure marks failed."""
    try:
        await step()
    except asyncio.CancelledError:
        raise
    except Exception:
        components.mark(name, "failed")
        log.exception("startup.component_failed", component=name)
    else:
        components.mark(name, "ready")


async def run_deferred_startup(app: Any, services: Any, components: StartupComponents) -> None:
    """Start every deferred component; independent ones run concurrently."""
    branches = [
        asyncio.create_task(
            _component(components, "dbos", lambda: _start_dbos(services)),
            name="startup-dbos",
        ),
        asyncio.create_task(
            _component(components, "mcp", lambda: _start_mcp(services)),
            name="startup-mcp",
        ),
        asyncio.create_task(
            _start_skills_plugins(services, components),
            name="startup-skills-plugins",
        ),
        asyncio.create_task(
            _component(components, "engine_registrations",
                       lambda: _start_engine_registrations(services)),
            name="startup-engine-registrations",
        ),
        asyncio.create_task(
            _component(components, "channels", lambda: _start_channels(services)),
            name="startup-channels",
        ),
        asyncio.create_task(
            _component(components, "automation",
                       lambda: _start_automation(services, components)),
            name="startup-automation",
        ),
        asyncio.create_task(
            _component(components, "scheduler", lambda: _start_scheduler(services)),
            name="startup-scheduler",
        ),
        asyncio.create_task(
            _component(components, "telegram", lambda: _start_telegram(services)),
            name="startup-telegram",
        ),
        asyncio.create_task(
            _component(components, "extensions",
                       lambda: _register_extensions(app)),
            name="startup-extensions",
        ),
    ]
    results = await asyncio.gather(*branches, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            # _component already logged per-component; this only guards the
            # wrapper itself (e.g. an internal bug) so shutdown stays clean.
            log.error("startup.deferred_branch_error", error=str(result))
    # The fast-path mcp warmup is not a component (health flipped ready when
    # the branch returned); still settle it here so a lifespan restart never
    # leaks an import task across event loops.
    await await_mcp_warmups(timeout=10.0)


async def _start_dbos(services: Any) -> None:
    """S2.1 + S5: launch DBOS, skipping migrations when nothing changed.

    The launch (system-DB migration ladder + executor startup) is sqlite-I/O
    heavy; running it on a worker thread lets the CPU-bound mcp-chain import
    proceed on the loop concurrently instead of serializing behind it.
    """
    from atlas.api.dbos_startup import migrations_current, record_started
    from atlas.config import get_config

    durable = services.durable
    data_dir = get_config().db_path.parent
    skip_migrations = migrations_current(data_dir)
    status = await asyncio.to_thread(
        lambda: durable.start(run_migrations=not skip_migrations),
    )
    record_started(data_dir, started=bool(status.get("started")))
    if not status.get("started"):
        raise RuntimeError(f"dbos start failed: {status.get('start_error')}")
    if skip_migrations:
        log.info("dbos.migrations_skipped", reason="version_unchanged")
    _fetch_dbos_instance()


def _fetch_dbos_instance() -> None:
    # W10: durable.start() constructed + launched the process-global DBOS
    # singleton; the automation engine reuses that same instance (never a
    # second DBOS per process). NOTE: _dbos_global_instance lives on the
    # dbos._dbos MODULE, not on the DBOS class — a class-level getattr
    # always misses.
    import dbos._dbos as _dbos_module

    getattr(_dbos_module, "_dbos_global_instance", None)


def _mcp_servers_configured() -> bool:
    """Mirror ``mcp_client._parse_server_configs``' enabled-server decision.

    Deliberately config-only: importing the module would pull the mcp chain —
    the exact cost the fast path below avoids. The background warmup still
    calls the real parser (and connects anything this mirror could ever miss),
    so a divergence self-heals within seconds.
    """
    from atlas.config import get_config

    cfg = get_config()
    servers_raw: dict[str, Any] = cfg.get("tools.servers", {}) or {}
    auto_start: list[str] = cfg.get("tools.auto_start", []) or []
    for name, data in servers_raw.items():
        if not isinstance(data, dict):
            continue
        if not data.get("enabled", True):
            continue
        if auto_start and name not in auto_start:
            continue
        return True
    return False


def _construct_mcp_client() -> Any:
    from atlas.tools.mcp_client import MCPClient

    return MCPClient()


async def _warm_mcp_chain() -> None:
    """Import the heavy mcp chain + start the (empty) client off the hot path.

    Only used on the no-configured-servers fast path: the proxy keeps serving
    until the real client is bound (never clobbering a test patch).
    """
    try:
        import atlas.server as server_module

        client = await asyncio.to_thread(_construct_mcp_client)
        if isinstance(server_module.mcp_client, server_module._DeferredMCPClient):
            server_module.mcp_client = client
        await client.start()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("mcp.warmup_failed")


async def _start_mcp(services: Any) -> None:
    """S2.2: bring MCP up.

    With configured servers, construct + connect here (the heavy mcp import
    chain is paid after uvicorn binds, not at module import). With none, there
    is nothing to connect and every consumer reads the client lazily through
    the proxy — mark ready immediately and warm the import in the background
    so the first request never pays it.
    """
    import atlas.server as server_module

    if not _mcp_servers_configured():
        warmup = asyncio.create_task(_warm_mcp_chain(), name="startup-mcp-warmup")
        _MCP_WARMUP_TASKS.add(warmup)
        warmup.add_done_callback(_MCP_WARMUP_TASKS.discard)
        return
    mcp_client = await asyncio.to_thread(_construct_mcp_client)
    server_module.mcp_client = mcp_client
    await mcp_client.start()


async def _scan_and_register_skills(services: Any) -> None:
    """S2.3: scan the shared skill index, then expose each indexed skill as an
    agent capability (register_skill_capabilities iterates list_skills(), so
    it must follow the scan)."""
    from atlas.agent.capabilities import register_skill_capabilities

    await services.skill_mgr.scan_skills()
    register_skill_capabilities(
        services.orchestrator.capabilities,
        services.skill_mgr,
        services.skill_registry,
        services.mcp_client,
    )


async def _start_skills_plugins(services: Any, components: StartupComponents) -> None:
    """S2.3 + S2.4: skill index scan, then plugin load + extension sources.

    Two components on one serial branch (the plugin index refresh must follow
    the initial scan); each sub-step settles its own component state.
    """
    from atlas.api.run_drive import _refresh_extension_sources

    await _component(components, "skills", lambda: _scan_and_register_skills(services))

    async def _load_plugins() -> None:
        plugin_load_report = await services.plugin_runtime.load_all(
            hook_bus=services.orchestrator.hooks,
            mcp_client=services.mcp_client,
            capabilities=services.orchestrator.capabilities,
        )
        _refresh_extension_sources()
        if plugin_load_report.get("errors"):
            log.warning("plugins.load_errors", errors=plugin_load_report["errors"])

    await _component(components, "plugins", _load_plugins)


async def _start_engine_registrations(services: Any) -> None:
    """S2.5: H3/H5 seam — once-per-process registrations (Atlas policy plugin
    + Hermes MCP servers) so the first user turn does not pay for them.
    Idempotent and fingerprint-checked; a failure only means the first turn
    re-runs the registration. The engine import + registration work is CPU
    heavy and thread-safe; off the loop it overlaps the DBOS worker."""
    try:
        await asyncio.to_thread(_engine_startup_registrations, services.model_mgr)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — degraded to a warning; first turn retries
        log.exception("engine.startup_registrations_failed")


def _engine_startup_registrations(model_manager: Any) -> None:
    from atlas.config import DATA_ROOT
    from atlas.engine import HermesRuntime

    HermesRuntime(data_dir=DATA_ROOT, model_manager=model_manager).startup_registrations()


async def _start_channels(services: Any) -> None:
    """S2.6 tail: the channel stack (manager/bridge wiring happened on the
    critical path) starts its adapters and polling loops here."""
    await services.channel_manager.start()


async def _start_automation(services: Any, components: StartupComponents) -> None:
    """S2.7: heartbeat reconcile + automation engine, gated on the dbos
    component (W10: the engine reuses the process-global DBOS instance)."""
    from atlas.api.run_drive import _reconcile_agent_heartbeats
    from atlas.automation import get_automation_engine

    if not await components.wait_ready("dbos", timeout=120.0):
        # durable.start() failed: automation CRUD keeps working (store only),
        # but triggers/runs report 503 until the next restart.
        log.warning("automation.engine_not_started", reason="dbos_not_ready")
        return
    import dbos._dbos as _dbos_module

    dbos_instance = getattr(_dbos_module, "_dbos_global_instance", None)
    automation_engine = get_automation_engine()
    if automation_engine is None or dbos_instance is None:
        log.warning("automation.engine_not_started", reason="dbos_instance_unavailable")
        return
    await automation_engine.start_async(dbos_instance)
    await _reconcile_agent_heartbeats(services.persistent_agents, automation_engine)


async def _start_scheduler(services: Any) -> None:
    """S2.8: scheduler start (no-op when disabled — still a ready component)."""
    import atlas.server as server_module
    from atlas.api.run_drive import _scheduled_goal
    from atlas.config import get_config
    from atlas.scheduler import AtlasScheduler

    if get_config().scheduler_enabled:
        scheduler = AtlasScheduler(agent_callback=_scheduled_goal)
        await scheduler.start()
        server_module.scheduler = scheduler


async def _start_telegram(services: Any) -> None:
    """S2.9: legacy TelegramService fallback poll — only when the gateway's
    telegram channel is NOT enabled, so the two stacks never double-poll."""
    from atlas.config import get_config

    telegram_service = services.telegram_service
    channel_manager = services.channel_manager
    if not ((channel_manager.configs if channel_manager else {}).get("telegram") or {}).get(
        "enabled",
    ):
        telegram_service.start()


async def _register_extensions(app: Any) -> None:
    """S2.10: /init 与 /review 的路由和工具注册。这些模块由独立子模块提供，
    注册失败只降级告警，绝不能拖垮 Atlas 本体启动。"""
    try:
        from atlas.commands.init import register_init_routes

        register_init_routes(app)
    except Exception:  # /init 模块缺失或注册失败只降级（lint: logger.exception）
        log.exception("C6 启动注册 /init 路由失败，/init 功能暂不可用")
    try:
        from atlas.review.engine import register_review_tools

        register_review_tools()
    except Exception:  # review 模块缺失或注册失败只降级
        log.exception("C6 启动注册审查工具失败，/review 功能暂不可用")
    try:
        from atlas.review.engine import register_review_routes

        register_review_routes(app)
    except Exception:  # review 路由注册失败只降级
        log.exception("C6 启动注册 /review 路由失败，/review 功能暂不可用")
