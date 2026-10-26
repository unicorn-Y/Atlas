"""Local pet package catalog and active-pet API."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.responses import FileResponse

from atlas.pet_store import PetPackageError, PetStore

router = APIRouter(prefix="/api/pets", tags=["pets"])
_store = PetStore()


class HatchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    emoji: str = Field(default="🐾", max_length=8)
    color: str = Field(default="#8277f4", max_length=7)


@router.get("")
def list_pets() -> dict:
    result = _store.list()
    for pet in result["pets"]:
        if pet.get("avatar"):
            pet["avatar_url"] = f"/api/pets/{pet['id']}/avatar"
    return result


@router.post("/hatch")
def hatch_pet(body: HatchRequest) -> dict:
    try:
        return {"pet": _store.hatch(body.name, body.emoji, body.color), **_store.list()}
    except PetPackageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/install")
async def install_pet(file: Annotated[UploadFile, File()]) -> dict:
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="请选择 ZIP 格式的宠物包")
    raw = await file.read(50 * 1024 * 1024 + 1)
    try:
        pet = _store.install_archive(raw)
    except PetPackageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"pet": pet, **_store.list()}


@router.put("/{pet_id}/active")
def activate_pet(pet_id: str) -> dict:
    try:
        pet = _store.activate(pet_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"pet": pet, **_store.list()}


@router.delete("/{pet_id}")
def remove_pet(pet_id: str) -> dict:
    try:
        _store.remove(pet_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PetPackageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _store.list()


@router.get("/{pet_id}/avatar")
def pet_avatar(pet_id: str) -> FileResponse:
    path = _store.avatar_path(pet_id)
    if path is None:
        raise HTTPException(status_code=404, detail="这只宠物没有可用头像")
    return FileResponse(path)
