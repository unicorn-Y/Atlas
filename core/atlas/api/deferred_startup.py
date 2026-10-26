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


def restore_lifespan_routes(app: Any, route_count: int) -> None:
    """Drop routes registered by a deferred extension when its app closes."""
    del app.router.routes[route_count:]
    app.openapi_schema = None


async def shutdown_lifespan_components(app: Any, state: dict[str, Any], route_count: int) -> None:
    """Release lifespan-owned services after startup settles or is cancelled."""
    import atlas.server as server_module
    from atlas.api import group_router
    from atlas.server import _DeferredMCPClient, get_automation_engine
    from atlas.tools.x2 import browser as x2browser
    from atlas.tools.x2 import computer as x2computer

    await _stop_background_startup_tasks(app)

    def resource(name: str) -> Any:
        return state[name] if name in state else getattr(server_module, name, None)

    for name in ("telegram_service", "scheduler"):
        service = resource(name)
        if service:
            await service.stop()
    channel_manager = resource("channel_manager")
    if channel_manager is not None:
        await channel_manager.stop()
        channel_manager.close()
    gateway_bridge = resource("gateway_bridge")
    if gateway_bridge is not None:
        gateway_bridge.sessions.close()
    automation_engine = get_automation_engine()
    if automation_engine is not None:
        automation_engine.shutdown()
    heartbeat_service = resource("heartbeat_service")
    if heartbeat_service is not None:
        await heartbeat_service.aclose()
    group_router.set_group_orchestrator(None)
    group_router.set_group_service(None)
    mcp_client = resource("mcp_client")
    if isinstance(mcp_client, _DeferredMCPClient):
        mcp_client = server_module.mcp_client
    if mcp_client is not None and not isinstance(mcp_client, _DeferredMCPClient):
        await mcp_client.stop()
    for name in ("local_execution", "computer_use"):
        service = resource(name)
        if service:
            await service.shutdown()
    await x2computer.shutdown()
    await x2browser.shutdown()
    cua_backend = resource("cua_backend")
    if cua_backend:
        await cua_backend.close()
    browser_use = resource("browser_use")
    if browser_use:
        for session_id in list(browser_use._sessions):
            await browser_use.close(session_id)
    ssh_workspaces = resource("ssh_workspaces")
    if ssh_workspaces is not None:
        await ssh_workspaces.close()
    agent_backend_host = resource("agent_backend_host")
    if agent_backend_host:
        await agent_backend_host.shutdown()
    durable = resource("durable")
    if durable:
        durable.stop()
    for name in ("projects", "usage_ledger", "memory", "manager"):
        service = resource(name)
        if service:
            await service.close()
    restore_lifespan_routes(app, route_count)


def start_lifespan_components(
    app: Any, services: Any, components: StartupComponents,
) -> tuple[asyncio.Task[None], int]:
    """Open the migration barrier before scheduling any request-visible startup work."""
    from atlas.config import DATA_ROOT
    from atlas.session_migration_gate import begin_session_migration

    begin_session_migration(DATA_ROOT / "engine")
    route_count = len(app.routes)
    task = asyncio.create_task(
        run_deferred_startup(app, services, components),
        name="atlas-deferred-startup",
    )
    return task, route_count


async def _component(
    components: StartupComponents, name: str, step: Callable[[], Awaitable[None]],
) -> None:
    """Run one component step; success marks ready, failure marks failed."""
    try:
        await step()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        components.mark(name, "failed", error=str(exc))
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
                       lambda: _start_engine_registrations(app, services)),
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
        asyncio.create_task(
            _component(components, "session_migration",
                       lambda: _migrate_legacy_sessions(services)),
            name="startup-session-migration",
        ),
    ]
    if getattr(app, "state", None) is not None:  # test doubles pass a bare object
        _schedule_background(app, "upstream-auto", _upstream_auto_loop())
    results = await asyncio.gather(*branches, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            # _component already logged per-component; this only guards the
            # wrapper itself (e.g. an internal bug) so shutdown stays clean.
            log.error("startup.deferred_branch_error", error=str(result))


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
    start_task = asyncio.create_task(
        asyncio.to_thread(lambda: durable.start(run_migrations=not skip_migrations)),
        name="startup-dbos-worker",
    )
    try:
        status = await asyncio.shield(start_task)
    except asyncio.CancelledError:
        cancel_start = getattr(durable, "cancel_pending_start", None)
        if callable(cancel_start):
            cancel_start()
        start_task.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None,
        )
        raise
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


def _construct_mcp_client() -> Any:
    from atlas.tools.mcp_client import MCPClient

    return MCPClient()


def _mcp_servers_configured() -> bool:
    """Mirror MCPClient.start's enabled-server filter without importing MCP SDKs."""
    from atlas.config import get_config

    config = get_config()
    servers = config.get("tools.servers", {}) or {}
    auto_start = config.get("tools.auto_start", []) or []
    if not isinstance(servers, dict):
        return True  # Let MCPClient report malformed configuration as a startup failure.
    return any(
        isinstance(value, dict)
        and value.get("enabled", True)
        and (not auto_start or name in auto_start)
        for name, value in servers.items()
    )


async def _start_mcp(services: Any) -> None:
    """S2.2: bring MCP up.

    The heavy MCP import and optional server connections are paid after
    uvicorn binds, not on the critical path. With no enabled servers the MCP
    component is settled without importing the SDK; the deferred proxy keeps
    dynamic add and first-use access compatible.
    """
    import os
    if os.environ.get("ATLAS_SAFE_MODE") == "1":
        log.info("startup.safe_mode.skipped", component="mcp")
        return
    if not _mcp_servers_configured():
        log.info("mcp.no_servers_configured")
        return

    import atlas.server as server_module

    # Importing the MCP SDK from a worker thread can deadlock when its package
    # initialization overlaps the API's lazy mcp.types router import. The
    # constructor is lightweight; keep this deferred import serialized on the
    # event-loop thread, after the listener is available.
    mcp_client = _construct_mcp_client()
    server_module.mcp_client = mcp_client
    await mcp_client.start()


async def _migrate_legacy_sessions(services: Any) -> None:
    """R3 startup seam: import historical sessions after the API is serving."""
    from atlas.config import DATA_ROOT, get_config
    from atlas.session_migration_gate import finish_session_migration, has_legacy_transcripts

    home = DATA_ROOT / "engine"
    try:
        if not has_legacy_transcripts(
            get_config().db_path, DATA_ROOT / "engine" / "state.db",
        ):
            finish_session_migration(home, "ready")
            return
        from atlas.engine.session_migration import migrate_legacy_sessions

        report = await migrate_legacy_sessions(home, services.memory)
        if report.status == "failed":
            raise RuntimeError(report.error or "Session history migration failed")
    except BaseException:
        finish_session_migration(home, "failed")
        raise


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
    import os
    if os.environ.get("ATLAS_SAFE_MODE") == "1":
        components.mark("skills", "ready")
        components.mark("plugins", "ready")
        log.info("startup.safe_mode.skipped", component="skills_plugins_extensions")
        return
    from atlas.api.run_drive import _refresh_extension_sources

    try:
        from atlas import expert_mode

        await asyncio.to_thread(expert_mode.ensure_pack)
        expert_mode.prime_runtime(services)
    except Exception:  # noqa: BLE001 — 专家目录出问题不能拖住启动
        log.exception("expert_mode.prime_failed")

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
        try:
            from atlas import expert_mode

            await expert_mode._apply_mcp(services)
        except Exception:  # noqa: BLE001
            log.exception("expert_mode.mcp_start_failed")

    await _component(components, "plugins", _load_plugins)


async def _start_engine_registrations(app: Any, services: Any) -> None:
    """S2.5: H3/H5 seam — once-per-process registrations (Atlas policy plugin
    + Hermes MCP servers) so the first user turn does not pay for them.
    Idempotent and fingerprint-checked; a failure only means the first turn
    re-runs the registration. The engine import + registration work is CPU
    heavy and thread-safe; off the loop it overlaps the DBOS worker."""
    await asyncio.to_thread(_engine_startup_registrations, services.model_mgr)
    # Warming is not a readiness condition: /api/health must not wait seconds for it.
    # A first turn that arrives earlier simply waits on the import lock in its own
    # worker thread, never on the event loop.
    task = asyncio.get_running_loop().create_task(
        asyncio.to_thread(_warm_engine), name="startup-engine-warmup",
    )
    background_tasks = getattr(app.state, "_atlas_background_startup_tasks", None)
    if background_tasks is None:
        background_tasks = set()
        app.state._atlas_background_startup_tasks = background_tasks
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


def _schedule_background(app: Any, name: str, coro: Awaitable[None]) -> None:
    """Run an optional long-lived task that the app cancels on shutdown."""
    task = asyncio.get_running_loop().create_task(coro, name=name)
    background_tasks = getattr(app.state, "_atlas_background_startup_tasks", None)
    if background_tasks is None:
        background_tasks = set()
        app.state._atlas_background_startup_tasks = background_tasks
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def _upstream_auto_loop() -> None:
    """自动追新：定时检查第三方组件，自动模式下在预演副本里更新（atlas.upstream）。"""
    from atlas.upstream.service import auto_loop

    await auto_loop()


# Atlas-owned modules the first turn needs. Import them on a worker thread so
# optional engine setup never delays the API-ready signal.
_ENGINE_WARM_IMPORTS = (
    "atlas.engine_core.agent.agent_hooks", "atlas.engine_core.agent.plan_prompt",
    "atlas.engine_core.tools.registry",
    "atlas.engine.tool_registry", "atlas.engine.hermes_policy",
)


async def _stop_background_startup_tasks(app: Any) -> None:
    """Cancel and drain this app's optional warmups without waiting for their threads."""
    background_tasks = getattr(app.state, "_atlas_background_startup_tasks", None)
    if background_tasks is None:
        return
    tasks = tuple(background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        background_tasks.difference_update(tasks)
    if not background_tasks:
        delattr(app.state, "_atlas_background_startup_tasks")


def _engine_startup_registrations(model_manager: Any) -> None:
    from atlas.config import DATA_ROOT
    from atlas.engine import HermesRuntime

    HermesRuntime(data_dir=DATA_ROOT, model_manager=model_manager).startup_registrations()


def _warm_engine() -> None:
    import importlib

    try:
        for module in _ENGINE_WARM_IMPORTS:
            importlib.import_module(module)
        # Token estimates need the tiktoken BPE file, which may have to be downloaded.
        from atlas.models.tokens import prefetch

        prefetch()
    except Exception:
        # Warming is an optimisation; the first turn imports whatever is missing.
        log.exception("startup.engine_warmup_failed")


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
        raise RuntimeError("automation engine not started: DBOS is not ready")
    import dbos._dbos as _dbos_module

    dbos_instance = getattr(_dbos_module, "_dbos_global_instance", None)
    automation_engine = get_automation_engine()
    if automation_engine is None or dbos_instance is None:
        raise RuntimeError("automation engine not started: DBOS instance unavailable")
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
    telegram_service = services.telegram_service
    channel_manager = services.channel_manager
    if not ((channel_manager.configs if channel_manager else {}).get("telegram") or {}).get(
        "enabled",
    ):
        telegram_service.start()


async def _register_extensions(app: Any) -> None:
    """S2.10: /init 与 /review 的路由和工具注册。这些模块由独立子模块提供，
    注册失败只降级告警，绝不能拖垮 Atlas 本体启动。"""
    import os
    if os.environ.get("ATLAS_SAFE_MODE") == "1":
        log.info("startup.safe_mode.skipped", component="extension_routes_and_tools")
        return
    errors: list[str] = []
    try:
        # MCP's SDK import graph is large; load its resource routes after the
        # core API has started answering requests.
        from atlas.api import mcp_resources_router as _mcp_resources_router  # noqa: F401
    except Exception:  # noqa: BLE001 — an optional integration must not gate chat
        log.exception("startup.mcp_resource_routes_failed")
        errors.append("MCP resource route implementation failed")
    try:
        from atlas.commands.init import register_init_routes

        register_init_routes(app)
    except Exception:  # /init 模块缺失或注册失败只降级（lint: logger.exception）
        log.exception("C6 启动注册 /init 路由失败，/init 功能暂不可用")
        errors.append("/init route registration failed")
    try:
        from atlas.review.engine import register_review_tools

        register_review_tools()
    except Exception:  # review 模块缺失或注册失败只降级
        log.exception("C6 启动注册审查工具失败，/review 功能暂不可用")
        errors.append("/review tool registration failed")
    try:
        from atlas.review.engine import register_review_routes

        register_review_routes(app)
    except Exception:  # review 路由注册失败只降级
        log.exception("C6 启动注册 /review 路由失败，/review 功能暂不可用")
        errors.append("/review route registration failed")
    if errors:
        raise RuntimeError("; ".join(errors))
