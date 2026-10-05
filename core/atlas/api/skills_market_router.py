"""REST surface for the X4 Skill Market (``/api/skills/market/*``).

Search, detail/preview, install, updates, uninstall, enable/disable and source
(tap) management over the Hermes Skills Hub source layer. All skill state lives
in the ONE Atlas Registry (see ``atlas.skills.market``); this module is HTTP
wiring only.

OriginGuard: the whole ``atlas.server`` app sits behind the ``OriginGuard``
ASGI middleware (``atlas.origin_guard``), which covers every route below once
the integration owner mounts this router. The ``_require_trusted_origin``
dependency re-applies the exact same ``is_trusted`` rule so the router stays
safe when mounted standalone (tests, tooling); under server.py it is a cheap
redundant check.

Integration note for the owner of ``atlas/server.py``:

- ``app.include_router(skills_market_router)`` — include it in the same section
  as the other routers; ``GET /api/skills/updates`` would otherwise be shadowed
  by the pre-existing ``GET /api/skills/{name}`` route (FastAPI matches in
  registration order), so the router must be included before that route is
  declared.
- The taskbook's ``DELETE /api/skills/{name}`` had no collision: server.py
  declares no DELETE route on that path today. If one appears, rename this
  route to ``DELETE /api/skills/market/{name}``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from atlas.origin_guard import TOKEN_HEADER, is_trusted
from atlas.skills.acquisition import _parse_manifest, payload_sha256
from atlas.skills.market import (
    MarketConflictError,
    MarketError,
    MarketUnavailableError,
    _canonical_name,
)

router = APIRouter(tags=["skill-market"])

_market_supplier: Any = None


def set_market_supplier(supplier: Any) -> None:
    """Override the default market builder (tests, custom wiring)."""
    global _market_supplier
    _market_supplier = supplier


def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(
        request.headers.get("origin"),
        request.headers.get(TOKEN_HEADER),
        fetch_site=request.headers.get("sec-fetch-site"),
    )
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")


def get_market() -> Any:
    if _market_supplier is not None:
        return _market_supplier()
    from atlas.skills.market import default_market

    def build() -> Any:
        from atlas.server import skill_mgr, skill_registry  # lazy; avoids import cycle

        assert skill_registry is not None
        return default_market(skill_registry, skill_manager=skill_mgr)

    return build()


def _http_error(exc: MarketError) -> HTTPException:
    status = 409 if isinstance(exc, MarketConflictError) else (
        503 if isinstance(exc, MarketUnavailableError) else 422
    )
    return HTTPException(status_code=status, detail={
        "message": exc.message, "code": exc.code,
        **({"details": exc.details} if exc.details else {}),
    })


# ---------------------------------------------------------------------------
# Local-origin persistence (X2 recordings / X5 evolved skills)
# ---------------------------------------------------------------------------
LOCAL_ORIGIN_KINDS = ("local_recorded", "local_evolved")


def save_local_skill_bundle(
    name: str,
    files: dict[str, str],
    *,
    origin_kind: str,
    reason: str,
    market: Any | None = None,
) -> dict[str, Any]:
    """Write a locally-produced skill bundle (X2 recording / X5 evolved) into
    the user-scope discovery directory and register it in the ONE registry.

    Layout and writers are SkillMarket's own — no second layout, no second
    registry: destination via the same ``_destination`` resolution ``install``
    uses (``<user skills>/community/<name>``, priority-10 ``atlas`` source),
    staged atomic payload via ``_write_payload``, provenance + audit history via
    ``register_local``. Re-saving the same origin updates in place: prior
    local-origin rows whose version or content no longer match are dropped
    (the same drop-before-reinstall rule ``_resolve_conflict`` applies to
    market-managed copies); foreign rows are never touched.
    """
    if market is None:
        market = get_market()
    if origin_kind not in LOCAL_ORIGIN_KINDS:
        raise MarketError(
            f"origin_kind 只支持 {'、'.join(LOCAL_ORIGIN_KINDS)}。", code="invalid_origin_kind")
    name = _canonical_name(name)
    if not isinstance(files, dict) or not str(files.get("SKILL.md") or "").strip():
        raise MarketError("技能包缺少 SKILL.md，无法保存。", code="invalid_local_skill")
    dest = market._destination("user", name)
    try:
        manifest, _dependencies = _parse_manifest(files["SKILL.md"], name)
    except ValueError as exc:
        raise MarketError(
            f"技能「{name}」的 SKILL.md 不符合 Atlas 规范：{exc}", code="invalid_manifest",
        ) from exc
    digest = payload_sha256(files)
    for row in market.registry.list():
        if row["name"] != name:
            continue
        provenance = row.get("provenance") or {}
        managed = provenance.get("origin_kind") in LOCAL_ORIGIN_KINDS or provenance.get(
            "installed_path") in {str(dest), str(dest.resolve())}
        if managed and (row["version"] != manifest["version"]
                        or provenance.get("computed_sha256") != digest):
            market.registry.remove(name, row["version"])
    market._write_payload(dest, files)
    result = market.register_local(
        name, path=dest, origin_kind=origin_kind, source="local", reason=reason)
    market._rescan()
    return {**result, "saved": True, "skill": name, "path": str(dest)}


@router.get(
    "/api/skills/market/search", dependencies=[Depends(_require_trusted_origin)],
    # A cancelled search returns a bare 499 Response, which FastAPI passes through
    # unvalidated; the declared model keeps the public contract an object.
    response_model=dict[str, Any],
)
async def market_search(
    request: Request,
    q: str = "",
    source: str | None = None,
    limit: int = 20,
) -> Any:
    """Search every enabled market source; failures degrade, never block the UI."""
    search_task = asyncio.create_task(get_market().search(query=q, source=source, limit=limit))
    try:
        while not search_task.done():
            await asyncio.wait({search_task}, timeout=0.1)
            if not search_task.done() and await request.is_disconnected():
                search_task.cancel()
                await asyncio.gather(search_task, return_exceptions=True)
                return Response(status_code=499)
        return await search_task
    except MarketError as exc:
        raise _http_error(exc) from None
    finally:
        if not search_task.done():
            search_task.cancel()
            await asyncio.gather(search_task, return_exceptions=True)


@router.get("/api/skills/market/sources", dependencies=[Depends(_require_trusted_origin)])
async def list_market_sources() -> dict[str, Any]:
    try:
        return get_market().list_sources()
    except MarketError as exc:
        raise _http_error(exc) from None


@router.post("/api/skills/market/sources", dependencies=[Depends(_require_trusted_origin)])
async def add_market_source(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        entry = get_market().add_source(
            str(payload.get("name", "")), str(payload.get("kind", "")),
            path=payload.get("path"), repo=payload.get("repo"),
            tap_path=str(payload.get("tap_path", "skills/")),
            proxy=payload.get("proxy"),
        )
        return {"status": "added", "source": entry}
    except MarketError as exc:
        raise _http_error(exc) from None


@router.delete("/api/skills/market/sources/{name}", dependencies=[Depends(_require_trusted_origin)])
async def remove_market_source(name: str) -> dict[str, Any]:
    try:
        return get_market().remove_source(name)
    except MarketError as exc:
        raise _http_error(exc) from None


@router.post(
    "/api/skills/market/sources/{name}/enable",
    dependencies=[Depends(_require_trusted_origin)],
)
async def enable_market_source(name: str) -> dict[str, Any]:
    try:
        return get_market().set_source_enabled(name, True)
    except MarketError as exc:
        raise _http_error(exc) from None


@router.post(
    "/api/skills/market/sources/{name}/disable",
    dependencies=[Depends(_require_trusted_origin)],
)
async def disable_market_source(name: str) -> dict[str, Any]:
    try:
        return get_market().set_source_enabled(name, False)
    except MarketError as exc:
        raise _http_error(exc) from None


@router.get(
    "/api/skills/market/installed", dependencies=[Depends(_require_trusted_origin)])
async def market_installed() -> dict[str, Any]:
    """Installed-with-provenance view (marketplace + X2/X5 local origins)."""
    try:
        rows = get_market().installed()
        return {"count": len(rows), "skills": rows}
    except MarketError as exc:
        raise _http_error(exc) from None


@router.get(
    "/api/skills/market/provenance/{name}",
    dependencies=[Depends(_require_trusted_origin)],
)
async def market_provenance(name: str) -> dict[str, Any]:
    try:
        record = get_market().provenance(name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
        return record
    except MarketError as exc:
        raise _http_error(exc) from None


@router.get(
    "/api/skills/market/{source}/{skill_id:path}",
    dependencies=[Depends(_require_trusted_origin)],
)
async def market_detail(source: str, skill_id: str) -> dict[str, Any]:
    """Detail + SKILL.md preview + file list for one market candidate.

    Declared after the literal sub-paths above so the ``{skill_id:path}`` catch
    all can never shadow them.
    """
    try:
        return await get_market().detail(source, skill_id)
    except MarketError as exc:
        raise _http_error(exc) from None


@router.post("/api/skills/market/install", dependencies=[Depends(_require_trusted_origin)])
async def market_install(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return await get_market().install(
            str(payload.get("source", "")), str(payload.get("id", "")),
            scope=str(payload.get("scope", "user")),
            overwrite=bool(payload.get("overwrite", False)),
        )
    except MarketError as exc:
        raise _http_error(exc) from None


@router.get("/api/skills/updates", dependencies=[Depends(_require_trusted_origin)])
async def skill_updates(name: str | None = None) -> dict[str, Any]:
    """Update check across installed-with-provenance skills (single state: Registry)."""
    try:
        market = get_market()
        return {
            "count": len(market.installed()),
            "installed": market.installed(),
            "updates": await market.check_updates(name),
        }
    except MarketError as exc:
        raise _http_error(exc) from None


@router.post("/api/skills/market/update", dependencies=[Depends(_require_trusted_origin)])
async def market_update(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return await get_market().update(str(payload.get("name", "")))
    except MarketError as exc:
        raise _http_error(exc) from None


@router.post("/api/skills/market/update-all", dependencies=[Depends(_require_trusted_origin)])
async def market_update_all() -> dict[str, Any]:
    try:
        return await get_market().update_all()
    except MarketError as exc:
        raise _http_error(exc) from None


@router.post(
    "/api/skills/market/{name}/enable",
    dependencies=[Depends(_require_trusted_origin)],
)
async def enable_skill(name: str) -> dict[str, Any]:
    try:
        return get_market().enable(name)
    except MarketError as exc:
        raise _http_error(exc) from None


@router.post(
    "/api/skills/market/{name}/disable",
    dependencies=[Depends(_require_trusted_origin)],
)
async def disable_skill(name: str) -> dict[str, Any]:
    try:
        return get_market().disable(name)
    except MarketError as exc:
        raise _http_error(exc) from None


@router.delete("/api/skills/{name}", dependencies=[Depends(_require_trusted_origin)])  # noqa: E501
async def uninstall_skill_route(name: str) -> dict[str, Any]:
    """Taskbook contract route. No DELETE /api/skills/{name} exists in server.py;
    if one is added there later, remount this as /api/skills/market/{name}."""
    try:
        return get_market().uninstall(name)
    except MarketError as exc:
        raise _http_error(exc) from None


@router.delete("/api/skills/market/{name}", dependencies=[Depends(_require_trusted_origin)])
async def uninstall_skill_market_route(name: str) -> dict[str, Any]:
    """Alias of the DELETE /api/skills/{name} contract at the market prefix —
    the frontend's uninstall call targets this path (skillsMarketApi.ts)."""
    try:
        return get_market().uninstall(name)
    except MarketError as exc:
        raise _http_error(exc) from None


@router.patch("/api/skills/market/{name}/enabled", dependencies=[Depends(_require_trusted_origin)])
async def set_skill_enabled(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """PATCH {enabled: bool} — frontend enable/disable toggle (skillsMarketApi.ts)."""
    enabled = bool((payload or {}).get("enabled", True))
    try:
        market = get_market()
        return market.enable(name) if enabled else market.disable(name)
    except MarketError as exc:
        raise _http_error(exc) from None


__all__ = ["router", "set_market_supplier", "get_market", "save_local_skill_bundle"]
