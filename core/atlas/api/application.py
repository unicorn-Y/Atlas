"""FastAPI application construction and domain-router composition."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atlas.api.agent_backends_router import router as agent_backends_router
from atlas.api.agent_skills_router import router as agent_skills_router
from atlas.api.app_services import AppServices
from atlas.api.startup_components import StartupComponents
from atlas.api.automation_router import automation_router
from atlas.api.browser_router import router as browser_router
from atlas.api.channel_router import router as channel_router
from atlas.api.conversations_router import router as conversations_router
from atlas.api.conversation_activity_router import router as conversation_activity_router
from atlas.api.computer_router import router as computer_router
from atlas.api.device_router import router as device_router
from atlas.api.evolution_router import evolution_router
from atlas.api.upstream_router import upstream_router
from atlas.api.group_router import router as group_router
from atlas.api.skills_router import router as skills_router
from atlas.api.usage_router import router as usage_router
from atlas.api.u4_router import router as u4_router
from atlas.api.health_router import router as health_router
from atlas.api.integrations_router import router as integrations_router
from atlas.api.local_models_router import router as local_models_router
from atlas.api.memory_router import router as memory_router
from atlas.api.models_settings_router import router as models_settings_router
from atlas.api.plugins_router import router as plugins_router
from atlas.api.recipes_router import router as recipe_templates_router
from atlas.api.extension_packages_router import router as extension_packages_router
from atlas.api.settings_export_router import router as settings_export_router
from atlas.api.diagnostics_router import router as diagnostics_router
from atlas.api.external_history_router import router as external_history_router
from atlas.api.workspace_trust_settings_router import router as workspace_trust_settings_router
from atlas.api.run_limits_router import router as run_limits_router
from atlas.api.network_settings_router import router as network_settings_router
from atlas.api.hook_trust_router import router as hook_trust_router
from atlas.api.linear_integration_router import router as linear_integration_router
from atlas.api.mcp_resources_lazy_router import router as mcp_resources_router
from atlas.api.model_catalog_preferences_router import router as model_catalog_preferences_router
from atlas.api.output_style_settings_router import router as output_style_settings_router
from atlas.api.personal_todos_router import router as personal_todos_router
from atlas.api.projects_router import router as projects_router
from atlas.api.u6_router import router as u6_router
from atlas.api.ultraplan_router import router as ultraplan_router
from atlas.api.records_router import router as records_router
from atlas.api.runtime import RuntimeManager
from atlas.api.runtime_router import router as runtime_router
from atlas.api.runtime_ws_router import router as runtime_ws_router
from atlas.api.scheduling_router import router as scheduling_router
from atlas.api.skills_market_router import router as skills_market_router
from atlas.api.memory_library_router import router as memory_library_router
from atlas.api.workspace_router import router as workspace_router
from atlas.api.workbench_router import router as workbench_router
from atlas.api.library_router import router as library_router
from atlas.api.expert_mode_router import router as expert_mode_router
from atlas.api.config_editor_router import router as config_editor_router
from atlas.api.tools_router import router as tools_router
from atlas.config import get_config
from atlas.models.routes import models_router
from atlas.origin_guard import DEV_ORIGINS, OriginGuard


def create_app(
    *,
    lifespan: Callable[..., Any],
    services: AppServices,
) -> FastAPI:
    """Construct an app whose route dependencies resolve its own services."""
    app = FastAPI(title="Atlas", version="0.1.0", lifespan=lifespan)
    if services.runtime_mgr is None:
        services.runtime_mgr = RuntimeManager()
    if services.startup is None:
        # H8 S1: /api/health can always reach a component registry, even for
        # apps mounted without the server lifespan (no components → ok).
        services.startup = StartupComponents()
    app.state.services = services
    services.runtime_mgr.services = services
    origins = get_config().get("server.allowed_origins", [])
    configured_origins = [str(item) for item in origins] if isinstance(origins, list) else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[*sorted(DEV_ORIGINS), "null", *configured_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(OriginGuard, extra_origins=lambda: configured_origins)

    # Preserve registration order: literal skill routes must precede path params.
    for router in (
        models_router,
        agent_backends_router,
        computer_router,
        browser_router,
        skills_market_router,
        evolution_router,
        upstream_router,
        channel_router,
        automation_router,
        device_router,
        local_models_router,
        agent_skills_router,
        conversations_router,
        conversation_activity_router,
        group_router,
        health_router,
        integrations_router,
        memory_router,
        models_settings_router,
        plugins_router,
        recipe_templates_router,
        extension_packages_router,
        settings_export_router,
        diagnostics_router,
        external_history_router,
        workspace_trust_settings_router,
        run_limits_router,
        network_settings_router,
        hook_trust_router,
        linear_integration_router,
        mcp_resources_router,
        model_catalog_preferences_router,
        output_style_settings_router,
        personal_todos_router,
        projects_router,
        u6_router,
        records_router,
        skills_router,
        runtime_router,
        runtime_ws_router,
        scheduling_router,
        tools_router,
        usage_router,
        u4_router,
        workspace_router,
        workbench_router,
        library_router,
        expert_mode_router,
        config_editor_router,
        ultraplan_router,
    ):
        app.include_router(router)
    app.include_router(memory_library_router)
    return app
