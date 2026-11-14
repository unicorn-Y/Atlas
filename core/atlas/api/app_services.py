"""Per-application service composition root used by API dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atlas.session_projections import SessionProjections
from atlas.engine.kernel.tool_finalize import ToolResultFinalizers
from atlas.api.service_registry import ServiceRegistry
from atlas.runtime.commands import SlashCommandRegistry


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
    slash_command_registry: SlashCommandRegistry = field(default_factory=SlashCommandRegistry)
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
    cli_handoffs: Any = None
    office_pairing: Any = None
    office_sessions: Any = None
    office_handoffs: Any = None
    office_writebacks: Any = None
    office_live_sessions: Any = None
    # Registrable derived session views with event-driven invalidation. Default-
    # constructed so every AppServices — including test harnesses that build a bare
    # container — gets one, and two features describing the same session share it.
    session_projections: Any = field(default_factory=SessionProjections)
    # Ordered, disposable content transforms applied to a tool result just before
    # the model sees it. Default-constructed for the same reason as
    # ``session_projections``: a bare container must still give registrants a real
    # registry, and a runtime without one gets a fresh no-op registry in the loop.
    tool_result_finalizers: Any = field(default_factory=ToolResultFinalizers)
    # Ownership and reversibility for services. The fields above stay exactly as
    # they are — 73 call sites read them directly, and migrating that for no
    # user-visible gain would be churn. What this adds is what the dataclass
    # cannot express: which owner provided a service, and how to take it back.
    # ``bind_into`` projects a registered service onto its same-named field, so
    # the two views never diverge.
    service_registry: Any = field(default_factory=ServiceRegistry)

    # -- guarded accessors -------------------------------------------------
    # Every handler writes ``services.<field>.<method>``, and a field that is
    # still ``None`` turns that into ``AttributeError: 'NoneType' object has no
    # attribute ...`` — a 500 with a traceback that names the attribute but not
    # the missing service. These accessors make the same failure name the field
    # that was never wired, which is the fact the caller needs.
    #
    # They are deliberately few. Atlas keeps capability in the owning module and
    # uses this container as a composition root, so wrapping 638 domain methods
    # here would only add a second place to look for every behaviour.

    def require(self, name: str) -> Any:
        """The bound service, or a ``LookupError`` naming the unwired field.

        Use when the handler genuinely cannot proceed without the service::

            services.require("memory").recall(query)

        A ``LookupError`` rather than ``AttributeError`` so an API layer can map
        it to 503 ("not wired in this build") instead of 500 ("we have a bug").
        """
        if name not in type(self).__slots__:
            raise LookupError(f"AppServices 没有字段 {name!r}")
        value = getattr(self, name, None)
        if value is None:
            raise LookupError(f"服务 {name!r} 未接线（字段存在但为 None）")
        return value

    def has(self, name: str) -> bool:
        """True when ``name`` is a declared field and is currently bound."""
        return name in type(self).__slots__ and getattr(self, name, None) is not None

    def maybe(self, name: str) -> Any:
        """The bound service, or ``None``. For optional capabilities.

        The point is the field-existence check: ``services.maybe("typo")`` returns
        ``None`` either way, but :meth:`missing` can then report the typo, whereas
        a bare ``getattr(self, "typo", None)`` hides it forever.
        """
        if name not in type(self).__slots__:
            return None
        return getattr(self, name, None)

    def missing(self, *names: str) -> list[str]:
        """Which of ``names`` are undeclared, and which are declared but unbound.

        Returns the undeclared ones first: a typo is a different bug from an
        unwired dependency, and they are fixed in different places.
        """
        undeclared = [n for n in names if n not in type(self).__slots__]
        unbound = [n for n in names if n in type(self).__slots__ and getattr(self, n, None) is None]
        return undeclared + unbound

    def wired(self) -> dict[str, str]:
        """``{field: type name}`` for every bound service.

        The one-glance wiring report: what this application actually built.
        """
        return {
            name: type(getattr(self, name, None)).__name__
            for name in type(self).__slots__
            if getattr(self, name, None) is not None
        }

    def unwired(self) -> list[str]:
        """Every declared field that is still ``None``."""
        return [
            name for name in type(self).__slots__ if getattr(self, name, None) is None
        ]
