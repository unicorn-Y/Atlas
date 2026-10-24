"""Local named secrets API; secret values are write-only except to child processes."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from atlas import secrets_store

router = APIRouter(prefix="/api/secrets", tags=["secrets"])

class SecretInput(BaseModel):
    name: str
    value: str
    description: str = ""
    scope: str = "global"

@router.get("")
async def list_secrets() -> dict[str, Any]: return {"secrets": secrets_store.list_secrets()}

@router.put("")
async def put_secret(req: SecretInput) -> dict[str, Any]:
    try: return secrets_store.set_secret(req.name, req.value, req.description, req.scope)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc

@router.delete("/{name}")
async def remove_secret(name: str) -> dict[str, bool]: return {"deleted": secrets_store.delete_secret(name)}

@router.post("/{name}/reveal")
async def reveal_secret(name: str) -> dict[str, str]:
    value = secrets_store.reveal_secret(name)
    if value is None: raise HTTPException(404, "Secret not found")
    return {"value": value}
