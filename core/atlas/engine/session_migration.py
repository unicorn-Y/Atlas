"""First-start migration from the retired Atlas message table to Hermes SessionDB."""

from atlas.engine.session_sync import MigrationReport, migrate_legacy_sessions

__all__ = ["MigrationReport", "migrate_legacy_sessions"]
