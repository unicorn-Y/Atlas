"""Tests for AtlasConfig — TOML loading and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.config import AtlasConfig, load_config


class TestAtlasConfigDefaults:
    """When no TOML file exists, sensible defaults should work."""

    def test_defaults(self) -> None:
        cfg = AtlasConfig()
        assert cfg.server_host == "0.0.0.0"
        assert cfg.server_port == 8765
        assert cfg.default_model == "claude-sonnet-4"
        assert cfg.max_context_messages == 50
        assert cfg.log_level == "INFO"
        assert cfg.scheduler_enabled is True
        assert cfg.scheduler_timezone == "Asia/Shanghai"

    def test_get_missing_key_returns_default(self) -> None:
        cfg = AtlasConfig()
        assert cfg.get("totally.missing.key", 42) == 42


class TestAtlasConfigFromData:
    """Test with explicit data dict (simulates parsed TOML)."""

    def test_overrides(self) -> None:
        data = {
            "server": {"host": "127.0.0.1", "port": 9999},
            "models": {"default": "gpt-4o"},
            "memory": {"db_path": "/tmp/test.db", "max_context_messages": 100},
            "logging": {"level": "DEBUG"},
        }
        cfg = AtlasConfig(data)
        assert cfg.server_host == "127.0.0.1"
        assert cfg.server_port == 9999
        assert cfg.default_model == "gpt-4o"
        assert cfg.max_context_messages == 100
        assert cfg.log_level == "DEBUG"

    def test_db_path_absolute(self) -> None:
        cfg = AtlasConfig({"memory": {"db_path": "/absolute/path/test.db"}})
        assert cfg.db_path == Path("/absolute/path/test.db")

    def test_db_path_relative(self) -> None:
        cfg = AtlasConfig({"memory": {"db_path": "./data/test.db"}})
        # Should be resolved relative to PROJECT_ROOT
        assert cfg.db_path.is_absolute()
        assert str(cfg.db_path).endswith("data/test.db") or str(cfg.db_path).endswith("data\\test.db")


class TestLoadConfig:
    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        # No example file to copy either
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.server_port == 8765  # defaults

    def test_load_from_file(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(
            '[server]\nhost = "localhost"\nport = 7777\n'
            '[models]\ndefault = "deepseek-v3"\n'
        )
        cfg = load_config(toml_file)
        assert cfg.server_host == "localhost"
        assert cfg.server_port == 7777
        assert cfg.default_model == "deepseek-v3"
