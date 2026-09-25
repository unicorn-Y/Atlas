"""Atlas Model Manager — manual model selection + LiteLLM unified proxy."""

from __future__ import annotations

import os
from typing import Any

import structlog

from atlas.config import get_config, load_user_settings, save_user_settings

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
        settings = load_user_settings()
        self._models: list[dict[str, Any]] = list(DEFAULT_MODELS)
        custom_models = settings.get("custom_models", [])
        if not isinstance(custom_models, list):
            custom_models = []
        self._current: str = default_model or str(settings.get("selected_model") or cfg.default_model)
        self._favorites: set[str] = {"claude-opus-4", "claude-sonnet-4", "gpt-4o"}
        self._api_base = str(settings.get("gateway_base_url") or cfg.gateway_base_url)
        self._api_key = str(settings.get("api_key") or cfg.gateway_api_key)

        # Config-defined models are loaded but are not copied to user preferences.
        for custom in cfg.custom_models:
            if custom.get("id"):
                self._models.append({**custom, "custom": False})
        for custom in custom_models:
            if custom.get("id") and not any(model["id"] == custom["id"] for model in self._models):
                self.add_model(custom, persist=False)

        # Configure LiteLLM to use gateway
        self._apply_provider_environment()

        log.info("model_manager.init", default=self._current, api_base=self._api_base)

    def _apply_provider_environment(self) -> None:
        if self._api_base:
            os.environ["OPENAI_API_BASE"] = self._api_base
        if self._api_key:
            os.environ["OPENAI_API_KEY"] = self._api_key
            os.environ["ANTHROPIC_API_KEY"] = self._api_key

    @property
    def gateway_base_url(self) -> str:
        return self._api_base

    @property
    def api_key_configured(self) -> bool:
        return bool(self._api_key)

    def update_provider(self, base_url: str, api_key: str | None) -> None:
        self._api_base = base_url.rstrip("/")
        if api_key:
            self._api_key = api_key
        self._apply_provider_environment()
        self._persist_settings()

    def _persist_settings(self) -> None:
        current = load_user_settings()
        current.update({
            "gateway_base_url": self._api_base,
            "api_key": self._api_key,
            "selected_model": self._current,
            "custom_models": [model for model in self._models if model.get("custom")],
        })
        save_user_settings(current)

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
        self._persist_settings()
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

    def add_model(self, model: dict[str, Any], persist: bool = True) -> None:
        """Register a custom model."""
        if any(existing["id"] == model.get("id") for existing in self._models):
            raise ValueError(f"Model already exists: {model.get('id')}")
        self._models.append({**model, "custom": True})
        if persist:
            self._persist_settings()
        log.info("model_manager.add_model", model_id=model.get("id"))
