"""Atlas FastAPI + WebSocket server."""

from __future__ import annotations

import asyncio
import os
import subprocess  # noqa: F401 — compat: tests patch ``atlas.server.subprocess.run``
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI

from atlas.agent.capabilities import (
    AgentCapabilityRegistry,
    register_skill_capabilities,
    register_skill_catalog_capabilities,
    register_skill_dependency_capability,
    register_skill_discovery_capability,
)
from atlas.agent.checkpoints import ShadowGitCheckpointStore
from atlas.agent.enrichment import (
    AtlasToolBridge,
    CodeActRuntime,
    DelegationService,
    MemoryReflectionBridge,
)
from atlas.agent.orchestrator import AgentOrchestrator
from atlas.api.app_services import AppServices
from atlas.api.application import create_app
from atlas.api.models_settings_router import (
    _model_supports_reasoning,  # noqa: F401,E402 — compat re-export
)
from atlas.api.runtime import (  # noqa: F401 — RunState re-exported for tests
    RunState,
    RuntimeManager,
)
from atlas.api.tools_router import ws_terminal  # noqa: F401,E402 — compat re-export
from atlas.api.usage_router import runtime_protocol  # noqa: F401,E402 — compat re-export
from atlas.asr import ASRManager
from atlas.automation import (
    AutomationEngine,
    AutomationStore,
    get_automation_engine,
    set_automation_engine,
)
from atlas.capabilities.browser.browser_use import BrowserUseAdapter
from atlas.capabilities.coding import ast_grep as ast_grep_capability
from atlas.capabilities.coding.repo_map import repo_map
from atlas.capabilities.computer.cua_backend import CuaBackend
from atlas.capabilities.computer.uia_backend import list_windows as list_uia_windows
from atlas.capabilities.durable.dbos_backend import DurableBackend
from atlas.capabilities.durable.dbos_backend import status as dbos_status
from atlas.channels import ChannelManager
from atlas.channels.adapters import register_builtin_channels
from atlas.config import (  # noqa: F401 — load/save stay the patch seams tests bind on this module
    get_config,
    load_user_settings,
    save_user_settings,
)
from atlas.devices import DeviceRegistry
from atlas.devices.takeover import TakeoverStateMachine
from atlas.gateway_service import GatewayBridge
from atlas.groups import GroupOrchestrator
from atlas.groups.store import GroupService, GroupStore
from atlas.heartbeat import HeartbeatService
from atlas.memory.store import MemoryStore
from atlas.models.manager import ModelManager
from atlas.notifications import NotificationBus
from atlas.persistent_agents import PersistentAgentService
from atlas.plugins import PluginRuntime
from atlas.projects import ProjectStore
from atlas.runtime.backend_host import AgentBackendHost
from atlas.runtime.capability_bus import CapabilityBus
from atlas.runtime.external_agents import (
    external_agent_status,  # noqa: F401 — read/patched via atlas.server
)
from atlas.sandbox import DockerSandboxManager
from atlas.scheduler import AtlasScheduler
from atlas.skills import (
    PROJECT_ROOT,
    SKILLS_DIR,
    SkillManager,
    default_skill_sources,
)
from atlas.skills.acquisition import (
    SkillsShProvider,
    install_acquisition,  # noqa: F401 — patched via atlas.server
)
from atlas.skills.bundles import PluginBundleDiscovery
from atlas.skills.lifecycle import (
    update_skill as update_lifecycle_skill,  # noqa: F401 — patched via atlas.server
)
from atlas.skills.registry import SkillRegistry
from atlas.ssh import ssh_workspaces
from atlas.telegram import TelegramService
from atlas.tools.computer_use import ComputerUseRuntime
from atlas.tools.custom_tools import CustomToolStore
from atlas.tools.local_execution import LocalExecutionRuntime
from atlas.tools.mcp_client import MCPClient
from atlas.tools.node_runtime import get_node_runtime_status  # noqa: F401 — read via atlas.server
from atlas.tools.web import WebRuntime
from atlas.tools.web_extract import extract_web
from atlas.usage import UsageLedger

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Singletons (populated by lifespan)
# ---------------------------------------------------------------------------

model_mgr: ModelManager | None = None
memory: MemoryStore | None = None
projects: ProjectStore | None = None
durable: DurableBackend | None = None
plugin_runtime: PluginRuntime | None = None
notifications: NotificationBus | None = None
orchestrator: AgentOrchestrator | None = None
mcp_client: MCPClient | None = None
local_execution: LocalExecutionRuntime | None = None
sandbox_manager = DockerSandboxManager()
computer_use: ComputerUseRuntime | None = None
capability_bus: CapabilityBus | None = None
cua_backend: CuaBackend | None = None
browser_use: BrowserUseAdapter | None = None
agent_backend_host: AgentBackendHost | None = None
web_runtime: WebRuntime | None = None
custom_tools: CustomToolStore | None = None
telegram_service: TelegramService | None = None
skill_mgr: SkillManager | None = None
skill_registry: SkillRegistry | None = None
skill_catalog_provider = SkillsShProvider()
SKILL_ACQUISITION_TTL = timedelta(minutes=10)
SKILL_CENTER_TOKEN = os.environ.get("ATLAS_SKILL_CENTER_TOKEN")
skill_acquisitions: dict[str, dict[str, Any]] = {}
skill_dependency_plans: dict[str, dict[str, Any]] = {}
scheduler: AtlasScheduler | None = None
external_agent_status_cache: dict[str, Any] = {}
external_conversation_sessions: dict[tuple[str, str], str] = {}
usage_ledger: UsageLedger | None = None
asr_manager: ASRManager | None = None
# W10 persistent-always-on singletons (populated by lifespan).
channel_manager: ChannelManager | None = None
gateway_bridge: GatewayBridge | None = None
heartbeat_service: HeartbeatService | None = None


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    services = app.state.services
    manager = services.runtime_mgr
    global model_mgr, memory, orchestrator, mcp_client, local_execution, computer_use
    global skill_mgr, skill_registry, scheduler
    global capability_bus, cua_backend, browser_use, agent_backend_host
    global projects, durable, plugin_runtime, notifications, web_runtime, custom_tools, telegram_service
    global usage_ledger
    # W10 persistent-always-on singletons (module-level, reset per lifespan).
    global channel_manager, gateway_bridge, heartbeat_service

    model_mgr = ModelManager()
    memory = MemoryStore()
    await memory.init()
    usage_ledger = UsageLedger(get_config().db_path)
    await usage_ledger.init()
    projects = ProjectStore(get_config().db_path.parent / "projects.db")
    await projects.init()
    durable = DurableBackend(get_config().db_path.parent / "dbos.sqlite")
    durable.set_dispatcher(_durable_dispatcher, asyncio.get_running_loop())
    durable.start()
    # W10: durable.start() constructed + launched the process-global DBOS
    # singleton; the automation engine reuses that same instance (never a second
    # DBOS per process). NOTE: _dbos_global_instance lives on the dbos._dbos
    # MODULE, not on the DBOS class — a class-level getattr always misses.
    from dbos import _dbos as _dbos_module

    dbos_instance = getattr(_dbos_module, "_dbos_global_instance", None)

    # W6: pin HERMES_HOME before the hermes engine initializes — importing this
    # module pins the machine-level local-runtime home exactly once (setdefault).
    import atlas.engine.local_runtime_adapter  # noqa: F401  # W6 integration touchpoint

    await manager.init(get_config().db_path)

    mcp_client = MCPClient()
    await mcp_client.start()
    local_execution = LocalExecutionRuntime()
    cua_backend = CuaBackend()
    computer_use = ComputerUseRuntime(cua_backend=cua_backend)
    capability_bus = CapabilityBus(dict(get_config().raw.get("integrations", {})))
    browser_use = BrowserUseAdapter()
    agent_backend_host = AgentBackendHost()

    skill_mgr = SkillManager()
    cfg = get_config()
    # E2: feed the one shared skill index from every source. Hermes skills are
    # strictly opt-in via `extensions.hermes_skills = "<hermes skills dir>"` in
    # atlas.toml; plugin skill dirs join through _refresh_extension_sources
    # once plugin_runtime exists below.
    hermes_skills = cfg.get("extensions.hermes_skills")
    for source in default_skill_sources(
        workspace=_default_workspace(),
        hermes_skills_dir=(
            Path(str(hermes_skills).strip()) if isinstance(hermes_skills, str) and hermes_skills.strip() else None
        ),
    ):
        skill_mgr.register_skill_source(source)
    await skill_mgr.scan_skills()
    custom_tools = CustomToolStore(cfg.db_path.parent / "tools")
    skill_registry = SkillRegistry(cfg.db_path.parent / "skill-registry.db")
    _register_local_skills(skill_mgr, skill_registry)
    capabilities = AgentCapabilityRegistry()
    register_skill_capabilities(capabilities, skill_mgr, skill_registry, mcp_client)
    register_skill_dependency_capability(capabilities, skill_mgr, skill_registry, mcp_client)
    register_skill_discovery_capability(capabilities, skill_registry)
    register_skill_catalog_capabilities(capabilities, skill_catalog_provider, skill_registry)
    checkpoints = ShadowGitCheckpointStore(cfg.db_path.parent / "checkpoints")
    bundles = PluginBundleDiscovery()
    capabilities.register(
        "local.full_access",
        description="Canonical P18A local execution tools (PowerShell, process, files, Git).",
        handler=lambda _inputs: local_execution.get_tools_for_llm(),
        source="atlas-p18a",
    )
    capabilities.register(
        "computer.cua.status", description="Connect to Cua Driver and return runtime metadata.",
        handler=lambda _inputs: cua_backend.connect(), source="trycua/cua",
    )
    capabilities.register(
        "computer.cua.tools", description="List installed Cua Driver computer tools.",
        handler=lambda _inputs: cua_backend.tools(), source="trycua/cua",
    )
    capabilities.register(
        "computer.cua.call", description="Call a Cua Driver computer tool by name.",
        handler=lambda inputs: cua_backend.call(
            str(inputs["name"]), dict(inputs.get("arguments", {})),
        ), source="trycua/cua",
    )
    capabilities.register(
        "computer.pywinauto.windows", description="List visible Windows UIA windows.",
        handler=lambda _inputs: list_uia_windows(), source="pywinauto",
    )
    capabilities.register(
        "browser.use.open", description="Open a URL in Browser Use and return page state.",
        handler=lambda inputs: browser_use.open(
            str(inputs["url"]), cdp_url=inputs.get("cdp_url"),
        ), source="browser-use/browser-use",
    )
    capabilities.register(
        "browser.use.task", description="Run a Browser Use Agent task against a web page.",
        handler=lambda inputs: browser_use.task(
            str(inputs["goal"]),
            start_url=inputs.get("start_url"),
            model=inputs.get("model"),
            session_options=dict(inputs.get("session_options", {})),
        ), source="browser-use/browser-use",
    )
    capabilities.register(
        "coding.ast_grep.run", description="Run ast-grep against a repository path.",
        handler=lambda inputs: ast_grep_capability.run(
            list(inputs.get("arguments", [])), cwd=str(inputs["cwd"]),
        ), source="ast-grep/ast-grep",
    )
    capabilities.register(
        "coding.repo_map", description="Generate an Aider repository map.",
        handler=lambda inputs: repo_map(str(inputs["path"]), int(inputs.get("budget", 1024))),
        source="Aider-AI/aider",
    )
    capabilities.register(
        "durable.dbos.status", description="Report DBOS installation and database readiness.",
        handler=lambda _inputs: dbos_status(), source="dbos-inc/dbos-transact-py",
    )
    web_runtime = WebRuntime()
    capabilities.register(
        "web.search",
        description="Search the public web (DuckDuckGo) and return result links.",
        handler=lambda inputs: web_runtime.web_search(
            str(inputs.get("query", "")), int(inputs.get("max_results", 5)),
        ),
        source="duckduckgo/html",
    )
    capabilities.register(
        "web.fetch",
        description="Download a web page and return readable text.",
        handler=lambda inputs: web_runtime.web_fetch(
            str(inputs.get("url", "")), int(inputs.get("max_chars", 8000)),
        ),
        source="duckduckgo/html",
    )
    capabilities.register(
        "notifications.send",
        description="Send a user notification through the configured Apprise targets.",
        handler=lambda inputs: notifications.notify(
            str(inputs.get("title", "Atlas")), str(inputs.get("body", "")),
        ),
        source="caronc/apprise",
    )
    capabilities.register(
        "durable.agent_task.run",
        description="Run one agent task as a DBOS durable workflow (crash-resumable).",
        handler=lambda inputs: durable.run_agent_task({
            "task_id": str(inputs.get("task_id", "adhoc")),
            "message": str(inputs.get("message", "")),
        }),
        source="dbos-inc/dbos-transact-py",
    )
    capabilities.register(
        "memory.session_search",
        description="Search past conversation messages (raw history) with surrounding context.",
        handler=lambda inputs: memory.session_search(
            str(inputs.get("query", "")),
            limit=int(inputs.get("limit", 8)),
            context=int(inputs.get("context", 2)),
        ),
        source="atlas-memory",
    )
    capabilities.register(
        "agent.execute_code",
        description="Run a bounded Python workflow through the shared Atlas tool bridge.",
        handler=lambda inputs: CodeActRuntime(
            AtlasToolBridge(local_execution, computer_use, mcp_client, checkpoints),
        ).execute(str(inputs["code"])),
        source="Hermes execute_code pattern",
    )
    capabilities.register(
        "agent.compact_context",
        description="Snapshot resume-critical task context before compaction.",
        handler=lambda inputs: orchestrator.context_maintenance.compact(inputs),
        source="Codex/OpenCode context maintenance",
    )
    capabilities.register(
        "agent.compaction.should_trigger",
        description="Return whether a session has reached its configured compaction threshold.",
        handler=lambda inputs: {
            "should_compact": orchestrator.context_maintenance.should_compact(
                list(inputs.get("messages", [])),
                message_limit=int(inputs.get("message_limit", 80)),
                character_limit=int(inputs.get("character_limit", 80_000)),
            ),
        },
        source="Codex/OpenCode context maintenance",
    )
    capabilities.register(
        "agent.memory.reflect",
        description="Propose task learning through the governed MemoryOS candidate path.",
        handler=lambda inputs: MemoryReflectionBridge(memory).reflect(
            conversation_id=str(inputs.get("conversation_id", "")),
            goal=str(inputs["goal"]), task_result=str(inputs["task_result"]),
            reviewer_evidence=list(inputs.get("reviewer_evidence", [])),
        ),
        source="Letta/Hermes reflection pattern",
    )
    capabilities.register(
        "workspace.checkpoint.create",
        description="Snapshot explicitly scoped workspace paths outside the repository.",
        handler=lambda inputs: checkpoints.create_checkpoint(
            str(inputs["workspace"]), list(inputs["paths"]),
        ),
        source="google-gemini/gemini-cli",
    )
    capabilities.register(
        "workspace.checkpoint.list",
        description="List Atlas shadow checkpoints, optionally for one workspace.",
        handler=lambda inputs: checkpoints.list_checkpoints(inputs.get("workspace")),
        source="google-gemini/gemini-cli",
    )
    capabilities.register(
        "workspace.checkpoint.restore",
        description="Restore the scoped paths in an Atlas shadow checkpoint.",
        handler=lambda inputs: checkpoints.restore_checkpoint(str(inputs["checkpoint_id"])),
        source="google-gemini/gemini-cli",
    )
    capabilities.register(
        "plugin.bundle.discover",
        description="Discover normalized plugin bundle declarations and plain Atlas Skills.",
        handler=lambda _inputs: bundles.discover([SKILLS_DIR], skill_mgr.list_skills()),
        source="ZCode/Gemini plugin manifest pattern",
    )
    if agent_backend_host:
        capabilities.register(
            "agent.delegate_task",
            description="Delegate one bounded investigation to a disposable Agent session.",
            handler=lambda inputs: DelegationService(
                agent_backend_host, orchestrator.hooks,
            ).delegate_task(
                str(inputs["goal"]), inputs.get("context"), inputs.get("tool_profile"),
            ),
            source="Claude/Hermes disposable delegation pattern",
        )

    orchestrator = AgentOrchestrator(
        model_mgr=model_mgr, memory=memory, mcp_client=mcp_client,
        capability_registry=capabilities,
        local_execution=local_execution,
        computer_use=computer_use,
        agent_backend_host=agent_backend_host,
        web_runtime=web_runtime,
        skill_manager=skill_mgr,
        projects=projects,
        # One store: the Agent's automatic snapshots must be the ones restore and diff read.
        checkpoint_store=checkpoints,
        custom_tools=custom_tools,
        web_extractor=extract_web,
    )

    plugin_runtime = PluginRuntime(
        [PROJECT_ROOT / "plugins", get_config().db_path.parent / "plugins"],
        get_config().db_path.parent / "plugins" / "state.json",
    )
    plugin_load_report = await plugin_runtime.load_all(
        hook_bus=orchestrator.hooks,
        mcp_client=mcp_client,
        capabilities=capabilities,
    )
    _refresh_extension_sources()

    # H3/H5 seam: run the once-per-process registrations (Atlas policy plugin +
    # Hermes MCP servers) at startup so the first user turn does not pay for
    # them. Idempotent and fingerprint-checked; a failure only means the first
    # turn re-runs the registration, so it must never break startup.
    try:
        from atlas.config import DATA_ROOT
        from atlas.engine import HermesRuntime

        HermesRuntime(data_dir=DATA_ROOT, model_manager=model_mgr).startup_registrations()
    except Exception:  # noqa: BLE001 — degraded to a warning; first turn retries
        log.exception("engine.startup_registrations_failed")

    notifications = NotificationBus()
    if plugin_load_report.get("errors"):
        log.warning("plugins.load_errors", errors=plugin_load_report["errors"])

    # -- W10 persistent-always-on wiring (agents / channels / heartbeat / automation) --
    agents_service = PersistentAgentService()
    from atlas.api.agent_router import set_agent_service, set_conversation_lookup

    set_agent_service(agents_service)
    set_conversation_lookup(_conversation_summary)
    app.state.services.persistent_agents = agents_service
    app.state.services.agent_conversation_lookup = _conversation_summary

    channel_manager = ChannelManager(
        db_path=cfg.db_path.parent / "channels.sqlite",
        config_path=cfg.db_path.parent / "channel-configs.json",
    )
    register_builtin_channels(channel_manager.register_channel)
    channel_workspace = _default_workspace()

    async def submit_channel_run(conn_id: str, data: dict[str, Any]) -> None:
        await _handle_run_start(conn_id, data, manager)

    async def channel_recovery_notice(run_id: str, message: str) -> None:
        run = manager.runs.get(run_id)
        if run is None:
            return
        env = run.next_envelope("run.recovery.notice", {"message": message})
        await manager.send_run(run, env, "channel")

    gateway_bridge = GatewayBridge(
        manager=channel_manager,
        db_path=cfg.db_path.parent / "channels.sqlite",
        submit_run=submit_channel_run,
        get_run=manager.runs.get,
        recovery_notice=channel_recovery_notice,
        read_answer=_read_conversation_answer,
        create_conversation=_create_channel_conversation,
        default_workspace=str(channel_workspace) if channel_workspace else None,
        set_agent_status=_set_agent_status_quiet,
        # H7 §9.1/§9.2: the configured defaults and the per-agent profile rung
        # of the permission ladder finally reach production wiring.
        default_permission_mode=get_config().gateway_default_permission_mode,
        approval_timeout_seconds=get_config().gateway_approval_timeout_seconds,
        get_agent=_channel_agent_profile,
    )
    channel_manager.set_dispatcher(gateway_bridge.dispatch)
    _sync_channel_routing(agents_service, channel_manager)
    from atlas.api.channel_router import set_channel_manager

    set_channel_manager(channel_manager)

    heartbeat_service = HeartbeatService(_AtlasHeartbeatHost(), root=cfg.db_path.parent / "heartbeat")

    # W8 group chat: singletons bound in order (service → orchestrator). The real
    # dispatcher drives member turns through the same engine seam as
    # heartbeat/automation — never a second agent core. Room log + watermarks
    # live under data/groups/<group_id>/ (the orchestrator's store.root).
    group_service = GroupService(GroupStore(cfg.db_path.parent), lookup=agents_service)
    group_orchestrator = GroupOrchestrator(
        group_service, dispatcher=_dispatch_group_member_turn,
    )
    from atlas.api.group_router import set_group_orchestrator, set_group_service

    set_group_service(group_service)
    set_group_orchestrator(group_orchestrator)

    automation_engine = AutomationEngine(
        AutomationStore(cfg.db_path.parent / "automations.toml"),
        heartbeat_tick=_automation_heartbeat_tick,
        dispatch_turn=_automation_dispatch_turn,
        deliver=_automation_deliver,
    )
    set_automation_engine(automation_engine)
    if dbos_instance is not None:
        await automation_engine.start_async(dbos_instance)
        await _reconcile_agent_heartbeats(agents_service, automation_engine)
    else:
        # durable.start() failed: automation CRUD keeps working (store only),
        # but triggers/runs report 503 until the next restart.
        log.warning("automation.engine_not_started", reason="dbos_instance_unavailable")

    from atlas.api import agent_skills_router, device_router, local_models_router
    from atlas.engine.local_runtime_adapter import LocalRuntimeAdapter
    from atlas.skills.agent_collections import AgentSkillCollections
    from atlas.skills.proposals import SkillProposalStore

    local_models_router.set_adapter(LocalRuntimeAdapter(cfg.get("local_runtime", {})))
    device_registry = DeviceRegistry(cfg.db_path.parent / "devices" / "devices.json")
    device_registry.register_self()
    takeover_machine = TakeoverStateMachine()
    # Legacy singletons stay queryable for standalone mounts; the app's own
    # request handlers read the same instances through app.state services.
    device_router.set_registry(device_registry)
    device_router.set_takeover(takeover_machine)
    services.device_registry = device_registry
    services.takeover = takeover_machine
    agent_skills_router.set_collections(AgentSkillCollections(skill_registry))
    # The proposal apply path writes skill payloads through the ONE market save
    # path (register_local + rescan) — without it approve() reports 503 market_unwired.
    from atlas.api.skills_market_router import get_market

    agent_skills_router.set_proposals(SkillProposalStore(
        skill_registry, market=get_market(),
        collections=agent_skills_router.get_collections(),
    ))
    # -- end W10 wiring --

    if cfg.scheduler_enabled:
        scheduler = AtlasScheduler(agent_callback=_scheduled_goal)
        await scheduler.start()

    # DEPRECATED (W10): the legacy TelegramService polling loop is retired in
    # favour of the channel gateway's telegram adapter (atlas.channels.adapters
    # .telegram + ChannelManager + gateway bridge). The service object stays —
    # /api/telegram settings/test_token and run approval keyboards depend on it —
    # but its getUpdates poll only starts when the gateway's telegram channel is
    # NOT enabled, so the two stacks never double-poll the same bot token.
    telegram_service = TelegramService(
        cfg.db_path.parent / "telegram.json",
        owns_lease=_owns_scheduler_lease,
        submit_task=_telegram_submit_task,
        command_handler=_telegram_command,
    )
    if not (channel_manager.configs.get("telegram") or {}).get("enabled"):
        telegram_service.start()

    await channel_manager.start()

    # C6:注册 /init 与 /review 的路由和工具。这些模块由独立子模块提供,可能晚于
    # 服务启动落地——注册失败只降级告警,绝不能拖垮 Atlas 本体启动。
    try:
        from atlas.commands.init import register_init_routes

        register_init_routes(app)
    except Exception as exc:  # noqa: BLE001 — /init 模块缺失或注册失败只降级
        log.warning("C6 启动注册 /init 路由失败，/init 功能暂不可用", error=str(exc))
    try:
        from atlas.review.engine import register_review_tools

        register_review_tools()
    except Exception as exc:  # noqa: BLE001 — review 模块缺失或注册失败只降级
        log.warning("C6 启动注册审查工具失败，/review 功能暂不可用", error=str(exc))
    try:
        from atlas.review.engine import register_review_routes

        register_review_routes(app)
    except Exception as exc:  # noqa: BLE001 — review 路由注册失败只降级
        log.warning("C6 启动注册 /review 路由失败，/review 功能暂不可用", error=str(exc))

    # Keep request and WebSocket dependencies bound to this lifespan's service root.
    services.config = get_config()
    for service_name in (
        "model_mgr", "memory", "orchestrator", "mcp_client", "local_execution",
        "computer_use", "skill_mgr", "skill_registry", "scheduler", "capability_bus",
        "cua_backend", "browser_use", "agent_backend_host", "projects", "durable",
        "plugin_runtime", "notifications", "web_runtime", "custom_tools",
        "telegram_service", "usage_ledger", "channel_manager", "gateway_bridge",
        "heartbeat_service",
    ):
        setattr(services, service_name, globals().get(service_name))
    # persistent_agents / group_service / group_orchestrator live only as
    # lifespan locals — the globals sweep above can never see them, so bind
    # them explicitly (globals().get() would clobber them back to None).
    services.persistent_agents = agents_service
    services.agent_conversation_lookup = _conversation_summary
    services.group_service = group_service
    services.group_orchestrator = group_orchestrator
    manager.services = services

    yield  # app is running

    # Shutdown
    if telegram_service:
        await telegram_service.stop()
    if scheduler:
        await scheduler.stop()
    # W10 reverse order: gateway → automation engine → heartbeat, all before
    # durable.stop() (the engine owns DBOS objects, not the DBOS instance).
    if channel_manager is not None:
        await channel_manager.stop()
        channel_manager.close()
    if gateway_bridge is not None:
        gateway_bridge.sessions.close()
    automation_engine = get_automation_engine()
    if automation_engine is not None:
        automation_engine.shutdown()
    if heartbeat_service is not None:
        await heartbeat_service.aclose()
    # W8 group chat singletons: reset so a stale orchestrator (and its bound
    # dispatcher over this lifespan's services) never leaks into a restart.
    from atlas.api import group_router as _group_router

    _group_router.set_group_orchestrator(None)
    _group_router.set_group_service(None)
    if mcp_client:
        await mcp_client.stop()
    if local_execution:
        await local_execution.shutdown()
    if computer_use:
        await computer_use.shutdown()
    # X2 bridges: cancel pending human cards + release Hermes desktop/browser sessions.
    from atlas.tools.x2 import browser as x2browser
    from atlas.tools.x2 import computer as x2computer

    await x2computer.shutdown()
    await x2browser.shutdown()
    if cua_backend:
        await cua_backend.close()
    if browser_use:
        for session_id in list(browser_use._sessions):
            await browser_use.close(session_id)
    await ssh_workspaces.close()
    if agent_backend_host:
        await agent_backend_host.shutdown()
    if durable:
        durable.stop()
    if projects:
        await projects.close()
    if usage_ledger:
        await usage_ledger.close()
    if memory:
        await memory.close()
    await manager.close()


# ---------------------------------------------------------------------------
# App factory and lifecycle-owned service root
# ---------------------------------------------------------------------------

runtime_mgr = RuntimeManager()
app = create_app(lifespan=lifespan, services=AppServices(runtime_mgr=runtime_mgr))


_WORKSPACE_IGNORES = {".git", "node_modules", ".venv", "__pycache__", ".atlas-checkpoints"}
_RULE_FILES = ("AGENTS.md", "CLAUDE.md", ".atlas/rules.md", ".atlas/NOTES.md")
_LOADED_RULE_WORKSPACES: set[str] = set()


# W10: agent_router must mount AFTER the literal /api/agents/... routes above
# (/api/agents/external, /api/agents/types): its GET /api/agents/{agent_id}
# would otherwise shadow them, because FastAPI matches routes in registration
# order and the mount block above runs before those literals are declared.
from atlas.api.agent_router import router as agent_router  # noqa: E402

app.include_router(agent_router)

# H5 A9: the run-drive / W10 service glue (run start/resume/trust handlers, the
# _execute_run drive loop, scheduler-goal / telegram / heartbeat / automation /
# group callbacks) now lives in atlas.api.run_drive. Re-export every name here so
# existing ``from atlas.server import X`` imports — and the monkeypatch seams on
# this module's namespace that tests rely on — keep working unchanged.
from atlas.api.run_drive import (  # noqa: E402, I001 — packed to keep this module inside the A9 line budget
    _agent_service, _AtlasHeartbeatHost, _automation_deliver,
    _automation_dispatch_turn, _automation_heartbeat_tick, _bounded_project_notes,
    _channel_agent_profile, _collect_orchestrator_text, _context_file_block,
    _conversation_summary, _create_channel_conversation, _default_workspace,
    _deliver_agent_notification, _dispatch_group_member_turn, _durable_dispatcher,
    _ensure_goal_migrated, _execute_after_rule_trust, _execute_external_agent,
    _execute_run, _goal_session_id, _handle_resume, _handle_rules_trust,
    _handle_run_start, _heartbeat_automation_current, _hook_store, _kanban_store,
    _map_tool_runtime_event, _merge_agent_collection_skills, _owns_scheduler_lease,
    _persist_hermes_goal_outcome, _plan_mode_tools, _plugin_agent_dirs,
    _plugin_command_sources, _plugin_contributions, _plugin_hooks,
    _plugin_skill_sources, _profile_store, _project_agent_run_status,
    _queue_run_steer, _read_conversation_answer, _reconcile_agent_heartbeats,
    _record_goal_failure, _refresh_extension_sources, _register_local_skills,
    _reload_extensions, _require_skill_center_authority,
    _resolve_active_skill_instructions, _resolve_agent_for_run,
    _resolve_group_member_conversation, _run_change_summary, _run_changes,
    _run_scheduled_goal, _scheduled_goal, _set_agent_status_quiet,
    _set_workspace_trusted, _start_group_turn_run, _sum_usage, _sync_channel_routing,
    _task_store, _telegram_command, _telegram_submit_task,
    _validated_file_attachments, _validated_image_attachments, _workspace_path,
    _workspace_trust, _workspace_trust_path, _worktrees, cancel_subtask
)

# Explicit re-export surface: everything the run-drive glue exposes through this
# module for backwards compatibility (tests import/patch these on atlas.server).
__all__ = [
    "_agent_service", "_AtlasHeartbeatHost", "_automation_deliver",
    "_automation_dispatch_turn", "_automation_heartbeat_tick",
    "_bounded_project_notes", "_channel_agent_profile", "_collect_orchestrator_text",
    "_context_file_block", "_conversation_summary", "_create_channel_conversation",
    "_default_workspace", "_deliver_agent_notification",
    "_dispatch_group_member_turn", "_durable_dispatcher", "_ensure_goal_migrated",
    "_execute_after_rule_trust", "_execute_external_agent", "_execute_run",
    "_goal_session_id", "_handle_resume", "_handle_rules_trust", "_handle_run_start",
    "_heartbeat_automation_current", "_hook_store", "_kanban_store",
    "_map_tool_runtime_event", "_merge_agent_collection_skills",
    "_model_supports_reasoning", "_owns_scheduler_lease",
    "_persist_hermes_goal_outcome", "_plan_mode_tools", "_plugin_agent_dirs",
    "_plugin_command_sources", "_plugin_contributions", "_plugin_hooks",
    "_plugin_skill_sources", "_profile_store", "_project_agent_run_status",
    "_queue_run_steer", "_read_conversation_answer", "_reconcile_agent_heartbeats",
    "_record_goal_failure", "_refresh_extension_sources", "_register_local_skills",
    "_reload_extensions", "_require_skill_center_authority",
    "_resolve_active_skill_instructions", "_resolve_agent_for_run",
    "_resolve_group_member_conversation", "_run_change_summary", "_run_changes",
    "_run_scheduled_goal", "_scheduled_goal", "_set_agent_status_quiet",
    "_set_workspace_trusted", "_start_group_turn_run", "_sum_usage",
    "_sync_channel_routing", "_task_store", "_telegram_command",
    "_telegram_submit_task", "_validated_file_attachments",
    "_validated_image_attachments", "_workspace_path", "_workspace_trust",
    "_workspace_trust_path", "_worktrees", "RunState", "RuntimeManager",
    "cancel_subtask", "external_agent_status", "get_node_runtime_status",
    "install_acquisition", "load_user_settings", "runtime_protocol",
    "save_user_settings", "subprocess", "ssh_workspaces", "update_lifecycle_skill",
    "ws_terminal",
]

app.state.services.runtime_start_handler = _handle_run_start
app.state.services.runtime_resume_handler = _handle_resume
app.state.services.rules_trust_handler = _handle_rules_trust
