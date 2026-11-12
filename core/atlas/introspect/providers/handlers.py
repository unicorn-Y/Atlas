"""Introspection provider: the mounted HTTP surface.

Atlas has 77 ``*_router.py`` modules and hundreds of route decorators. Two things
go wrong at that size and neither is visible from any single file:

**Shadowing.** Starlette matches routes in registration order. Two routers
declaring the same path and method means the second is unreachable, and the
symptom is an endpoint that "exists" in source and 404s (or answers with the
wrong handler) at runtime.

**Orphaning.** A router that defines routes but is never passed to
``include_router`` is dead code that looks alive. This happens silently because
importing a module has no effect on the app.

Both questions are answered by the *mounted* app, not by source. That is why this
provider reads ``app.routes`` and never re-parses decorators: the app object is
already the authority on what was actually included, in the order it was
included.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema

_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


def _route_rows(ctx: Context) -> list[dict[str, Any]]:
    """One row per (path, method) actually mounted on the app."""
    app = ctx.app
    rows: list[dict[str, Any]] = []
    for route in getattr(app, "routes", ()) or ():
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if path is None or not methods or endpoint is None:
            # Mounts and websocket routes carry no HTTP method set; skip them
            # here and report them separately by count.
            continue
        for method in sorted(methods & set(_HTTP_METHODS)):
            rows.append(
                {
                    "method": method,
                    "path": path,
                    "handler": getattr(endpoint, "__name__", type(endpoint).__name__),
                    "module": getattr(endpoint, "__module__", ""),
                }
            )
    return rows


def _summary(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    rows = _route_rows(ctx)
    modules = Counter(row["module"] for row in rows)
    all_routes = list(getattr(ctx.app, "routes", ()) or ())
    return {
        "routes": len(rows),
        "paths": len({row["path"] for row in rows}),
        "modules": len(modules),
        "mounts": sum(1 for r in all_routes if type(r).__name__ == "Mount"),
        "websockets": sum(1 for r in all_routes if type(r).__name__ == "WebSocketRoute"),
        "top_modules": [
            {"module": module, "routes": count}
            for module, count in modules.most_common(int(args.get("top") or 15))
        ],
    }


def _list_routes(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    rows = _route_rows(ctx)
    prefix = str(args.get("path_prefix") or "")
    method = str(args.get("method") or "").upper()
    module = str(args.get("module") or "")
    if prefix:
        rows = [row for row in rows if row["path"].startswith(prefix)]
    if method:
        rows = [row for row in rows if row["method"] == method]
    if module:
        rows = [row for row in rows if module in row["module"]]

    limit = int(args.get("limit") or 200)
    return {"matched": len(rows), "returned": min(limit, len(rows)), "routes": rows[:limit]}


def _shadowed(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Paths+methods claimed more than once — only the first is reachable."""
    rows = _route_rows(ctx)
    counts = Counter((row["method"], row["path"]) for row in rows)
    dupes = []
    for (method, path), count in counts.items():
        if count < 2:
            continue
        claimants = [
            {"handler": r["handler"], "module": r["module"]}
            for r in rows
            if r["method"] == method and r["path"] == path
        ]
        dupes.append(
            {
                "method": method,
                "path": path,
                "count": count,
                "reachable": claimants[0],
                "unreachable": claimants[1:],
            }
        )
    dupes.sort(key=lambda item: (item["path"], item["method"]))
    return {
        "count": len(dupes),
        "note": "同一路径+方法被注册多次时，只有第一个能命中；其余是永远走不到的处理函数。",
        "duplicates": dupes,
    }


PROVIDER = Provider(
    id="routes",
    title="接口面",
    summary="应用实际挂载了哪些路由、按模块如何分布、有没有被遮蔽（注册了但永远走不到）。",
    methods=(
        Method(
            name="summary",
            summary="路由总数、模块分布、mount 与 websocket 数量。",
            input_schema=object_schema(
                {"top": {"type": "integer", "description": "返回前 N 个模块，默认 15。"}}
            ),
            run=_summary,
        ),
        Method(
            name="list",
            summary="按前缀/方法/模块筛选具体路由。",
            input_schema=object_schema(
                {
                    "path_prefix": {"type": "string", "description": "只保留该前缀开头的路径。"},
                    "method": {"type": "string", "description": "只保留该 HTTP 方法。"},
                    "module": {"type": "string", "description": "只保留模块名含该子串的路由。"},
                    "limit": {"type": "integer", "description": "最多返回多少条，默认 200。"},
                }
            ),
            run=_list_routes,
        ),
        Method(
            name="shadowed",
            summary="找出被重复注册、因而永远走不到的路由。",
            input_schema=object_schema(),
            run=_shadowed,
        ),
    ),
)
