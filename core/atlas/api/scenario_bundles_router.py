"""HTTP API for user-authored scenario bundles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.skills.scenario_bundles import ScenarioBundleStore

router = APIRouter(prefix="/api/scenario-bundles", tags=["scenario-bundles"])


def _installed_skills(services: AppServices) -> set[str]:
    manager = services.skill_mgr
    if manager is None:
        return set()
    return {str(item.name) for item in manager.list_skills()}


def _memory_collections() -> set[str]:
    try:
        from atlas.memory.library import get_library
        library = get_library()
        if library is None:
            return set()
        return {str(Path(path).parent.as_posix()) for path in library.store.pages()}
    except (OSError, RuntimeError, AttributeError):
        return set()


@router.get("")
async def list_bundles() -> dict[str, Any]:
    try:
        return ScenarioBundleStore().list()
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("")
async def save_bundle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        item = ScenarioBundleStore().save(payload)
        return {"bundle": item, "saved": True}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"保存场景包失败：{exc}") from exc


@router.delete("/{name}")
async def delete_bundle(name: str) -> dict[str, Any]:
    try:
        return ScenarioBundleStore().delete(name)
    except KeyError:
        raise HTTPException(404, "场景包不存在") from None
    except OSError as exc:
        raise HTTPException(500, f"删除场景包失败：{exc}") from exc


@router.post("/{name}/load")
async def load_bundle(name: str, services: AppServices = Depends(get_app_services)) -> dict[str, Any]:
    try:
        result = ScenarioBundleStore().load(name, _installed_skills(services), _memory_collections())
    except KeyError:
        raise HTTPException(404, "场景包不存在") from None
    except (OSError, ValueError) as exc:
        raise HTTPException(500, f"加载场景包失败：{exc}") from exc
    return result


@router.get("/{name}/preview")
async def preview_bundle(name: str, services: AppServices = Depends(get_app_services)) -> dict[str, Any]:
    try:
        return ScenarioBundleStore().preview(name, _installed_skills(services), _memory_collections())
    except KeyError:
        raise HTTPException(404, "场景包不存在") from None
    except (OSError, ValueError) as exc:
        raise HTTPException(500, f"预览场景包失败：{exc}") from exc


@router.post("/unload")
async def unload_bundle() -> dict[str, Any]:
    try:
        return ScenarioBundleStore().unload()
    except (OSError, ValueError) as exc:
        raise HTTPException(500, f"卸载场景包失败：{exc}") from exc
