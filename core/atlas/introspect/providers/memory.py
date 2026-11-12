"""Introspection provider: the memory library.

Atlas keeps memory as a Markdown-and-git library rather than a vector store, so
the honest questions are structural: which pages exist, which of the four
first-class kinds they are, and whether the library finished its startup
reconciliation. Those are exactly what this provider answers.

``overview()`` re-reads every page and is deliberately **not** called here: on a
real library it is the expensive path, and an introspection request must never
turn into a full disk scan. ``today()`` and the page list are cheap.
"""

from __future__ import annotations

from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema

#: The four kinds the library treats as first-class memory. Anything else is
#: derived text (candidates, notes) rather than a remembered fact.
MEMORY_KINDS = ("diary", "dream", "episode", "fact")


def _library(ctx: Context) -> Any:
    return getattr(ctx.services, "memory", None) if ctx.services else None


def _kinds(_ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    from atlas.memory.library import MemoryLibrary

    return {
        "kinds": list(MEMORY_KINDS),
        "class": MemoryLibrary.__name__,
        "note": "记忆库以 Markdown + git 保存；这里列出的是一等记忆类型。",
    }


def _pages(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    lib = _library(ctx)
    if lib is None:
        return {"count": 0, "pages": [], "note": "当前应用没有 memory 服务。"}
    fn = getattr(lib, "overview", None)
    if not callable(fn):
        return {"count": 0, "pages": [], "note": "memory 服务没有 overview()。"}
    try:
        overview = fn()
    except Exception as exc:  # noqa: BLE001 - a broken library must not 500 the endpoint
        return {"count": 0, "pages": [], "error": f"{type(exc).__name__}: {exc}"}

    rows = list(overview.get("pages") or [])
    wanted = str(args.get("kind") or "").strip().lower()
    if wanted:
        rows = [row for row in rows if str(row.get("kind", "")).lower() == wanted]
    filtered = str(args.get("filter") or "").strip().lower()
    if filtered:
        rows = [
            row
            for row in rows
            if filtered in str(row.get("path", "")).lower()
            or filtered in str(row.get("title", "")).lower()
        ]
    return {
        "count": len(rows),
        "root": overview.get("root", ""),
        "pages": rows,
    }


def _today(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    lib = _library(ctx)
    if lib is None:
        return {"note": "当前应用没有 memory 服务。"}
    fn = getattr(lib, "today", None)
    if not callable(fn):
        return {"note": "memory 服务没有 today()。"}
    try:
        return dict(fn())
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


PROVIDER = Provider(
    id="memory",
    title="记忆库",
    summary="Markdown + git 记忆库的结构：一等记忆类型、页面清单与今日条目。",
    methods=(
        Method(
            name="kinds",
            summary="列出记忆库的一等记忆类型（日记/梦/情景/事实）。",
            input_schema=object_schema(),
            run=_kinds,
        ),
        Method(
            name="pages",
            summary="列出记忆页面的路径、标题、类型与条目数。",
            input_schema=object_schema(
                {
                    "kind": {
                        "type": "string",
                        "description": "只看某一类，例如 diary / dream / episode / fact。",
                    },
                    "filter": {
                        "type": "string",
                        "description": "按页面路径或标题做子串过滤。",
                    },
                }
            ),
            run=_pages,
        ),
        Method(
            name="today",
            summary="今天写进记忆库的条目。",
            input_schema=object_schema(),
            run=_today,
        ),
    ),
)
