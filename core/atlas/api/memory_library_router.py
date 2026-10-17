"""Memory library (docs/memory/PLAN-V1.md) for the memory page and for other devices.

- GET  /api/memlib/today              今日变动、现状、今天聊了几轮
- GET  /api/memlib/overview           所有页面（我 / 现状 / 它自己 / 人 / 事）
- GET  /api/memlib/page?path=人/老王.md  一页的当前与历史
- GET  /api/memlib/changes?limit=60   变动记录（每次 git 提交一条，附增删）
- GET  /api/memlib/search?q=...       搜索（和 memory_search 工具同一套）
- POST /api/memlib/entry              {"id", "text"} 改一条 → 标成「你改的」
- POST /api/memlib/add                {"path", "text"} 在某页加一条
- POST /api/memlib/forget             {"id"} 忘掉一条（留墓碑，日记原文一并抹掉）
- POST /api/memlib/aliases            {"path", "aliases": [...]}
- POST /api/memlib/revert             {"sha"} 撤销某次变动
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from atlas.memory.library import MemoryLibrary, get_library
from atlas.memory.library.store import Entry

router = APIRouter(prefix="/api/memlib", tags=["memory-library"])
log = structlog.get_logger(__name__)
_dream_task: asyncio.Task[Any] | None = None


def _lib() -> MemoryLibrary:
    library = get_library()
    if library is None:
        raise HTTPException(503, "记忆库已在配置中关闭（[memory.library] enabled = false）。")
    return library


async def _run(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except KeyError as exc:
        raise HTTPException(404, "找不到这条记忆，可能已经被改过。") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


class EntryEdit(BaseModel):
    id: str
    text: str


class EntryAdd(BaseModel):
    path: str
    text: str


class QueueRetry(BaseModel):
    id: int | None = None


class EntryRef(BaseModel):
    id: str


class Aliases(BaseModel):
    path: str
    aliases: list[str]


class Revert(BaseModel):
    sha: str


@router.get("/today")
async def today() -> dict[str, Any]:
    return await _run(_lib().today)


@router.get("/overview")
async def overview() -> dict[str, Any]:
    return await _run(_lib().overview)


@router.get("/page")
async def page(path: str) -> dict[str, Any]:
    return await _run(_lib().page_view, path)


@router.get("/changes")
async def changes(limit: int = 60, diary: bool = False) -> dict[str, Any]:
    rows = await _run(_lib().changes, max(1, min(300, limit)), diary)
    return {"changes": rows}


@router.get("/search")
async def search(
    q: str = "",
    src: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    project: str = "",
    kinds: str = "memory",
    limit: int = 30,
    offset: int = 0,
    history: bool = False,
) -> dict[str, Any]:
    requested = tuple(x.strip() for x in kinds.split(",") if x.strip())
    normalized = ("fact", "dream", "episode", "diary") if "memory" in requested else ()
    if "raw" in requested:
        normalized += ("raw",)
    # Filtering and total calculation happen below, so gather the full bounded
    # candidate set before applying offset/limit. The index caps this at 100k.
    rows = await _run(_lib().search, q, 100000, history, normalized)
    _lib().index._schedule_embeddings()
    sources = {x.strip() for x in src.split(",") if x.strip()}
    filtered = []
    for row in rows:
        path, text = str(row.get("path") or ""), str(row.get("text") or "")
        if sources and row.get("src") not in sources:
            continue
        if from_ and str(row.get("at") or "")[:10] < from_:
            continue
        if to and str(row.get("at") or "")[:10] > to:
            continue
        if project and project.casefold() not in (path + text).casefold():
            continue
        filtered.append(row)
    items = []
    for row in filtered[max(0, offset) : max(0, offset) + max(1, min(100, limit))]:
        path = str(row.get("path") or "")
        items.append(
            {
                "id": row.get("id"),
                "kind": row.get("kind"),
                "path": path,
                "title": Path(path).stem,
                "text": row.get("text"),
                "snippet": row.get("text"),
                "src": row.get("src"),
                "at": row.get("at"),
                "ref": row.get("ref"),
                "score": row.get("score"),
                "project": Path(path).stem if path.startswith("事/") else "",
            }
        )
    return {"total": len(filtered), "items": items}


@router.get("/timeline")
async def timeline(before: str = "", limit: int = 50, src: str = "") -> dict[str, Any]:
    library = _lib()
    await _run(library.ready)
    entries = []
    for rel in library.store.pages():
        if not rel.startswith("经历/"):
            continue
        for entry in library.store.read(rel).current:
            if before:
                cursor_at, sep, cursor_id = before.partition("|")
                if sep:
                    if (entry.at, entry.id) >= (cursor_at, cursor_id):
                        continue
                elif entry.at >= cursor_at:
                    continue
            if src and entry.src != src:
                continue
            entries.append(entry)
    entries.sort(key=lambda e: (e.at, e.id), reverse=True)
    size = max(1, min(100, limit))
    page = entries[:size]
    return {
        "items": [
            {
                "id": e.id,
                "day": e.at[:10],
                "at": e.at,
                "session": e.session,
                "ref": e.ref,
                "text": e.text,
                "outcome": e.outcome,
                "verified": e.verified,
                "steps": e.steps,
                "decisions": e.decisions,
                "files": e.files,
                "commands": e.commands,
                "facts": e.facts,
                "open_items": e.open_items,
                "trigger": e.trigger,
            }
            for e in page
        ],
        "next": f"{page[-1].at}|{page[-1].id}" if len(entries) > size and page else None,
    }


@router.get("/projects")
async def projects() -> dict[str, Any]:
    library = _lib()
    await _run(library.ready)
    rows = []
    for rel in library.store.pages():
        if not rel.startswith("事/"):
            continue
        page = library.store.read(rel)
        text = (library.store.root / rel).read_text(encoding="utf-8")
        pending_section = False
        open_items = 0
        for line in text.splitlines():
            if line.startswith("## "):
                pending_section = line[3:].strip() == "没做完"
            elif pending_section and line.strip().startswith(("-", "*")):
                open_items += 1
        rows.append(
            {
                "path": rel,
                "title": page.title,
                "count": len(page.current),
                "updated": max((e.at for e in page.current), default=""),
                "open_items": open_items,
            }
        )
    rows.sort(key=lambda row: row["updated"], reverse=True)
    return {"items": rows}


@router.get("/project")
async def project(path: str) -> dict[str, Any]:
    library = _lib()
    await _run(library.ready)
    rel = library._safe_rel(path)
    if not rel.startswith("事/"):
        raise HTTPException(400, "项目路径必须位于事/目录")
    page = library.store.read(rel)
    section_names = ("现在状态", "定下的决定", "没做完", "来龙去脉")
    sections: dict[str, list[dict[str, Any]]] = {key: [] for key in section_names}
    source = library.store.root / rel
    current = None
    if source.exists():
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
            elif current in sections:
                entry = Entry.parse(line)
                if entry:
                    sections[current].append(
                        {
                            "id": entry.id,
                            "text": entry.text,
                            "src": entry.src,
                            "at": entry.at,
                            "ref": entry.ref,
                        }
                    )
    return {
        "path": rel,
        "title": page.title,
        "aliases": page.aliases,
        "sections": sections,
        "history": [
            *sections["来龙去脉"],
            *[
                {"id": e.id, "text": e.text, "src": e.src, "at": e.at, "ref": e.ref}
                for e in page.history
            ],
        ],
    }


@router.get("/open")
async def open_source(ref: str, window: int = 1) -> dict[str, Any]:
    from atlas.memory.library.sources import open_ref

    return await _run(open_ref, ref, max(1, min(2, window)))


@router.get("/stats")
async def stats() -> dict[str, Any]:
    library = _lib()
    await _run(library.ready)
    facts = episodes = projects_count = 0
    last_dream = None
    for rel in library.store.pages():
        page = library.store.read(rel)
        if rel.startswith("事/"):
            projects_count += 1
            facts += len(page.current)
        elif rel.startswith("经历/"):
            episodes += len(page.current)
        else:
            facts += len(page.current)
        for entry in page.current:
            if entry.src == "整理" and (last_dream is None or entry.at > last_dream):
                last_dream = entry.at
    today = datetime.now().astimezone().date().isoformat()
    today_added = sum(
        1
        for rel in library.store.pages()
        for entry in library.store.read(rel).current
        if entry.at[:10] == today
    )
    return {
        "facts": facts,
        "episodes": episodes,
        "projects": projects_count,
        "diary_days": len(library.store.diary_pages()),
        "today_added": today_added,
        "last_dream": last_dream,
        "pending_failed": library.queue.failed_count(),
        "embed": library.index.embedding_state,
    }


@router.post("/dream")
async def run_dream_now() -> dict[str, Any]:
    from atlas import server
    from atlas.memory.library.dream import run_dream

    return await run_dream(_lib(), getattr(server, "model_mgr", None))


@router.get("/queue/failed")
async def failed_queue(limit: int = 100) -> dict[str, Any]:
    return {"items": await _run(_lib().queue.failed, limit)}


@router.post("/queue/retry")
async def retry_failed_queue(body: QueueRetry) -> dict[str, Any]:
    from atlas import server

    library = _lib()
    retried = await _run(library.queue.retry_failed, body.id)
    if retried:
        task = asyncio.create_task(library._drain(getattr(server, "model_mgr", None)))
        library._tasks.add(task)
        task.add_done_callback(library._tasks.discard)
    return {"retried": retried}


async def _dream_scheduler() -> None:
    while True:
        now = datetime.now().astimezone()
        next_run = now.replace(hour=3, minute=30, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep(max(1, (next_run - now).total_seconds()))
        try:
            from atlas import server
            from atlas.memory.library.dream import run_dream

            library = get_library()
            if library:
                await run_dream(library, getattr(server, "model_mgr", None))
        except Exception as exc:  # noqa: BLE001 - daemon must survive a failed daily run.
            log.warning("memory.library.dream_scheduler_failed", error=str(exc))


@router.on_event("startup")
async def start_dream_scheduler() -> None:
    global _dream_task
    if _dream_task is None or _dream_task.done():
        _dream_task = asyncio.create_task(_dream_scheduler())
    library = get_library()
    if library and library.queue.count():
        from atlas import server

        async def drain_pending() -> None:
            await asyncio.sleep(1)
            await library._drain(getattr(server, "model_mgr", None))

        task = asyncio.create_task(drain_pending())
        library._tasks.add(task)
        task.add_done_callback(library._tasks.discard)


@router.on_event("shutdown")
async def stop_dream_scheduler() -> None:
    global _dream_task
    if _dream_task:
        _dream_task.cancel()
        try:
            await _dream_task
        except asyncio.CancelledError:
            pass
        _dream_task = None


@router.post("/entry")
async def edit_entry(body: EntryEdit) -> dict[str, Any]:
    return await _run(_lib().edit_entry, body.id, body.text)


@router.post("/add")
async def add_entry(body: EntryAdd) -> dict[str, Any]:
    return await _run(_lib().add_entry, body.path, body.text)


@router.post("/forget")
async def forget(body: EntryRef) -> dict[str, Any]:
    return await _run(_lib().forget_entry, body.id)


@router.post("/aliases")
async def aliases(body: Aliases) -> dict[str, Any]:
    await _run(_lib().set_aliases, body.path, body.aliases)
    return {"ok": True}


@router.post("/revert")
async def revert(body: Revert) -> dict[str, Any]:
    await _run(_lib().revert, body.sha)
    return {"ok": True}
