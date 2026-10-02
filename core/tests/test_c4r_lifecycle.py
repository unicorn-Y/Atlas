"""C4 R lifecycle hooks: wire the real lifecycle points into the shared HookStore.

Covers the manual compaction pair (PreCompact block, PostCompact notification)
through the compact entry point, SessionEnd at the real conversation-destruction
endpoint, and the fire-and-forget helper used by the automatic-compression
bridge in run_turn. Hook commands run as real subprocesses fed via stdin, but
never touch real user directories or the network.

The ``run_turn`` ``on_event`` closure itself (session:compress -> PostCompact)
is not covered end to end: exercising it needs a real Hermes turn. Faking the
event would defeat the point of the bridge, so only the dispatch helper is
unit-tested here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.engine import HermesRuntime
from atlas.engine.hermes_runtime import _fire_lifecycle_hook
from atlas.memory import MemoryStore
from atlas.runtime.hooks import HookStore


# ---------------------------------------------------------------------------
# Fixtures: Claude-format settings.json plus real hook executables
# ---------------------------------------------------------------------------

def _hook_script(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / f"{name}_hook.py"
    script.write_text(body, encoding="utf-8")
    return script


def _write_project_hooks(
    tmp_path: Path, event: str, command: str, args: list[str],
    *, matcher: str | None = None, local: bool = False,
) -> Path:
    group: dict[str, Any] = {"hooks": [
        {"type": "command", "command": command, "args": args},
    ]}
    if matcher is not None:
        group["matcher"] = matcher
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    path = claude / ("settings.local.json" if local else "settings.json")
    path.write_text(json.dumps({"hooks": {event: [group]}}), encoding="utf-8")
    return path


def _store(tmp_path: Path) -> HookStore:
    return HookStore(tmp_path / "hooks.toml")


def _dump_payload_hook(tmp_path: Path, name: str) -> Path:
    """A real subprocess hook that persists its stdin payload as JSON."""
    return _hook_script(tmp_path, name, (
        "import json,sys\n"
        "from pathlib import Path\n"
        "data = json.load(sys.stdin)\n"
        "out = Path(__file__).with_name(" + json.dumps(f"{name}.json") + ")\n"
        "out.write_text(json.dumps(data), encoding='utf-8')\n"
    ))


def _read_payload(tmp_path: Path, name: str) -> dict[str, Any]:
    return json.loads((tmp_path / f"{name}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Manual compaction: PreCompact block + PostCompact notification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_precompact_blocks_manual_compact_via_shared_store(tmp_path: Path) -> None:
    script = _hook_script(tmp_path, "compact", (
        "import sys\nfrom pathlib import Path\n"
        "sys.stdin.read()\n"
        "Path(__file__).with_name('compact-marker').write_text('ran', encoding='utf-8')\n"
        "sys.stderr.write('compaction denied by policy')\n"
        "sys.exit(2)\n"
    ))
    _write_project_hooks(tmp_path, "PreCompact", sys.executable, [str(script)])
    store = _store(tmp_path)
    runtime = HermesRuntime(data_dir=tmp_path / "data", model_manager=MagicMock())

    result = await runtime.compact_session(
        conversation_id="c1", workspace=str(tmp_path), hook_store=store,
    )

    assert result["compressed"] is False
    assert result["reason"] == "blocked_by_hook"
    assert "compaction denied by policy" in result["detail"]
    # The passed-in store is the one that executed the hook.
    assert any(log["event"] == "PreCompact" for log in store.recent_logs())


@pytest.mark.asyncio
async def test_manual_compact_fires_postcompact_with_payload(tmp_path: Path) -> None:
    script = _dump_payload_hook(tmp_path, "postcompact")
    _write_project_hooks(tmp_path, "PostCompact", sys.executable, [str(script)])
    runtime = HermesRuntime(data_dir=tmp_path / "data", model_manager=MagicMock())
    runtime._compact_session_sync = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "compressed": True, "before_tokens": 100, "after_tokens": 40, "summary": "s",
    }

    result = await runtime.compact_session(
        conversation_id="conv-post", workspace=str(tmp_path), hook_store=_store(tmp_path),
    )

    assert result["compressed"] is True
    payload = _read_payload(tmp_path, "postcompact")
    assert payload["hook_event_name"] == "PostCompact"
    assert payload["trigger"] == "manual"
    assert payload["before_tokens"] == 100
    assert payload["after_tokens"] == 40
    assert payload["conversation_id"] == "conv-post"


@pytest.mark.asyncio
async def test_manual_compact_empty_session_skips_postcompact(tmp_path: Path) -> None:
    script = _dump_payload_hook(tmp_path, "postcompact")
    _write_project_hooks(tmp_path, "PostCompact", sys.executable, [str(script)])
    runtime = HermesRuntime(data_dir=tmp_path / "data", model_manager=MagicMock())
    runtime._compact_session_sync = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "compressed": False, "reason": "empty_session", "summary": "",
    }

    result = await runtime.compact_session(
        conversation_id="conv-empty", workspace=str(tmp_path), hook_store=_store(tmp_path),
    )

    assert result["reason"] == "empty_session"
    assert not (tmp_path / "postcompact.json").exists()


# ---------------------------------------------------------------------------
# Automatic compaction bridge: the fire-and-forget dispatch helper
# ---------------------------------------------------------------------------

async def test_fire_lifecycle_hook_supports_sync_and_async_callbacks() -> None:
    seen: list[tuple[str, Any]] = []

    def sync_callback(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        seen.append((event, payload["attempt"]))
        return {"blocked": True}  # fire-and-forget: the outcome is ignored

    async def async_callback(event: str, payload: dict[str, Any]) -> None:
        seen.append((event + "-async", payload["attempt"]))

    await _fire_lifecycle_hook(sync_callback, "PostCompact", {"attempt": 1})
    await _fire_lifecycle_hook(async_callback, "PostCompact", {"attempt": 2})

    assert seen == [("PostCompact", 1), ("PostCompact-async", 2)]


async def test_fire_lifecycle_hook_swallows_callback_errors() -> None:
    def failing_callback(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("hook exploded")

    await _fire_lifecycle_hook(failing_callback, "PostCompact", {})  # must not raise


# ---------------------------------------------------------------------------
# SessionEnd at the real conversation-destruction endpoint
# ---------------------------------------------------------------------------

async def _install_delete_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> MemoryStore:
    script = _dump_payload_hook(tmp_path, "sessionend")
    _write_project_hooks(tmp_path, "SessionEnd", sys.executable, [str(script)])
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    monkeypatch.setattr(server, "memory", store)
    monkeypatch.setattr(server, "_hook_store", lambda: _store(tmp_path))
    return store


async def test_delete_conversation_fires_session_end(tmp_path: Path, monkeypatch) -> None:
    store = await _install_delete_fixtures(tmp_path, monkeypatch)
    conversation_id = await store.create_conversation("doomed")
    await store.update_conversation(conversation_id, workspace=str(tmp_path))

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(f"/api/conversations/{conversation_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    payload = _read_payload(tmp_path, "sessionend")
    assert payload["hook_event_name"] == "SessionEnd"
    assert payload["reason"] == "delete"
    assert payload["conversation_id"] == conversation_id
    await store.close()


async def test_delete_missing_conversation_skips_session_end(
    tmp_path: Path, monkeypatch,
) -> None:
    await _install_delete_fixtures(tmp_path, monkeypatch)

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/api/conversations/missing-conv")

    assert response.status_code == 404
    assert not (tmp_path / "sessionend.json").exists()
