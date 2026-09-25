"""Atlas Model Manager — manual model selection + LiteLLM unified proxy."""

from __future__ import annotations

import os
from typing import Any

import structlog

from atlas.config import get_config

log = structlog.get_logger()

# Default model configurations
DEFAULT_MODELS: list[dict[str, Any]] = [
    {
        "id": "claude-opus-4",
        "name": "Claude Opus 4",
        "provider": "anthropic",
        "litellm_model": "anthropic/claude-opus-4-20250514",
        "category": "flagship",
    },
    {
        "id": "claude-sonnet-4",
        "name": "Claude Sonnet 4",
        "provider": "anthropic",
        "litellm_model": "anthropic/claude-sonnet-4-20250514",
        "category": "balanced",
    },
    {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "litellm_model": "openai/gpt-4o",
        "category": "balanced",
    },
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "openai",
        "litellm_model": "openai/gpt-4o-mini",
        "category": "fast",
    },
    {
        "id": "claude-haiku-3.5",
        "name": "Claude 3.5 Haiku",
        "provider": "anthropic",
        "litellm_model": "anthropic/claude-3-5-haiku-20241022",
        "category": "fast",
    },
    {
        "id": "deepseek-v3",
        "name": "DeepSeek V3",
        "provider": "deepseek",
        "litellm_model": "deepseek/deepseek-chat",
        "category": "balanced",
    },
    {
        "id": "deepseek-r1",
        "name": "DeepSeek R1",
        "provider": "deepseek",
        "litellm_model": "deepseek/deepseek-reasoner",
        "category": "reasoning",
    },
]


class ModelManager:
    """Manages available models and the user's current selection.

    No auto-routing — the user picks the model manually.
    LiteLLM handles the actual API call unification.
    """

    def __init__(self, default_model: str | None = None) -> None:
        cfg = get_config()
        self._models: list[dict[str, Any]] = list(DEFAULT_MODELS)
        self._current: str = default_model or cfg.default_model
        self._favorites: set[str] = {"claude-opus-4", "claude-sonnet-4", "gpt-4o"}

        # Register custom models from config
        for custom in cfg.custom_models:
            if custom.get("id"):
                self._models.append(custom)

        # Configure LiteLLM to use gateway
        api_base = cfg.gateway_base_url
        api_key = cfg.gateway_api_key

        if api_base:
            os.environ.setdefault("OPENAI_API_BASE", api_base)
        if api_key:
            os.environ.setdefault("OPENAI_API_KEY", api_key)
            os.environ.setdefault("ANTHROPIC_API_KEY", api_key)

        log.info("model_manager.init", default=self._current, api_base=api_base)

    @property
    def current_model(self) -> str:
        return self._current

    @property
    def current_litellm_model(self) -> str:
        """Return the LiteLLM model string for the currently selected model."""
        for m in self._models:
            if m["id"] == self._current:
                return m["litellm_model"]
        return self._current  # fallback: use raw ID

    def select(self, model_id: str) -> None:
        """Switch the active model."""
        valid_ids = {m["id"] for m in self._models}
        if model_id not in valid_ids:
            raise ValueError(f"Unknown model: {model_id}. Available: {valid_ids}")
        self._current = model_id
        log.info("model_manager.select", model=model_id)

    def list_models(self) -> list[dict[str, Any]]:
        """Return all available models with favorite status."""
        result = []
        for m in self._models:
            result.append({
                **m,
                "favorite": m["id"] in self._favorites,
                "selected": m["id"] == self._current,
            })
        # Favorites first, then alphabetical
        result.sort(key=lambda x: (not x["favorite"], x["name"]))
        return result

    def add_favorite(self, model_id: str) -> None:
        self._favorites.add(model_id)

    def remove_favorite(self, model_id: str) -> None:
        self._favorites.discard(model_id)

    def add_model(self, model: dict[str, Any]) -> None:
        """Register a custom model."""
        self._models.append(model)
        log.info("model_manager.add_model", model_id=model.get("id"))
