"""Tests for AtlasConfig — TOML loading and defaults."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tzlocal import get_localzone_name

from atlas.config import AtlasConfig, load_config


class TestAtlasConfigDefaults:
    """When no TOML file exists, sensible defaults should work."""

    def test_defaults(self, monkeypatch) -> None:
        # The isolated suite disables real scheduler startup globally; this
        # case checks the configuration default without its environment override.
        monkeypatch.delenv("ATLAS_SCHEDULER_ENABLED", raising=False)
        cfg = AtlasConfig()
        assert cfg.server_host == "0.0.0.0"
        assert cfg.server_port == 8765
        assert cfg.default_model == "claude-sonnet-4"
        assert cfg.max_context_messages == 50
        assert cfg.log_level == "INFO"
        # P10: legacy APScheduler is opt-in; DBOS automation is the default owner.
        assert cfg.scheduler_enabled is False
        assert cfg.scheduler_timezone == "Asia/Shanghai"
        assert cfg.context_maintenance_message_limit == 80
        assert cfg.context_maintenance_character_limit == 80000
        assert cfg.trajectory_reviewer_enabled is False

    def test_user_timezone_defaults_to_system_iana_timezone(self) -> None:
        cfg = AtlasConfig()

        assert getattr(cfg, "user_timezone", None) == get_localzone_name()

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
            "agent": {
                "context_maintenance": {"message_limit": 12, "character_limit": 4000},
                "trajectory_reviewer": {
                    "enabled": True, "backend": "litellm", "model": "openai/gpt-4o-mini",
                },
            },
            "logging": {"level": "DEBUG"},
        }
        cfg = AtlasConfig(data)
        assert cfg.server_host == "127.0.0.1"
        assert cfg.server_port == 9999
        assert cfg.default_model == "gpt-4o"
        assert cfg.max_context_messages == 100
        assert cfg.context_maintenance_message_limit == 12
        assert cfg.context_maintenance_character_limit == 4000
        assert cfg.trajectory_reviewer_enabled is True
        assert cfg.trajectory_reviewer_backend == "litellm"
        assert cfg.trajectory_reviewer_model == "openai/gpt-4o-mini"
        assert cfg.log_level == "DEBUG"

    def test_db_path_absolute(self) -> None:
        absolute_path = (Path.cwd() / "absolute" / "path" / "test.db").resolve()
        cfg = AtlasConfig({"memory": {"db_path": str(absolute_path)}})
        assert cfg.db_path == absolute_path

    def test_db_path_relative(self) -> None:
        cfg = AtlasConfig({"memory": {"db_path": "./data/test.db"}})
        # Should be resolved relative to PROJECT_ROOT
        assert cfg.db_path.is_absolute()
        assert (
            str(cfg.db_path).endswith("data/test.db")
            or str(cfg.db_path).endswith("data\\test.db")
        )

    def test_user_timezone_prefers_configured_iana_zone_with_dst_rules(self) -> None:
        cfg = AtlasConfig({"user": {"timezone": "America/New_York"}})

        assert getattr(cfg, "user_timezone", None) == "America/New_York"
        zone = ZoneInfo(cfg.user_timezone)
        assert datetime(2026, 1, 1, tzinfo=zone).utcoffset().total_seconds() == -5 * 3600
        assert datetime(2026, 7, 1, tzinfo=zone).utcoffset().total_seconds() == -4 * 3600


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
