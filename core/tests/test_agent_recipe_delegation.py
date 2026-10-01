from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from atlas.agent import _render_delegation_recipe


def test_delegation_recipe_renders_required_parameters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("atlas.agent.get_config", lambda: SimpleNamespace(db_path=tmp_path / "atlas.db"))
    recipe = {
        "id": "review",
        "name": "Review",
        "prompt": "Review {{target}}",
        "params": [{"name": "target"}],
    }
    with patch("atlas.task_artifacts.TomlRecordStore.get", return_value=recipe):
        actual, prompt = _render_delegation_recipe({"id": "review", "params": {"target": "core"}})

    assert actual is recipe
    assert prompt == "Review core"


def test_delegation_recipe_rejects_missing_required_parameters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("atlas.agent.get_config", lambda: SimpleNamespace(db_path=tmp_path / "atlas.db"))
    recipe = {
        "id": "review",
        "name": "Review",
        "prompt": "Review {{target}}",
        "params": [{"name": "target"}],
    }
    with patch("atlas.task_artifacts.TomlRecordStore.get", return_value=recipe):
        with pytest.raises(ValueError, match="缺少参数：target"):
            _render_delegation_recipe({"id": "review", "params": {}})
