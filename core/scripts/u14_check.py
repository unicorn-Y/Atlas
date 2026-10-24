from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def check_scoped_config_and_credential_migration() -> None:
    from atlas.config import AtlasConfig
    from atlas.config_migrations import GLOBAL_GATEWAY_KEY, migrate_configuration, rollback_configuration_migration
    from atlas.project_context import project_scope, validate_config_override
    from atlas.project_settings import (
        get_project_gateway_key, get_session_gateway_key, load_project_config,
        save_project_config, set_project_gateway_key, set_session_gateway_key,
    )

    class MemoryKeyring:
        values: dict[str, str] = {}
        def get(self, key): return self.values.get(key)
        def set(self, key, value): self.values[key] = value
        def delete(self, key): self.values.pop(key, None)
    keyring = MemoryKeyring()
    with tempfile.TemporaryDirectory(prefix="atlas-u14-config-") as temp:
        root = Path(temp)
        config, settings = root / "atlas.toml", root / "user-settings.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('[models]\ndefault = "global"\n[models.gateway]\napi_key = "MIGRATION-SECRET"\nbase_url = "https://legacy.test"\n', encoding="utf-8")
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"api_key": "SETTINGS-SECRET", "selected_model": "global"}), encoding="utf-8")
        with patch("atlas.config_migrations._keyring", return_value=keyring):
            result = migrate_configuration(config, settings)
            assert result["config_version"] == 2 and result["settings_version"] == 2
            assert GLOBAL_GATEWAY_KEY in keyring.values
        assert "MIGRATION-SECRET" not in config.read_text(encoding="utf-8")
        assert "SETTINGS-SECRET" not in settings.read_text(encoding="utf-8")
        rollback = rollback_configuration_migration(config, settings)
        assert rollback == {"config": True, "settings": True}
        assert "MIGRATION-SECRET" not in config.read_text(encoding="utf-8")
        assert "SETTINGS-SECRET" not in settings.read_text(encoding="utf-8")

    with patch("atlas.project_settings._credential_store", return_value=keyring):
        save_project_config("alpha", {"models": {"default": "alpha-model", "gateway": {"base_url": "https://alpha.test"}}})
        save_project_config("beta", {"models": {"default": "beta-model"}})
        set_project_gateway_key("alpha", "ALPHA-ONLY")
        set_session_gateway_key("session-a", "SESSION-ONLY")
        assert get_project_gateway_key("alpha") == "ALPHA-ONLY"
        assert get_project_gateway_key("beta") is None
        assert get_session_gateway_key("session-a") == "SESSION-ONLY"
        cfg = AtlasConfig({"models": {"default": "global-model", "gateway": {"base_url": "https://global.test"}}})
        with project_scope("alpha"):
            assert cfg.get("models.default") == "alpha-model"
            assert cfg.gateway_base_url == "https://alpha.test"
        with project_scope("beta"):
            assert cfg.get("models.default") == "beta-model"
            assert cfg.gateway_base_url == "https://global.test"
        with project_scope("alpha", session_id="session-a"):
            assert cfg.get("models.default") == "alpha-model"
            assert get_session_gateway_key("session-a") != get_project_gateway_key("alpha")
        with project_scope("alpha", config_override={"models": {"default": "temporary"}}):
            assert cfg.default_model == "temporary"
        with project_scope("alpha", ignore_project_config=True):
            assert cfg.default_model == "global-model"
    try:
        validate_config_override({"models": {"api_key": "must-reject"}})
    except ValueError:
        pass
    else:
        raise AssertionError("config override accepted secret material")
    print("U14 credentials/config scope and sanitized migration rollback PASS")


def check_openclaw_import() -> None:
    from atlas.runtime.external_import import import_external, scan_external
    with tempfile.TemporaryDirectory(prefix="atlas-u14-openclaw-") as temp:
        root = Path(temp)
        source = root / "home" / ".openclaw"
        source.mkdir(parents=True)
        (source / "openclaw.json").write_text(json.dumps({"tools": {"mcp": {"servers": {
            "fixture": {"command": "fixture-server", "args": ["--stdio"], "env": {"FIXTURE_API_KEY": "SYNTHETIC-KEY"}}
        }}}}), encoding="utf-8")
        ws, atlas = root / "workspace", root / "atlas"
        ws.mkdir()
        manifest = scan_external("openclaw", workspace=ws, atlas_home=atlas, source_home=root / "home")
        mcp = next(item for item in manifest["items"] if item["kind"] == "mcp")
        result = import_external("openclaw", [mcp], workspace=ws, atlas_home=atlas, source_home=root / "home")
        assert result["imported"] == 1
        content = (atlas / "config" / "atlas.toml").read_text(encoding="utf-8")
        assert "SYNTHETIC-KEY" not in content and "{{secret:IMPORT_" in content
        from atlas.tools.mcp_client import resolve_mcp_env
        env, problems = resolve_mcp_env({"FIXTURE_API_KEY": "{{secret:IMPORT_" + content.split("{{secret:IMPORT_", 1)[1].split("}", 1)[0] + "}}"})
        assert not problems and env["FIXTURE_API_KEY"] == "SYNTHETIC-KEY"
        sessions = source / "agents" / "main" / "sessions"
        sessions.mkdir(parents=True)
        history = sessions / "fixture.jsonl"
        history.write_text("\n".join([
            json.dumps({"type": "session", "title": "OpenClaw fixture session"}),
            json.dumps({"type": "message", "message": {"role": "user", "content": "synthetic question", "id": "u1"}}),
            json.dumps({"type": "message", "message": {"role": "assistant", "content": "synthetic answer", "id": "a1"}}),
        ]) + "\n", encoding="utf-8")
        from atlas.runtime.external_import import load_external_history
        with patch.dict(os.environ, {"OPENCLAW_HOME": str(source)}), \
             patch("atlas.runtime.external_import._HISTORY_INDEX_PATH", root / "history-index.json"):
            imported = load_external_history("openclaw")
        assert imported["total_files"] == 1, imported
        assert [row["content"] for row in imported["sessions"][0]["messages"]] == ["synthetic question", "synthetic answer"]
    print("U14 OpenClaw config, text session import and MCP secret resolution PASS")


async def check_remote_access() -> None:
    from atlas.api.app_services import AppServices
    from atlas.api.application import create_app
    from atlas.api.runtime import RunState, RuntimeManager
    from atlas.api.run_drive import _handle_resume
    from atlas.remote_access import remote_token_valid
    from atlas.origin_guard import is_trusted

    class Memory:
        async def list_conversations(self, limit=None):
            return [{"id": "session-one", "title": "Remote test", "workspace": ""}]
    @asynccontextmanager
    async def lifespan(_app):
        yield
    manager = RuntimeManager()
    run = RunState("remote-run", "session-one", "fixture-model")
    run.next_envelope("approval.required", {"approval_id": "approval-one", "description": "Fixture approval", "tool": "write"})
    run.status = "waiting"
    manager.runs[run.run_id] = run
    app = create_app(lifespan=lifespan, services=AppServices(memory=Memory(), runtime_mgr=manager, runtime_resume_handler=_handle_resume))
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        page = client.get("/remote", headers={"Sec-Fetch-Site": "same-origin"})
        assert page.status_code == 200 and "Atlas · Remote" in page.text and "run.steer" in page.text
        grant_response = client.post("/api/remote/access", json={"host": "192.168.10.4", "ttl_seconds": 600})
        assert grant_response.status_code == 200, grant_response.text
        grant = grant_response.json()
        token = grant["url"].split("#", 1)[1]
        assert remote_token_valid(token)
        assert is_trusted(None, token, client_host="192.168.10.9")
        tasks = client.get("/api/remote/tasks", headers={"X-Atlas-Api-Token": token})
        assert tasks.status_code == 200 and tasks.json()[0]["id"] == "session-one"
        assert tasks.json()[0]["run_id"] == "remote-run" and tasks.json()[0]["waiting_for"] == "approval"
        with client.websocket_connect("/ws/chat", subprotocols=["atlas", token]) as ws:
            ws.send_json({"type": "resume", "run_id": "remote-run", "after_sequence": 0})
            replay = ws.receive_json()
            assert replay["event"] == "approval.required" and replay["data"]["approval_id"] == "approval-one"
        assert "#" in grant["url"] and grant["url"].startswith("http://192.168.10.4:")
        stopped = client.post("/api/remote/stop", json={"session_id": grant["session_id"]})
        assert stopped.status_code == 200 and stopped.json()["revoked"] == 1
        assert not remote_token_valid(token)
    print("U14 mobile remote URL, external bearer auth, task list and revocation PASS")


def check_bot_loop_and_page_find() -> None:
    from atlas.channels.contract import MessageEvent, MessageType
    from atlas.channels.ingress import IngressQueue, event_from_payload, event_to_payload
    with tempfile.TemporaryDirectory(prefix="atlas-u14-bot-") as temp:
        queue = IngressQueue(Path(temp) / "ingress.sqlite")
        first = MessageEvent(channel="webhook", account="one", event_id="1", chat_id="room", sender_id="bot", kind=MessageType.TEXT, text="hello", sender_is_bot=True, causal_id="cause", bot_depth=1)
        restored = event_from_payload(event_to_payload(first))
        assert restored.sender_is_bot and restored.causal_id == "cause" and restored.bot_depth == 1
        ok, _ = queue.admit_bot_event(first, now=1000)
        assert ok
        duplicate = MessageEvent(channel="webhook", account="one", event_id="2", chat_id="room", sender_id="bot", kind=MessageType.TEXT, text="hello", sender_is_bot=True)
        ok, reason = queue.admit_bot_event(duplicate, now=1001)
        assert not ok and "repeated" in reason
        separate_chat = MessageEvent(channel="webhook", account="one", event_id="other", chat_id="different-room", sender_id="bot", kind=MessageType.TEXT, text="hello", sender_is_bot=True)
        assert queue.admit_bot_event(separate_chat, now=1002)[0]
        queue.record_outbound_bot_content("echo", channel="webhook", account="one", chat_id="room", now=1000)
        echo = MessageEvent(channel="webhook", account="one", event_id="3", chat_id="room", sender_id="bot", kind=MessageType.TEXT, text="echo", sender_is_bot=True)
        ok, reason = queue.admit_bot_event(echo, now=1001)
        assert not ok and "echo" in reason
        too_deep = MessageEvent(channel="webhook", account="one", event_id="4", chat_id="room", sender_id="bot", text="deep", sender_is_bot=True, bot_depth=3)
        assert not queue.admit_bot_event(too_deep, now=1002)[0]
        queue.close()
    source = Path("frontend/src/renderer/shell/panels/BrowserPanel.tsx").read_text(encoding="utf-8")
    assert "findInPage(query" in source and "stopFindInPage('clearSelection')" in source
    assert "browser:find" in Path("frontend/src/main/electron.ts").read_text(encoding="utf-8")
    print("U14 Bot echo/repetition/depth controls and page find bindings PASS")


def main() -> None:
    check_scoped_config_and_credential_migration()
    check_openclaw_import()
    asyncio.run(check_remote_access())
    check_bot_loop_and_page_find()
    print("U14 CHECK PASS")


if __name__ == "__main__":
    main()
