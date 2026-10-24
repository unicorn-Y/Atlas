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
from atlas.projects import ProjectStore


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

            projects = ProjectStore(data / "projects.db")
            await projects.init()
            project = await projects.create_project("U6 临时项目", str(workspace), color="#7654AB", default_model="deepseek-v4.1-flash")
            await projects.attach_conversation(project.project_id, "u6-check-conversation")
            assert (await projects.find_by_conversation("u6-check-conversation")).project_id == project.project_id
            assert await projects.list_conversations(project.project_id) == ["u6-check-conversation"]
            assert await projects.delete_project(project.project_id)
            assert await projects.find_by_conversation("u6-check-conversation") is None
            await projects.close()

            repo = Path(__file__).parents[2]
            app_source = (repo / "frontend" / "src" / "renderer" / "App.tsx").read_text(encoding="utf-8")
            composer_source = (repo / "frontend" / "src" / "renderer" / "components" / "Composer.tsx").read_text(encoding="utf-8")
            browser_source = (repo / "core" / "atlas" / "api" / "browser_router.py").read_text(encoding="utf-8")
            assert "/api/mcp/resources/read" in app_source and "kind: 'resource'" in app_source
            assert "atlas.input-stash." in composer_source and "vimEnabled" in composer_source
            assert "queuedRecovery" in app_source and "failedRun" in app_source
            assert '"/recordings/{recording_id}/steps"' in browser_source

        assert (await u6_router.whatsnew())["source"] in {"git", "git+model", "CHANGELOG.md"}

    # One real, low-cost suggestions request through the configured DeepSeek route.
    from atlas.models import ModelManager
    manager = ModelManager()
    services = AppServices(model_mgr=manager, orchestrator=SimpleNamespace(_model_router=manager.model_router))
    with patch.object(u6_router, "load_user_settings", return_value={"compression_model": "deepseek-v4.1-flash"}):
        try:
            generated = await u6_router.generate_suggestions(services, {
                "goal": "看看 core/atlas/api/u6_router.py 有没有明显问题",
                "response": "读完了 u6_router.py：whatsnew 写死只认 U1~U6 提交；storage 清理会话会删除全部会话；"
                            "suggestions 失败时直接抛 502。还没有改代码，也没有对应的测试。",
            })
            trivial = await u6_router.generate_suggestions(services, {"goal": "你好", "response": "你好！有什么可以帮你？"})
        except HTTPException as exc:
            raise RuntimeError(f"real suggestions request failed ({exc.status_code})") from None
    assert len(generated["suggestions"]) >= 2, "real suggestions response returned fewer than two items"
    assert not any(item.strip("。") in u6_router._GENERIC_SUGGESTIONS for item in generated["suggestions"]), generated
    assert len(trivial["suggestions"]) == 0, f"greeting should not produce suggestions: {trivial}"

    print("U6 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
