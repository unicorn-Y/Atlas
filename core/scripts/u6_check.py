"""Focused U6 checks that never launch Electron or access configured credentials."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from atlas.api import u6_router
from atlas.api.app_services import AppServices


class _Db:
    async def execute(self, _sql: str) -> None:
        return None


class _Memory:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.deleted: list[str] = []
        self.archived: list[str] = []
        self._db = _Db()

    async def list_conversations(self, limit=None):
        return list(self.rows)

    async def delete_conversation(self, conversation_id: str) -> bool:
        self.deleted.append(conversation_id)
        return True

    async def update_conversation(self, conversation_id: str, *, archived: bool) -> bool:
        self.archived.append(conversation_id)
        return True


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u6-check-") as temp:
        root = Path(temp); data = root / "data"; data.mkdir()
        config = SimpleNamespace(db_path=data / "atlas.db")
        settings_path = data / "user-settings.json"
        memory = _Memory()
        services = AppServices(memory=memory, projects=None)
        with patch("atlas.config.DATA_ROOT", root), patch("atlas.config.USER_SETTINGS_PATH", settings_path), patch("atlas.config.get_config", return_value=config):
            (root / "logs").mkdir(); (root / "logs" / "sample.log").write_text("log", encoding="utf-8")
            measured = await u6_router.storage_usage()
            assert {entry["id"] for entry in measured["categories"]} == {"sessions", "logs", "artifacts", "cache", "snapshots", "models"}
            assert next(entry for entry in measured["categories"] if entry["id"] == "logs")["bytes"] == 3
            result = await u6_router.clear_storage("logs", {"confirm": True}, services)
            assert result["released_bytes"] == 3 and not (root / "logs").exists()
            await u6_router.clear_storage("sessions", {"confirm": True}, services)

            saved = await u6_router.put_retention({"days": 30, "action": "archive", "exclude_pinned": True, "exclude_projects": True})
            assert saved["days"] == 30 and saved["action"] == "archive"
            memory.rows = [{"id": "old", "updated_at": "2000-01-01 00:00:00", "pinned": False, "archived": False}]
            u6_router._last_retention_sweep = 0
            cleaned = await u6_router.run_retention(services)
            assert cleaned["affected"] == 1 and memory.archived == ["old"]

            result = await u6_router.put_keybindings({"bindings": {"palette": ["Ctrl+K"], "stopRun": []}})
            assert result["bindings"]["stopRun"] == []
            loaded = await u6_router.get_keybindings()
            assert loaded["bindings"]["palette"] == ["Ctrl+K"]
            (data / "keybindings.json").write_text("{broken", encoding="utf-8")
            try:
                await u6_router.get_keybindings()
                raise AssertionError("malformed keybindings should return 422")
            except HTTPException as exc:
                assert exc.status_code == 422

            catalog_source = (Path(__file__).parents[1] / "atlas" / "agent" / "tool_catalog.py").read_text(encoding="utf-8")
            assert '"name": "send_to_session"' in catalog_source and '"name": "read_session"' in catalog_source
            workspace = root / "workspace"; workspace.mkdir(); (workspace / "app.py").write_text("print('ok')", encoding="utf-8")
            environment = await u6_router.workspace_environment(str(workspace))
            assert "Python" in environment["languages"]

        assert (await u6_router.whatsnew())["source"] in {"git", "CHANGELOG.md"}

    print("U6 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
