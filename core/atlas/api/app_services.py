"""Per-application service composition root used by API dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AppServices:
    """Live service instances owned by one FastAPI application.

    These are references to the existing authorities, not new stores. The app
    factory fills the fields during construction/lifespan; request handlers
    receive this container from ``app.state`` through FastAPI dependency
    injection. Keeping the fields here makes cross-router wiring explicit and
    allows two app instances to run against isolated service graphs.
    """

    config: Any = None
    model_mgr: Any = None
    asr_manager: Any = None
    memory: Any = None
    orchestrator: Any = None
    mcp_client: Any = None
    local_execution: Any = None
    computer_use: Any = None
    skill_mgr: Any = None
    skill_registry: Any = None
    scheduler: Any = None
    capability_bus: Any = None
    cua_backend: Any = None
    browser_use: Any = None
    agent_backend_host: Any = None
    projects: Any = None
    durable: Any = None
    # RuntimeManager owns the websocket connections, active runs, replay/events,
    # and each RunState's pending approval/input futures and execution context.
    runtime_mgr: Any = None
    runtime_start_handler: Any = None
    runtime_resume_handler: Any = None
    rules_trust_handler: Any = None
    plugin_runtime: Any = None
    notifications: Any = None
    web_runtime: Any = None
    custom_tools: Any = None
    telegram_service: Any = None
    usage_ledger: Any = None
    channel_manager: Any = None
    gateway_bridge: Any = None
    heartbeat_service: Any = None
    sandbox_manager: Any = None
    skill_catalog_provider: Any = None
    persistent_agents: Any = None
    agent_conversation_lookup: Any = None
    agent_skill_collections: Any = None
    skill_proposals: Any = None
    vault_store_factory: Any = None
    device_registry: Any = None
    takeover: Any = None
    group_service: Any = None
    group_orchestrator: Any = None
    local_runtime_adapter: Any = None
    skills_market_supplier: Any = None
    # H8 S1/S2: per-component startup state (starting/ready/failed) reported by
    # /api/health and used by S3's bounded wait_ready gates on request paths.
    startup: Any = None
