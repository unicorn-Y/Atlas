"""Provider registry for Atlas self-introspection.

Atlas is large enough that "what can it actually do right now?" stopped being a
question you can answer by reading code: 767 route decorators, 77 routers, a
tool registry with scoped toolsets, 68 desktop event names, and a config file
that mixes defaults with live secrets. Every one of those is discoverable only
by grepping or by booting the app and poking it.

This module makes that knowledge *queryable at runtime* by the same process that
owns it. A :class:`Provider` is a named, versionless, read-only view over one
subsystem; each :class:`Method` declares a JSON-schema-shaped input plus one
callable. The contract is deliberately narrow:

* **Read-only.** No method may mutate state, write files, spend a model request,
  or consume a run. ``/api/introspect/*`` is safe to call on every page load.
* **Never leaks a secret.** Any string that came from configuration goes through
  :func:`atlas.secrets_store.redact` before it leaves a provider.
* **Reuses the authority.** Providers read the live services the app already
  owns (``app.state.services``) and the modules that already know the answer —
  ``atlas.api.event_names``, ``atlas.capabilities.probes``,
  ``atlas.engine.tools.registry``. A provider that re-implements a subsystem's
  logic is a second truth source, which is the exact failure mode this package
  exists to remove.

The provider set mirrors what a Cordis-style host exposes as Inspect Providers,
so the same questions have the same shape here.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)

Args = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Context:
    """What a provider is allowed to read.

    Two handles, both owned by the live application:

    ``services``
        The per-app :class:`atlas.api.app_services.AppServices` container, so a
        provider sees exactly the service graph this app instance built.
    ``app``
        The FastAPI application, needed by providers that answer questions about
        *mounting* (which routes exist, in which order) rather than about a
        service.

    Nothing else. A provider cannot open its own database, build a second config
    loader, or reach a module singleton — that is how two truths start.
    """

    services: Any = None
    app: Any = None


Runner = Callable[[Context, Args], "Any | Awaitable[Any]"]


class QueryError(Exception):
    """An answerable-shaped request that cannot be answered.

    Raised for an unknown provider, an unknown method, or input that violates
    the method's declared schema. The router maps it to HTTP 400/404 — a client
    mistake, never a 500, because a typo in a method name is not a server fault.
    """


@dataclass(frozen=True, slots=True)
class Method:
    """One read-only question a provider can answer."""

    name: str
    summary: str
    input_schema: dict[str, Any]
    run: Runner

    def manifest(self) -> dict[str, Any]:
        return {"name": self.name, "summary": self.summary, "input": self.input_schema}


@dataclass(frozen=True, slots=True)
class Provider:
    """One subsystem's read-only view."""

    id: str
    title: str
    summary: str
    methods: tuple[Method, ...]

    def method(self, name: str) -> Method:
        for candidate in self.methods:
            if candidate.name == name:
                return candidate
        available = ", ".join(m.name for m in self.methods)
        raise QueryError(f"provider {self.id!r} has no method {name!r} (available: {available})")

    def manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "methods": [method.manifest() for method in self.methods],
        }


# ---------------------------------------------------------------------------
# Schema helpers — small on purpose
# ---------------------------------------------------------------------------

_PY_TYPES: dict[str, type] = {
    "string": str,
    "boolean": bool,
    "integer": int,
    "array": list,
    "object": dict,
}


def object_schema(
    properties: dict[str, dict[str, Any]] | None = None,
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build the object schema shape every Method input uses."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties or {}),
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _check_args(schema: dict[str, Any], args: Args) -> None:
    """Reject unknown keys, missing required keys, and wrong scalar types.

    Hand-rolled instead of ``jsonschema``: the inputs here are flat objects with
    a handful of string/bool/integer fields, and a hand-rolled check can name the
    offending key in the user's language, which a validator traceback cannot.
    """
    properties: dict[str, dict[str, Any]] = schema.get("properties") or {}
    required: tuple[str, ...] = tuple(schema.get("required") or ())

    unknown = sorted(set(args) - set(properties))
    if unknown:
        allowed = ", ".join(sorted(properties)) or "无"
        raise QueryError(f"未知参数：{', '.join(unknown)}（可用参数：{allowed}）")

    missing = [key for key in required if key not in args]
    if missing:
        raise QueryError(f"缺少必填参数：{', '.join(missing)}")

    for key, value in args.items():
        declared = properties[key].get("type")
        expected = _PY_TYPES.get(str(declared))
        if expected is None:
            continue
        # bool is a subclass of int, so check it before the integer branch.
        if expected is int and isinstance(value, bool):
            raise QueryError(f"参数 {key} 需要整数")
        if not isinstance(value, expected):
            raise QueryError(f"参数 {key} 需要 {declared}")


# ---------------------------------------------------------------------------
# Registry surface
# ---------------------------------------------------------------------------


def providers() -> tuple[Provider, ...]:
    """Every provider, in presentation order.

    Imported lazily so this module stays importable without dragging in the tool
    registry or the config loader (which reads disk) at import time.
    """
    from atlas.introspect.providers import PROVIDERS

    return PROVIDERS


def get_provider(provider_id: str) -> Provider:
    for provider in providers():
        if provider.id == provider_id:
            return provider
    known = ", ".join(p.id for p in providers())
    raise QueryError(f"未知 provider：{provider_id!r}（已注册：{known}）")


def list_providers() -> dict[str, Any]:
    """Manifest for every provider — the equivalent of ``GET /providers``."""
    manifests = [provider.manifest() for provider in providers()]
    return {
        "count": len(manifests),
        "providers": manifests,
        "method_count": sum(len(item["methods"]) for item in manifests),
    }


def describe(provider_id: str) -> dict[str, Any]:
    return get_provider(provider_id).manifest()


async def query(
    provider_id: str,
    method: str,
    payload: dict[str, Any] | None = None,
    *,
    services: Any = None,
    app: Any = None,
) -> dict[str, Any]:
    """Run one read-only query and wrap the answer with provenance.

    ``duration_ms`` is included because the honest use of this surface is
    diagnosing a live system: if ``health.capabilities`` takes four seconds, that
    number is itself a finding.
    """
    provider = get_provider(provider_id)
    target = provider.method(method)
    args: Args = dict(payload or {})
    _check_args(target.input_schema, args)

    started = time.perf_counter()
    result = target.run(Context(services=services, app=app), args)
    if inspect.isawaitable(result):
        result = await result
    duration_ms = int((time.perf_counter() - started) * 1000)
    log.debug(
        "introspect.query",
        provider=provider.id,
        method=target.name,
        duration_ms=duration_ms,
    )
    return {
        "provider": provider.id,
        "method": target.name,
        "duration_ms": duration_ms,
        "result": result,
    }


__all__ = [
    "Args",
    "Context",
    "Method",
    "Provider",
    "QueryError",
    "Runner",
    "describe",
    "get_provider",
    "list_providers",
    "object_schema",
    "providers",
    "query",
]
