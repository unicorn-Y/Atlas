"""Introspection provider: the live service graph.

``AppServices`` is the composition root — one dataclass whose fields are the
authorities this application actually built. When a feature looks broken and the
question is "is the thing even wired?", this provider answers it without a
debugger: which fields are bound, what each one *is*, and what it can do.

Field values are never returned. A service is an object graph that routinely
holds credentials, model clients, and user data; the useful facts are its type
and its callable surface.
"""

from __future__ import annotations

import inspect
from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema


def _slots(container: Any) -> tuple[str, ...]:
    if container is None:
        return ()
    return tuple(getattr(container, "__slots__", ()) or ())


def _describe_value(value: Any) -> dict[str, Any]:
    """Type identity and callable surface, without touching instance state.

    ``inspect.getmembers_static`` is deliberate: plain ``getattr`` on a service
    runs properties and ``__getattr__`` shims, which can open sockets or read
    disk. Introspection must not have side effects.
    """
    if value is None:
        return {"bound": False, "type": "None", "methods": [], "method_count": 0}

    cls = type(value)
    try:
        members = inspect.getmembers_static(value)
    except Exception:  # noqa: BLE001 - a hostile __dir__ must not 500 the endpoint
        members = []
    methods = sorted(
        name
        for name, _ in members
        if not name.startswith("_") and callable(getattr(cls, name, None))
    )
    return {
        "bound": True,
        "type": cls.__name__,
        "module": cls.__module__,
        "methods": methods,
        "method_count": len(methods),
    }


def _list_services(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    container = ctx.services
    if container is None:
        return {"count": 0, "services": [], "note": "当前应用还没有 AppServices 容器。"}

    rows: list[dict[str, Any]] = []
    for name in sorted(_slots(container)):
        value = getattr(container, name, None)
        rows.append(
            {"name": name, "bound": value is not None, "type": type(value).__name__}
        )

    wanted = str(args.get("filter") or "").strip().lower()
    if wanted:
        rows = [
            row
            for row in rows
            if wanted in row["name"].lower() or wanted in row["type"].lower()
        ]
    if args.get("only_bound") is True:
        rows = [row for row in rows if row["bound"]]

    return {
        "count": len(rows),
        "bound": sum(1 for row in rows if row["bound"]),
        "services": rows,
    }


def _service_detail(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    name = args["name"]
    container = ctx.services
    if container is None or name not in _slots(container):
        declared = ", ".join(sorted(_slots(container))) or "无"
        raise KeyError(f"AppServices 没有字段 {name!r}（已声明：{declared}）")
    return {"name": name, **_describe_value(getattr(container, name, None))}


def _unbound(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Every declared-but-unbound field.

    This list is the honest wiring debt: a field that is ``None`` is a feature
    whose dependency was never provided, and the failure mode is a 500 at
    request time rather than a startup error.
    """
    container = ctx.services
    slots = _slots(container)
    empty = [name for name in sorted(slots) if getattr(container, name, None) is None]
    return {"count": len(empty), "unbound": empty, "declared": len(slots)}


def _projections(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Registered derived session views, their deps, and cache counters.

    The hit/miss/eviction split is the point: a projection with many misses and
    no hits is either mis-keyed or invalidated by an event that fires constantly,
    and both look like "the summary feels slow" from the outside.
    """
    registry = getattr(ctx.services, "session_projections", None) if ctx.services else None
    if registry is None:
        return {"registered": 0, "note": "当前应用没有 session_projections 容器。"}
    return registry.describe()


def _wiring(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    """The container's own wiring report, read through its accessors.

    ``wired()``/``unwired()`` are the methods handlers use to guard themselves, so
    this endpoint reports exactly what the code will see — not a parallel
    re-derivation that could disagree with it.
    """
    container = ctx.services
    if container is None:
        return {"note": "当前应用还没有 AppServices 容器。"}
    wired = getattr(container, "wired", None)
    unwired = getattr(container, "unwired", None)
    if not callable(wired) or not callable(unwired):
        return {"note": "这个容器没有 wired()/unwired() 访问器。"}
    bound = wired()
    empty = unwired()
    return {
        "wired": bound,
        "wired_count": len(bound),
        "unwired": sorted(empty),
        "unwired_count": len(empty),
        "declared": len(bound) + len(empty),
    }


def _registry(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    """Who registered each service, and what a teardown could remove.

    `wiring` answers "is the field filled"; this answers "who filled it" — the
    question a plugin unload actually needs, and the one a flat dataclass cannot
    answer at all.
    """
    container = ctx.services
    if container is None:
        return {"note": "当前应用还没有 AppServices 容器。"}
    registry = getattr(container, "service_registry", None)
    if registry is None:
        return {"note": "这个容器没有 service_registry。"}
    snapshot = getattr(registry, "snapshot", None)
    owners = getattr(registry, "owners", None)
    registered = snapshot() if callable(snapshot) else {}
    return {
        "registered": registered,
        "count": len(registered),
        "by_owner": owners() if callable(owners) else {},
    }


PROVIDER = Provider(
    id="services",
    title="服务图谱",
    summary="当前应用实际构建出来的服务对象：哪些已接线、每个是什么、能调用什么。",
    methods=(
        Method(
            name="list",
            summary="列出 AppServices 的每个字段及其绑定状态。",
            input_schema=object_schema(
                {
                    "filter": {"type": "string", "description": "按字段名或类型名做子串过滤。"},
                    "only_bound": {"type": "boolean", "description": "只返回已绑定的字段。"},
                }
            ),
            run=_list_services,
        ),
        Method(
            name="detail",
            summary="看一个服务字段的类型与公开方法名。",
            input_schema=object_schema(
                {"name": {"type": "string", "description": "AppServices 的字段名。"}},
                required=("name",),
            ),
            run=_service_detail,
        ),
        Method(
            name="unbound",
            summary="列出声明了但没接线的字段（接线债）。",
            input_schema=object_schema(),
            run=_unbound,
        ),
        Method(
            name="projections",
            summary="已注册的会话派生视图：依赖哪个事件、命中/未命中/淘汰各多少次。",
            input_schema=object_schema(),
            run=_projections,
        ),
        Method(
            name="wiring",
            summary="容器自身的接线报告：已接线的字段与类型、未接线的字段。",
            input_schema=object_schema(),
            run=_wiring,
        ),
        Method(
            name="registry",
            summary="服务注册表：每个服务由谁注册、按 owner 的计数，以及哪些可被撤销。",
            input_schema=object_schema(),
            run=_registry,
        ),
    ),
)
