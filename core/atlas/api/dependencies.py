"""FastAPI dependencies shared by domain routers."""

from __future__ import annotations

from starlette.requests import HTTPConnection

from atlas.api.app_services import AppServices


def get_app_services(connection: HTTPConnection) -> AppServices:
    """Resolve services from this request's app, never from a module singleton."""
    services = getattr(connection.app.state, "services", None)
    if not isinstance(services, AppServices):
        raise RuntimeError("FastAPI app is missing its AppServices container")
    return services
