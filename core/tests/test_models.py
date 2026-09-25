"""Tests for ModelManager — model selection, listing, favorites."""

from __future__ import annotations

import os

import pytest

from atlas.models import ModelManager


@pytest.fixture
def mgr() -> ModelManager:
    """Create a ModelManager with default settings."""
    # Ensure env vars don't interfere
    return ModelManager(default_model="claude-sonnet-4")


class TestModelSelection:
    def test_default_model(self, mgr: ModelManager) -> None:
        assert mgr.current_model == "claude-sonnet-4"

    def test_select_valid(self, mgr: ModelManager) -> None:
        mgr.select("gpt-4o")
        assert mgr.current_model == "gpt-4o"

    def test_select_invalid_raises(self, mgr: ModelManager) -> None:
        with pytest.raises(ValueError, match="Unknown model"):
            mgr.select("nonexistent-model")

    def test_current_litellm_model(self, mgr: ModelManager) -> None:
        mgr.select("claude-opus-4")
        assert mgr.current_litellm_model == "anthropic/claude-opus-4-20250514"

        mgr.select("deepseek-v3")
        assert mgr.current_litellm_model == "deepseek/deepseek-chat"


class TestModelListing:
    def test_list_returns_all(self, mgr: ModelManager) -> None:
        models = mgr.list_models()
        ids = {m["id"] for m in models}
        assert "claude-opus-4" in ids
        assert "claude-sonnet-4" in ids
        assert "gpt-4o" in ids
        assert "gpt-4o-mini" in ids
        assert "claude-haiku-3.5" in ids
        assert "deepseek-v3" in ids
        assert "deepseek-r1" in ids

    def test_selected_flag(self, mgr: ModelManager) -> None:
        mgr.select("gpt-4o")
        models = mgr.list_models()
        selected = [m for m in models if m["selected"]]
        assert len(selected) == 1
        assert selected[0]["id"] == "gpt-4o"

    def test_favorites_first(self, mgr: ModelManager) -> None:
        """Favorites should appear before non-favorites."""
        models = mgr.list_models()
        fav_indices = [i for i, m in enumerate(models) if m["favorite"]]
        non_fav_indices = [i for i, m in enumerate(models) if not m["favorite"]]
        if fav_indices and non_fav_indices:
            assert max(fav_indices) < min(non_fav_indices)


class TestFavorites:
    def test_add_favorite(self, mgr: ModelManager) -> None:
        mgr.add_favorite("deepseek-v3")
        models = mgr.list_models()
        ds = next(m for m in models if m["id"] == "deepseek-v3")
        assert ds["favorite"] is True

    def test_remove_favorite(self, mgr: ModelManager) -> None:
        mgr.remove_favorite("gpt-4o")
        models = mgr.list_models()
        gpt = next(m for m in models if m["id"] == "gpt-4o")
        assert gpt["favorite"] is False


class TestCustomModels:
    def test_add_model(self, mgr: ModelManager) -> None:
        mgr.add_model({
            "id": "local-llama",
            "name": "Local Llama 3.1",
            "provider": "ollama",
            "litellm_model": "ollama/llama3.1",
            "category": "local",
        })
        models = mgr.list_models()
        ids = {m["id"] for m in models}
        assert "local-llama" in ids

        # Should be selectable
        mgr.select("local-llama")
        assert mgr.current_model == "local-llama"
        assert mgr.current_litellm_model == "ollama/llama3.1"
