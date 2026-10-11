"""User-authored parameterized recipe templates; the UI owns the session launch.

Behavior reference: Goose session recipes and recipe reference:
https://goose-docs.ai/docs/guides/recipes/session-recipes/
https://goose-docs.ai/docs/guides/recipes/recipe-reference/
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.config import load_user_settings, save_user_settings

router = APIRouter(tags=["recipe-templates"])


class RecipeParameter(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = False
    default: Any = None


class RecipePayload(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    prompt: str = Field(min_length=1, max_length=50000)
    parameters: list[RecipeParameter] = Field(default_factory=list, max_length=100)
    provider_id: str = ""
    model_id: str = ""
    allowed_extension_ids: list[str] = Field(default_factory=list, max_length=200)
    activity_button_label: str = Field(default="Start recipe", max_length=80)
    output_shape: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _recipes() -> list[dict[str, Any]]:
    value = load_user_settings().get("recipe_templates", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _save(recipes: list[dict[str, Any]]) -> None:
    settings = load_user_settings()
    settings["recipe_templates"] = recipes
    save_user_settings(settings)


@router.get("/api/recipe-templates")
async def list_recipes() -> dict[str, Any]:
    return {"recipes": _recipes()}


@router.post("/api/recipe-templates")
async def create_recipe(payload: RecipePayload) -> dict[str, Any]:
    recipes = _recipes()
    if any(item.get("id") == payload.id for item in recipes):
        raise HTTPException(status_code=409, detail="Recipe ID already exists")
    row = payload.model_dump(mode="json")
    recipes.append(row)
    _save(recipes)
    return row


@router.put("/api/recipe-templates/{recipe_id}")
async def update_recipe(recipe_id: str, payload: RecipePayload) -> dict[str, Any]:
    if payload.id != recipe_id:
        raise HTTPException(status_code=422, detail="Recipe ID must match the URL")
    recipes = _recipes()
    for index, item in enumerate(recipes):
        if item.get("id") == recipe_id:
            row = payload.model_dump(mode="json")
            recipes[index] = row
            _save(recipes)
            return row
    raise HTTPException(status_code=404, detail="Recipe not found")


@router.delete("/api/recipe-templates/{recipe_id}")
async def delete_recipe(recipe_id: str) -> dict[str, Any]:
    recipes = _recipes()
    kept = [item for item in recipes if item.get("id") != recipe_id]
    if len(kept) == len(recipes):
        raise HTTPException(status_code=404, detail="Recipe not found")
    _save(kept)
    return {"id": recipe_id, "deleted": True}
