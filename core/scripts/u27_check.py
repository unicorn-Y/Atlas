"""Acceptance scenarios for U27. Uses temporary memory stores and a fake Slack exchange."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))


def check_item_0() -> None:
    from atlas.tools.mcp_client import MCPClient, MCPServerConfig

    dashboard = (CORE / "atlas" / "api" / "dashboard_router.py").read_text(encoding="utf-8")
    run_drive = (CORE / "atlas" / "api" / "run_drive.py").read_text(encoding="utf-8")
    assert "window.addEventListener('hashchange'" in dashboard
    assert "sessionStorage.removeItem(tokenKey)" in dashboard
    assert "设置→诊断中重新点击“打开本地控制台”" in dashboard
    assert 'wait_ready("mcp"' not in run_drive

    async def scene() -> None:
        client = MCPClient()
        attempts = 0

        async def fail_start(_cfg, _handle):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("synthetic missing MCP executable")

        client._connect_stdio = fail_start  # type: ignore[method-assign]
        cfg = MCPServerConfig(name="u27-missing", command="missing-u27-command")
        try:
            await client._connect_server(cfg)
        except RuntimeError:
            pass
        await client._connect_server(cfg)
        assert attempts == 1, "identical failed MCP config bypassed its cooldown"
        try:
            await client.restart_server(cfg.name)
        except RuntimeError:
            pass
        assert attempts == 2, "explicit restart must retry even after failed initial startup"
        changed = MCPServerConfig(name=cfg.name, command="changed-u27-command")
        try:
            await client._connect_server(changed)
        except RuntimeError:
            pass
        assert attempts == 3, "edited MCP config must bypass cooldown"

    asyncio.run(scene())


def check_item_1() -> None:
    from atlas.api import memory_library_router as router
    from atlas.memory.library import MemoryLibrary
    from atlas.memory.library.store import Entry

    with tempfile.TemporaryDirectory(prefix="atlas-u27-journey-") as temp:
        library = MemoryLibrary(Path(temp) / "memory")
        library.ready()
        library.add_entry("我.md", "周末喜欢骑自行车。")
        page = library.store.read("我.md")
        page.current.append(Entry(text="迁移工具已验证。", id="u27-episode", at="2026-01-03T12:00:00+00:00", src="经历"))
        library.store.write(page)
        (library.store.root / "journey.jsonl").write_text(json.dumps({
            "id": "u27-skill", "kind": "skill", "at": "2026-01-04T12:00:00+00:00",
            "title": "学习到技能：测试", "text": "留出验证通过", "path": "C:/learned/SKILL.md",
            "source": "SkillOpt-Sleep",
        }) + "\n", encoding="utf-8")
        library.index.sync()
        with patch.object(router, "_lib", return_value=library):
            memories = asyncio.run(router.journey(kind="memory", limit=10))
            skills = asyncio.run(router.journey(kind="skill", limit=10))
            page_one = asyncio.run(router.journey(limit=1))
            page_two = asyncio.run(router.journey(before=page_one["next"], limit=1))
        assert memories["items"] and all(row["kind"] == "memory" for row in memories["items"])
        assert skills["items"][0]["id"] == "u27-skill"
        assert page_one["next"] and page_two["items"] and page_one["items"][0]["id"] != page_two["items"][0]["id"]
        if library.index._db is not None:
            library.index._db.close()


def check_item_2() -> None:
    import httpx
    from fastapi import HTTPException
    from atlas.api import channel_router as router

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "ok": True, "scope": ",".join(sorted(router._SLACK_BOT_SCOPES)),
                "access_token": "xoxb-u27-fake", "team": {"name": "U27 Test Workspace"},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url: str, data: dict[str, str]):
            assert url == "https://slack.com/api/oauth.v2.access"
            assert data["client_secret"] == "u27-fake-client-secret"
            return Response()

    class Manager:
        def __init__(self):
            self.saved: dict[tuple[str, str], str] = {}
            self.enabled = False
            self.credentials = self

        def set(self, channel: str, name: str, value: str) -> None:
            self.saved[(channel, name)] = value

        def configure(self, channel: str, config: dict[str, object]) -> None:
            self.enabled = channel == "slack" and config.get("enabled") is True

        async def restart_channel(self, channel: str) -> None:
            assert channel == "slack"

        def status(self) -> dict[str, object]:
            return {"channels": [{"name": "slack", "enabled": self.enabled, "running": False}]}

    async def scene() -> None:
        router._slack_oauth_states.clear()
        manager = Manager()

        def get_secret(_channel: str, field: str) -> str | None:
            return "u27-fake-client-secret" if field == "oauth_client_secret" else None

        with patch("atlas.channels.adapters._vendor.credentials_bridge.get_channel_secret", get_secret), \
                patch.object(router, "get_channel_manager", return_value=manager), \
                patch.object(httpx, "AsyncClient", FakeClient):
            started = await router.slack_oauth_start(router.SlackOAuthStart(
                client_id="u27-client-id",
                redirect_uri="http://127.0.0.1:8765/api/channels/slack/oauth/callback",
            ))
            params = parse_qs(urlparse(started["url"]).query)
            state = params["state"][0]
            assert set(params["scope"][0].split(",")) == router._SLACK_BOT_SCOPES
            result = await router.slack_oauth_callback(code="u27-code", state=state)
            assert result["ok"] is True and result["enabled"] is True
            assert manager.saved[("slack", "bot_token")] == "xoxb-u27-fake"
            try:
                await router.slack_oauth_callback(code="u27-code", state=state)
            except HTTPException as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError("Slack OAuth state was reusable")


def check_item_3() -> None:
    app = (ROOT / "frontend" / "src" / "renderer" / "App.tsx").read_text(encoding="utf-8")
    composer = (ROOT / "frontend" / "src" / "renderer" / "components" / "Composer.tsx").read_text(encoding="utf-8")
    main = (ROOT / "frontend" / "src" / "main" / "electron.ts").read_text(encoding="utf-8")
    assert "id: 'voice'" in app and "if (voiceOpen) { setVoiceOpen(false); return; }" in app
    assert "speech-auto-send" in app and "speech-input-mode" in app
    assert "stopSpeechInput" in app and "ended" in app
    assert "onPointerDown" in composer and "onPointerUp" in composer
    assert "triggerVoiceShortcut" in main and "app:voice-hotkey" in main


def check_item_4() -> None:
    from atlas.memory.bench import run_memory_benchmark

    result = run_memory_benchmark(ks=(1, 3, 5))
    assert result["case_count"] == 5
    assert result["averages"]["answer_hit_at_1"] >= 0.8
    assert result["averages"]["recall_at_1"] >= 0.8


def check_item_5() -> None:
    from atlas.agent.run_phases import _extract_memory_citations
    from atlas.engine.session_sync import (
        append_session_message, latest_session_message_id,
        read_session_messages, update_session_assistant_message,
    )

    with tempfile.TemporaryDirectory(prefix="atlas-u27-citations-") as temp:
        root = Path(temp)
        raw = "答案是燕麦奶。 <!-- atlas-memory-citations: u27-valid, invented -->"
        clean, refs = _extract_memory_citations(raw, ["u27-valid"])
        assert clean == "答案是燕麦奶。" and refs == ["u27-valid"]
        append_session_message(root, "u27-citation-session", "assistant", raw)
        message_id = latest_session_message_id(root, "u27-citation-session", role="assistant")
        assert message_id and update_session_assistant_message(
            root, "u27-citation-session", message_id, content=clean,
            metadata_patch={"memory_citations": refs},
        )
        message = read_session_messages(root, "u27-citation-session")[-1]
        assert message["content"] == clean
        assert message["metadata"]["memory_citations"] == ["u27-valid"]

    # Verify a real model turn against an isolated memory entry. Disable only
    # the unrelated background vector worker in this fixture so its SQLite
    # handle cannot race the temporary test's index lifecycle.
    from atlas.memory.library import get_library
    from atlas.memory.library.store import Entry
    from atlas.engine.session_sync import append_session_message

    library = get_library()
    if library is None:
        raise AssertionError("memory library is disabled in the regression configuration")
    library.index._schedule_embeddings = lambda: None
    library.ready()
    memory_rel = "人/U27-fixture.md"
    memory_path = library.store.root / memory_rel
    original_page = memory_path.read_bytes() if memory_path.exists() else None
    marker = "U27 cobalt lantern personal fact"
    conversation_id = "u27-source-" + os.urandom(5).hex()
    at = datetime.now().astimezone().isoformat(timespec="seconds")
    citation_ref = f"{conversation_id}@{at}"
    entry = Entry(text=f"The U27 personal fact is cobalt lantern ({marker}).",
                  id="u27-live-citation", ref=citation_ref, at=at)
    try:
        data_root = Path(os.environ.get("ATLAS_DATA_DIR", os.environ["ATLAS_ROOT"]))
        append_session_message(data_root / "engine", conversation_id, "user",
                               "Synthetic U27 citation source.")
        append_session_message(data_root / "engine", conversation_id, "assistant",
                               "Synthetic U27 source confirmation.")
        page = library.store.read(memory_rel)
        page.aliases = ["U27 cobalt lantern personal fact"]
        page.current.append(entry)
        library.store.write(page)
        library.index.sync()
        prompt = "I told you before about U27 cobalt lantern personal fact. What exact object and color did I tell you?"
        recalled = library.recall(prompt)
        assert citation_ref in recalled["refs"], "isolated fixture was not recalled for the real model turn"
        if library.index._db is not None:
            library.index._db.close()
            library.index._db = None
        env = os.environ.copy()
        env["ATLAS_ROOT"] = str(ROOT)
        env["ATLAS_DATA_DIR"] = str(data_root)
        run = subprocess.run(
            [sys.executable, "-m", "atlas.cli", "run", "--print", prompt,
             "--model", "deepseek-v4.1-flash", "--permission-mode", "read_only",
             "--output-format", "json", "--timeout", "240"],
            cwd=CORE, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=270,
        )
        if run.returncode:
            diagnostics = "\n".join(
                part.strip()[-6000:] for part in (run.stdout, run.stderr) if part.strip()
            ) or "(child process produced no output)"
            raise AssertionError(
                f"real citation run failed with exit {run.returncode}; child diagnostics:\n{diagnostics}"
            )
        conversation = str(json.loads(run.stdout).get("conversation_id") or "")
        assistant_messages = [row for row in read_session_messages(
            data_root / "engine", conversation,
        ) if row.get("role") == "assistant"]
        citations = (assistant_messages[-1].get("metadata", {}).get("memory_citations", [])
                     if assistant_messages else [])
        if citation_ref not in citations:
            final_text = str(assistant_messages[-1].get("content", ""))[-1200:] if assistant_messages else "(no assistant message)"
            raise AssertionError(
                "real answer did not persist the adopted memory source ref; "
                f"persisted_refs={citations!r}; final_text_tail={final_text!r}"
            )
    finally:
        if original_page is not None:
            memory_path.write_bytes(original_page)
        elif memory_path.exists():
            memory_path.unlink()
        library.index.sync()
        if library.index._db is not None:
            library.index._db.close()
            library.index._db = None


def check_item_6() -> None:
    frontend = ROOT / "frontend"
    program = (
        "import assert from 'node:assert/strict'; "
        "import {extractMemoryMarkers} from './src/renderer/services/memoryMarkers.ts'; "
        "const input=['ordinary','# Remember this preference','with a detail line','','#记住：avoid late calls',"
        "'~~~js','# code-only','~~~','\\\\# literal'].join(String.fromCharCode(10)); "
        "assert.deepEqual(extractMemoryMarkers(input),['Remember this preference'+String.fromCharCode(10)+'with a detail line','avoid late calls']); "
        "assert.ok(input.includes('# Remember this preference')); "
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", program], cwd=frontend,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)

    from atlas.memory.library import MemoryLibrary
    with tempfile.TemporaryDirectory(prefix="atlas-u27-marker-save-") as temp:
        library = MemoryLibrary(Path(temp) / "memory")
        library.ready()
        saved = library.add_entry("我.md", "Remember this preference with a detail line")
        assert saved["path"] == "我.md" and library.page_view("我.md")["current"][0]["text"].startswith("Remember this preference")
        try:
            library.add_entry("我.md", "api_key=not-a-real-secret-value")
        except ValueError:
            pass
        else:
            raise AssertionError("memory review write accepted a secret-like value")
        if library.index._db is not None:
            library.index._db.close()


def main() -> int:
    os.environ.setdefault("ATLAS_ROOT", str(ROOT))
    os.environ.setdefault("ATLAS_DATA_DIR", str(ROOT.parent / "_atlasroot"))
    scenes = [
        ("0 dashboard hash token, non-blocking MCP and failure cooldown/manual retry", check_item_0),
        ("1 memory journey filtering, stable pagination and skill event", check_item_1),
        ("2 Slack OAuth with local fake exchange and one-use state", check_item_2),
        ("3 shared voice toggle, push-to-talk and autosend lifecycle", check_item_3),
        ("4 isolated memory retrieval benchmark metrics", check_item_4),
        ("5 explicit citation filtering, transcript cleanup and message binding", check_item_5),
        ("6 line-start marker parsing, escaped/code boundaries and confirmed memory write", check_item_6),
    ]
    try:
        for title, check in scenes:
            print(f"U27 scene: {title}", flush=True)
            check()
            print(f"U27 scene passed: {title}", flush=True)
    except Exception as exc:  # Keep diagnostics actionable without dumping config values.
        print(f"U27 scene failed: {type(exc).__name__}: {exc}", flush=True)
        print("U27 CHECK FAIL", flush=True)
        return 1
    print("Electron was not started; scenarios use temporary stores and a local fake OAuth service.", flush=True)
    print("U27 CHECK PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
