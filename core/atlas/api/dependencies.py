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


def get_optional_app_services(connection: HTTPConnection) -> AppServices | None:
    """The container when this app has one, else ``None``.

    For routers that were mounted standalone before the container existed and
    still support that: they hold a module-level actuator (``set_collections``,
    ``set_market_supplier``, …) as their fallback. Raising :func:`get_app_services`
    in those handlers would make a supported mount mode crash, so they take this
    instead and read the container *first* at request time.

    Everywhere a handler genuinely cannot work without the container, keep using
    :func:`get_app_services` — a 500 naming the missing container is the honest
    answer there, and this variant would only turn it into a later AttributeError.
    """
    services = getattr(connection.app.state, "services", None)
    return services if isinstance(services, AppServices) else None
