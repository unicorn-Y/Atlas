"""Capability health surface: ``GET /api/capabilities``.

``/api/health`` answers "did startup finish?"; this endpoint answers "what can
Atlas actually do right now?". The report is computed on demand (or reused from
a short TTL cache) by ``atlas.capabilities.probes`` and lists every failing
capability with a remediation hint, so a broken integration is visible instead
of hiding behind a ``ready`` startup component.

Like every other router here, services come from ``app.state`` via FastAPI
dependency injection — never a module-level singleton.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.capabilities.probes import capabilities_report

router = APIRouter()


@router.get("/api/capabilities")
async def capabilities(
    services: Annotated[AppServices, Depends(get_app_services)],
    refresh: Annotated[bool, Query(description="Ignore the cached report and re-probe now.")] = False,
    recheck_model: Annotated[
        bool,
        Query(
            description=(
                "Also retest the chat model. Off by default because that spends a "
                "real (tiny) model request; omit it for ordinary refresh polling."
            )
        ),
    ] = False,
) -> dict[str, Any]:
    """Probe every registered capability and report the verdict.

    ``status`` is the overall verdict (``ok`` / ``degraded`` / ``unavailable``);
    ``failing`` repeats only the non-ok probes, each with a remediation hint, so
    the payload is readable without grouping client-side.

    ``refresh`` re-runs the local probes only. The chat model verdict is cached
    per model id for ten minutes so polling this endpoint never bills the user;
    pass ``recheck_model=true`` for an explicit "test my model" action.
    """
    return await capabilities_report(services, refresh=refresh, recheck_model=recheck_model)
