"""Self-introspection surface: ``/api/introspect/*``.

Atlas is a 600-file Python backend with 767 routes, a tool registry whose contents
depend on what plugins loaded and which environment variables are set, and a
configuration file that mixes defaults with live secrets. Every one of those facts
is knowable only from inside the running process, and until now the only way to
get at them was to read source and guess.

These endpoints expose that knowledge as read-only queries. They are the same
shape as the harness-style Inspect Providers this project is measured against:

* ``GET  /api/introspect/providers``          — manifest of every provider
* ``GET  /api/introspect/providers/{id}``     — manifest of one provider
* ``POST /api/introspect/query``              — run one method

Contract, all three endpoints: nothing is written, no model is called unless a
method explicitly says so, and every configuration string passes through
``atlas.secrets_store.redact`` before it leaves the process.

Errors are answers here. An unknown provider or a bad argument is a 400/404 with
the available options named, because the caller is usually a person (or an agent)
exploring the surface, and "Internal Server Error" teaches them nothing.

Services come from ``app.state`` via dependency injection, never a module
singleton — same rule as every other router in ``atlas.api``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.introspect import registry as introspect

router = APIRouter()


def _app_of(request: Request) -> Any:
    """The FastAPI app this request arrived on.

    Route-level introspection must read the app that actually served the request
    rather than a module-level global, for the same reason services do: a second
    app instance in the same process (tests, or a future multi-app embed) would
    otherwise describe somebody else's route table.
    """
    return request.app


@router.get("/api/introspect/providers")
async def list_providers(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Every provider with its methods and input schemas.

    Returned in one call so a client can build its whole UI (or an agent can plan
    a whole investigation) without discovering the surface by trial and error.
    """
    return introspect.list_providers()


@router.get("/api/introspect/providers/{provider_id}")
async def describe_provider(
    provider_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """One provider's manifest."""
    try:
        return introspect.describe(provider_id)
    except introspect.QueryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/introspect/query")
async def run_query(
    request: Request,
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: Annotated[
        dict[str, Any],
        Body(
            description=(
                "``{provider, method, input?}`` — ``input`` must satisfy the method's "
                "declared schema; unknown keys are rejected rather than ignored."
            )
        ),
    ],
) -> dict[str, Any]:
    """Run one read-only query.

    A provider that raises ``KeyError`` is answering "that name does not exist",
    which is a client mistake (404). Anything else is a real fault and propagates
    as a 500 rather than being flattened into a friendly message that would hide a
    broken provider.
    """
    provider = str(payload.get("provider") or "").strip()
    method = str(payload.get("method") or "").strip()
    if not provider or not method:
        raise HTTPException(
            status_code=422, detail="payload 需要 provider 与 method 两个字段。"
        )
    raw_input = payload.get("input")
    if raw_input is None:
        inputs: dict[str, Any] = {}
    elif isinstance(raw_input, dict):
        inputs = raw_input
    else:
        raise HTTPException(status_code=422, detail="input 必须是对象（键值表）。")

    try:
        return await introspect.query(
            provider, method, inputs, services=services, app=_app_of(request)
        )
    except introspect.QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
