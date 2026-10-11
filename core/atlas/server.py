"""Atlas FastAPI + WebSocket server."""

from __future__ import annotations

import asyncio
import os
import subprocess  # noqa: F401 — compat: tests patch ``atlas.server.subprocess.run``
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import FastAPI

from atlas.agent.capabilities import (
    AgentCapabilityRegistry,
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
from atlas.api.deferred_startup import start_lifespan_components
from atlas.api.models_settings_router import (
    _model_supports_reasoning,  # noqa: F401,E402 — compat re-export
)
from atlas.api.runtime import (  # noqa: F401 — RunState re-exported for tests
    RunState,
    RuntimeManager,
)
from atlas.api.startup_components import COMPONENT_NAMES, StartupComponents
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
from atlas.memory.unified_facade import UnifiedMemoryFacade
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
from atlas.usage import UsageLedger

if TYPE_CHECKING:  # H8 O1/S2: annotations are strings (PEP 563); the heavy
    # mcp/tools modules are resolved lazily (_LAZY_TOOL_EXPORTS / module
    # __getattr__) so importing atlas.server — and therefore every cold start
    # — no longer pays the ~1.1 s mcp import chain on the critical path.
    from atlas.scheduler import AtlasScheduler
    from atlas.tools.computer_use import ComputerUseRuntime
    from atlas.tools.custom_tools import CustomToolStore
    from atlas.tools.local_execution import LocalExecutionRuntime
    from atlas.tools.mcp_client import MCPClient
    from atlas.tools.node_runtime import get_node_runtime_status  # noqa: F401
    from atlas.tools.web import WebRuntime

# PEP 562: keep the historical ``atlas.server.<name>`` surface resolvable
# (attribute access and ``from atlas.server import <name>``) without the
# eager imports. ``atlas.server.subprocess`` and the run-drive re-exports
# below are unaffected.
_LAZY_TOOL_EXPORTS = {
    "ComputerUseRuntime": "atlas.tools.computer_use",
    "CustomToolStore": "atlas.tools.custom_tools",
    "LocalExecutionRuntime": "atlas.tools.local_execution",
    "MCPClient": "atlas.tools.mcp_client",
    "WebRuntime": "atlas.tools.web",
    "extract_web": "atlas.tools.web_extract",
    "get_node_runtime_status": "atlas.tools.node_runtime",
}


def __getattr__(name: str):
    module_name = _LAZY_TOOL_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value  # cache: subsequent lookups skip the hook
    return value


class _DeferredMCPClient:
    """S2 stand-in for the real MCPClient while the deferred ``mcp``
    component starts. First attribute access binds (or re-binds — test
    patches of ``atlas.server.mcp_client`` keep working) the module-level
    client and forwards, so the critical-path consumers (capability lambdas,
    the orchestrator's tool bridge, /api/tools) behave exactly as with an
    un-started client: empty tool index until the component is ready (S3's
    documented degraded window)."""

    def __getattr__(self, name: str) -> Any:
        client = globals().get("mcp_client")
        if client is None or client is self:
            from atlas.tools.mcp_client import MCPClient

            client = MCPClient()
            globals()["mcp_client"] = client
        return getattr(client, name)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Singletons (populated by lifespan)
# ---------------------------------------------------------------------------

model_mgr: ModelManager | None = None
memory: MemoryStore | None = None
# T01.3：unified-memory facade（enabled=true 时由 lifespan 装配并挂到 services）。
unified_memory: UnifiedMemoryFacade | None = None
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
    """Startup / shutdown lifecycle.

    H8 §10.2 split (S1/S2): everything the first request needs — managers,
    small DB inits, runtime constructors, capability registration, the
    orchestrator, and all W10 service wiring — runs on the critical path
    before ``yield``. The expensive component *starts* (DBOS launch, MCP
    connect, skill scan, plugin load, engine registrations, channel start,
    automation, scheduler, telegram poll, /init + /review registration) run
    as one deferred task after ``yield``; per-component state lives on
    ``services.startup`` for /api/health (S4) and S3's bounded MCP gate.
    """
    from atlas.logs import configure_logging

    configure_logging(get_config())
    services = app.state.services
    manager = services.runtime_mgr
    global model_mgr, memory, orchestrator, mcp_client, local_execution, computer_use
    global skill_mgr, skill_registry, scheduler, usage_ledger
    global capability_bus, cua_backend, browser_use, agent_backend_host
    global projects, durable, plugin_runtime, notifications, web_runtime, custom_tools, telegram_service
    global unified_memory
    # W10 persistent-always-on singletons (module-level, reset per lifespan).
    global channel_manager, gateway_bridge, heartbeat_service

    # S1: fresh per-lifespan component registry (restarts must not inherit a
    # previous run's states); created before anything can mark.
    startup = StartupComponents()
    services.startup = startup
    for component_name in COMPONENT_NAMES:
        startup.mark(component_name, "starting")

    for resource_name in (
        "model_mgr", "memory", "unified_memory", "projects", "durable", "plugin_runtime", "notifications",
        "orchestrator", "mcp_client", "local_execution", "computer_use", "capability_bus",
        "cua_backend", "browser_use", "agent_backend_host", "web_runtime", "custom_tools",
        "telegram_service", "skill_mgr", "skill_registry", "scheduler", "usage_ledger",
        "channel_manager", "gateway_bridge", "heartbeat_service",
    ):
        globals()[resource_name] = None
    deferred_startup: asyncio.Task[None] | None = None
    capture_flush_task: asyncio.Task[None] | None = None
    capture_service = None
    observer_drain_task: asyncio.Task[None] | None = None
    observer_drain_requested = False
    memory_observer = None
    observer_drain = None
    memory_reflector = None
    reflector_idle_task: asyncio.Task[None] | None = None
    memoryos_lifecycle = None
    routes_before_lifespan_extensions = len(app.routes)
    startup_aborted = False
    cancelled = False
    try:
        model_mgr = ModelManager()
        # T01.3 全入口组成：unified-memory 开关（默认 false → facade=None，
        # MemoryStore 保持完整旧本地行为，全部旧测试不受影响）。
        unified_memory = (
            UnifiedMemoryFacade.from_config()
            if get_config().get("memory.unified.enabled") else None
        )
        if unified_memory is not None:
            from atlas.memory.service_lifecycle import MemoryOSServiceLifecycle

            memoryos_lifecycle = MemoryOSServiceLifecycle(get_config())
            unified_memory.bind_service_lifecycle(memoryos_lifecycle)
            startup.mark("memoryos", "starting")
        # T02.2：统一记忆真实捕获（对话/工具事件 → ObservationBuilder →
        # OperationalOutbox → 周期 flush）。capture_mode 缺省 enabled、可配置
        # 关闭；disabled（含 unified.enabled=false）时不建服务、不起循环，
        # 聊天/工具主流程零影响。
        if unified_memory is not None:
            from atlas.memory.capture import (
                capture_flush_loop,
                configure_capture_service,
            )

            capture_service = configure_capture_service(facade=unified_memory)
            if capture_service is not None:
                from atlas.memory.capture import register_observer_session_callback
                from atlas.memory.intent_bridge import IntentBridge
                from atlas.memory.observer import MemoryObserver
                from atlas.memory.observer_drain import MemoryObserverDrain

                memory_observer = MemoryObserver(
                    model_mgr, get_config(), outbox=capture_service._ensure_outbox(),
                )
                observer_drain = MemoryObserverDrain(
                    memory_observer, unified_memory,
                    # F3-B2：观察者产出带时间条件的 INTENT → 既有 AutomationEngine
                    # 真实建任务（桥未注入时 drain 行为与从前一致）。
                    intent_bridge=IntentBridge(
                        facade=unified_memory, config=get_config(),
                    ),
                    automation_engine=get_automation_engine(),
                )
                register_observer_session_callback(observer_drain.note_session_started)

                async def drain_observer_batches() -> None:
                    nonlocal observer_drain_requested
                    while True:
                        observer_drain_requested = False
                        await asyncio.sleep(0)
                        await observer_drain.drain_once()
                        if not observer_drain_requested:
                            return

                def schedule_observer_drain() -> None:
                    nonlocal observer_drain_task, observer_drain_requested
                    observer_drain_requested = True
                    if observer_drain_task is None or observer_drain_task.done():
                        observer_drain_task = asyncio.create_task(
                            drain_observer_batches(), name="unified-memory-observer-drain",
                        )

                capture_flush_task = asyncio.create_task(
                    capture_flush_loop(
                        capture_service, after_flush_tick=schedule_observer_drain,
                    ),
                    name="unified-capture-flush",
                )
                # F3-C：把 drain 与它的调度踢点登记给控制面，供
                # POST /api/unified-memory/session/close 触发「会话结束」批量冲刷。
                from atlas.memory.observer_drain import register_observer_drain

                register_observer_drain(observer_drain, schedule_observer_drain)
                from atlas.memory.reflector import (
                    MemoryReflector,
                    reflector_idle_loop,
                    set_memory_reflector,
                )

                memory_reflector = MemoryReflector(
                    model_mgr, get_config(), client=unified_memory,
                )
                set_memory_reflector(memory_reflector)
                reflector_idle_task = asyncio.create_task(
                    reflector_idle_loop(memory_reflector),
                    name="unified-memory-reflector-idle",
                )
        memory = MemoryStore(unified=unified_memory)
        await memory.init()
        usage_ledger = UsageLedger(get_config().db_path)
        await usage_ledger.init()
        projects = ProjectStore(get_config().db_path.parent / "projects.db")
        await projects.init()
        cfg = get_config()
        durable = DurableBackend(cfg.db_path.parent / "dbos.sqlite")
        durable.set_dispatcher(_durable_dispatcher, asyncio.get_running_loop())
        # S2.1/S5: durable.start() — the DBOS launch + system-DB migrations — is
        # the deferred ``dbos`` component; the lifespan continues meanwhile.

        # W6: pin HERMES_HOME before the hermes engine initializes — importing this
        # module pins the machine-level local-runtime home exactly once (setdefault).
        import atlas.engine.local_runtime_adapter  # noqa: F401  # W6 integration touchpoint

        await manager.init(cfg.db_path)

        # S2.2: the real MCPClient is constructed + started by the deferred ``mcp``
        # component (the heavy mcp import chain is paid after uvicorn binds). The
        # proxy keeps every existing consumer working in the meantime.
        mcp_client = _DeferredMCPClient()

        # S2: the runtime constructors stay on the critical path; only their
        # modules' imports are function-local so module import stays light.
        from atlas.tools.computer_use import ComputerUseRuntime
        from atlas.tools.custom_tools import CustomToolStore
        from atlas.tools.local_execution import LocalExecutionRuntime
        from atlas.tools.web import WebRuntime

        local_execution = LocalExecutionRuntime()
        cua_backend = CuaBackend()
        computer_use = ComputerUseRuntime(cua_backend=cua_backend)
        capability_bus = CapabilityBus(dict(cfg.raw.get("integrations", {})))
        browser_use = BrowserUseAdapter()
        agent_backend_host = AgentBackendHost()

        skill_mgr = SkillManager()
        # E2: feed the one shared skill index from every source. Hermes skills are
        # strictly opt-in via `extensions.hermes_skills` in atlas.toml; plugin skill
        # dirs join through _refresh_extension_sources once plugin_runtime exists.
        hermes_skills = cfg.get("extensions.hermes_skills")
        for source in default_skill_sources(
            workspace=_default_workspace(),
            hermes_skills_dir=(
                Path(str(hermes_skills).strip()) if isinstance(hermes_skills, str) and hermes_skills.strip() else None
            ),
        ):
            skill_mgr.register_skill_source(source)
        # S2.3: skill_mgr.scan_skills() is the deferred ``skills`` component; the
        # SkillManager object and its sources exist from here on.
        custom_tools = CustomToolStore(cfg.db_path.parent / "tools")
        skill_registry = SkillRegistry(cfg.db_path.parent / "skill-registry.db")
        _register_local_skills(skill_mgr, skill_registry)
        capabilities = AgentCapabilityRegistry()
        # S2.3: the per-skill capability loop (iterates skill_mgr.list_skills())
        # moved to the deferred ``skills`` component; the handlers below read the
        # manager/registry lazily and stay critical.
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
            # web_extractor omitted (H8): the orchestrator falls back to its lazy
            # _default_web_extractor(), so the web_extract import only happens on
            # first use instead of on the critical path.
        )

        plugin_runtime = PluginRuntime(
            [PROJECT_ROOT / "plugins", get_config().db_path.parent / "plugins"],
            get_config().db_path.parent / "plugins" / "state.json",
        )
        if orchestrator is not None:
            orchestrator._plugin_runtime = plugin_runtime
        # S2.4: plugin_runtime.load_all(...) + _refresh_extension_sources() are the
        # deferred ``plugins`` component (after the initial skill scan).

        # (S2.5) H3/H5 seam: the once-per-process engine registrations moved to the
        # deferred ``engine_registrations`` component.

        notifications = NotificationBus()

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
        # S2.7: the engine start + heartbeat reconcile are the deferred
        # ``automation`` component, gated on the ``dbos`` component (W10).

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

        # S2.8/S2.9/S2.6: scheduler start, the telegram fallback poll and
        # channel_manager.start() are deferred components.

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
        # (telegram_service.start() — the deferred ``telegram`` component.)

        # Keep request and WebSocket dependencies bound to this lifespan's service root.
        services.config = get_config()
        for service_name in (
            "model_mgr", "memory", "unified_memory", "orchestrator", "mcp_client", "local_execution",
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

        # S2: everything deferred starts from here — after uvicorn binds, so
        # /api/health answers while the components come up.
        deferred_startup, routes_before_lifespan_extensions = start_lifespan_components(
            app, services, startup,
        )

        yield  # app is running
    except BaseException:
        startup_aborted = True
        raise
    finally:
        if observer_drain is not None:
            try:
                observer_drain.end_active_session()
            except Exception as exc:  # noqa: BLE001 — report, then continue teardown
                log.exception("memory.observer_end_signal_failed", error=str(exc))
        try:
            from atlas.memory.capture import register_observer_session_callback

            register_observer_session_callback(None)
            from atlas.memory.observer_drain import register_observer_drain

            register_observer_drain(None)
        except Exception as exc:  # noqa: BLE001 — startup may have ended before capture setup
            log.debug("memory.observer_session_callbacks_reset_failed", error=str(exc),
                      exc_info=True)
        # T02.2：先停捕获 flush 循环并复位单例，避免跨 lifespan 残留旧服务。
        if capture_flush_task is not None:
            capture_flush_task.cancel()
            await asyncio.gather(capture_flush_task, return_exceptions=True)
        if capture_service is not None:
            try:
                await capture_service.flush()
            except Exception as exc:  # noqa: BLE001 — preserve outbox for next lifespan
                log.exception("memory.capture_shutdown_flush_failed", error=str(exc))
        if observer_drain is not None and observer_drain.end_sessions:
            try:
                # Session end is persisted before asking the model, so an offline
                # MemoryOS or a slow model leaves the source and flush request recoverable.
                schedule_observer_drain()
            except Exception as exc:  # noqa: BLE001 — no teardown is skipped
                log.exception("memory.observer_shutdown_schedule_failed", error=str(exc))
        if observer_drain_task is not None and not observer_drain_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(observer_drain_task), timeout=15.0)
            except TimeoutError:
                observer_drain_task.cancel()
                await asyncio.gather(observer_drain_task, return_exceptions=True)
                log.warning("memory.observer_shutdown_drain_timeout")
        if reflector_idle_task is not None:
            reflector_idle_task.cancel()
            await asyncio.gather(reflector_idle_task, return_exceptions=True)
        try:
            from atlas.memory.reflector import set_memory_reflector
            set_memory_reflector(None)
        except Exception as exc:
            log.debug("memory.reflector_reset_failed", error=str(exc), exc_info=True)
        try:
            from atlas.memory.capture import reset_capture_service

            reset_capture_service()
        except Exception:  # noqa: BLE001 — 关停清理不阻塞其余 teardown
            log.exception("unified.capture_reset_failed")
        if deferred_startup is not None:
            # Let deferred startup settle before reverse teardown; a stuck step is bounded.
            try:
                await asyncio.wait_for(deferred_startup, timeout=10.0)
            except TimeoutError:
                log.error("startup.deferred_shutdown_timeout")
                startup_aborted = True
            except asyncio.CancelledError:
                startup_aborted = True
                cancelled = bool(asyncio.current_task().cancelling())
                deferred_startup.cancel()
                await asyncio.gather(deferred_startup, return_exceptions=True)
            except Exception:  # noqa: BLE001 — a failed component must not block teardown
                log.exception("startup.deferred_shutdown_error")
        if (
            deferred_startup is not None
            and startup_aborted
            and startup.state("session_migration") == "starting"
        ):
            from atlas.config import DATA_ROOT
            from atlas.session_migration_gate import finish_session_migration

            finish_session_migration(DATA_ROOT / "engine", "failed")

        from atlas.api.deferred_startup import shutdown_lifespan_components

        try:
            await shutdown_lifespan_components(
                app, locals(), routes_before_lifespan_extensions,
            )
        finally:
            if memoryos_lifecycle is not None:
                try:
                    await memoryos_lifecycle.stop()
                except Exception:  # noqa: BLE001 — process cleanup must not skip service teardown
                    log.exception("memoryos.child_shutdown_failed")
            # Teardown hygiene: a stopped runtime must not keep advertising its
            # services. Leaving ``manager.services`` pointing at the closed stores
            # let late readers (and later TestClient lifespans in-process) consume
            # dead components silently instead of failing on the missing seam.
            manager.services = None
        if cancelled:
            raise asyncio.CancelledError


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
