"""LSPClient × fake server integration tests (C6A LSP wave, subagent E).

Spawns ``tests/fakes/fake_lsp_server.py`` (a real asyncio stdio subprocess, no
shell wrapper) and drives ``atlas.lsp.client.LSPClient`` through the exact
acceptance flows: open a buggy file → wait → one T999 error; fix the file →
fresh diagnostics empty; plus stderr-tail capture, watched-file notifications,
seed-first-push semantics, unknown-method errors and the not-running guard.
Acceptance mapping: taskbook #1 (open → type error) and #2 (fix → error gone).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from atlas.lsp.client import LSPClient
from atlas.lsp.protocol import ERROR_METHOD_NOT_FOUND, LSPProtocolError, LSPRequestError

FAKE_SERVER = Path(__file__).resolve().parent / "fakes" / "fake_lsp_server.py"

BUGGY = "def main():\n    x = 1  # LSP_BUG\n    return x\n"
CLEAN = "def main():\n    x = 1\n    return x\n"


def _make_client(tmp_path: Path, *, extra_args: list[str] | None = None, **kwargs) -> LSPClient:
    command = [
        sys.executable,
        str(FAKE_SERVER),
        "--server-id",
        "fake",
        "--state-file",
        str(tmp_path / "fake_state.json"),
        *(extra_args or []),
    ]
    return LSPClient(server_id="fake", workspace_root=str(tmp_path), command=command, **kwargs)


async def _poll_stderr_contains(client: LSPClient, needle: str, timeout: float = 3.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if needle in client.failure_details():
            return True
        await asyncio.sleep(0.02)
    return False


# ---- acceptance #1 / #2: open → error, fix → clean ----------------------------

@pytest.mark.asyncio
async def test_open_buggy_file_reports_t999_then_fix_clears_it(tmp_path):
    path = tmp_path / "buggy.py"
    path.write_text(BUGGY, encoding="utf-8")
    client = _make_client(tmp_path)
    await client.start()
    try:
        assert client.is_running and client.state == "running"

        # Acceptance #1: open → type error.
        version = await client.open_file(str(path), language_id="python")
        assert version == 0
        assert await client.wait_for_diagnostics(str(path), version) is True
        diags = client.diagnostics_for(str(path), fresh_only=True)
        assert len(diags) == 1
        d = diags[0]
        assert d["code"] == "T999"
        assert d["severity"] == 1
        assert d["source"] == "fakeserver"
        assert "LSP_BUG" in d["message"] and "line 2" in d["message"]
        assert d["range"]["start"]["line"] == 1
        assert d["range"]["start"]["character"] == 4

        # Acceptance #2: fix → the same error disappears.
        path.write_text(CLEAN, encoding="utf-8")
        v2 = await client.open_file(str(path), language_id="python")
        assert v2 == 1  # incremental sync (server advertised change=2)
        assert await client.wait_for_diagnostics(str(path), v2) is True
        assert client.diagnostics_for(str(path), fresh_only=True) == []
    finally:
        await client.shutdown()

    assert client.state == "stopped" and not client.is_running
    assert "server exited with code 0" in client.failure_details()
    state = json.loads((tmp_path / "fake_state.json").read_text(encoding="utf-8"))
    assert state["server_id"] == "fake"
    assert state["pid"] != 0
    assert state["initialized"] is True
    assert state.get("shutdown") is True


@pytest.mark.asyncio
async def test_shutdown_is_idempotent_and_second_shutdown_is_safe(tmp_path):
    client = _make_client(tmp_path)
    await client.start()
    await client.shutdown()
    await client.shutdown()  # must not raise
    assert client.state == "stopped"
    assert "server exited with code 0" in client.failure_details()


# ---- stderr tail --------------------------------------------------------------

@pytest.mark.asyncio
async def test_stderr_tail_captures_server_ready_banner(tmp_path):
    client = _make_client(tmp_path)
    await client.start()
    try:
        assert await _poll_stderr_contains(client, "fake-lsp-server ready (fake) pid=")
    finally:
        await client.shutdown()


# ---- didChangeWatchedFiles is sent on every open and is harmless ---------------

@pytest.mark.asyncio
async def test_repeated_opens_send_watched_file_events_without_disturbing_diagnostics(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text(BUGGY, encoding="utf-8")
    b.write_text(CLEAN, encoding="utf-8")
    client = _make_client(tmp_path)
    await client.start()
    try:
        # Every open_file fires workspace/didChangeWatchedFiles (type 1 then 2);
        # the fake ignores them, and diagnostics must stay per-file correct.
        va = await client.open_file(str(a), language_id="python")
        vb = await client.open_file(str(b), language_id="python")
        assert (va, vb) == (0, 0)
        assert await client.wait_for_diagnostics(str(a), va)
        assert await client.wait_for_diagnostics(str(b), vb)

        codes_a = [d.get("code") for d in client.diagnostics_for(str(a), fresh_only=True)]
        assert client.diagnostics_for(str(b), fresh_only=True) == []
        assert codes_a == ["T999"]

        # Re-open (didChange path, more watched-file events): still fine.
        path_buggy_again = await client.open_file(str(a), language_id="python")
        assert path_buggy_again == 1
        assert await client.wait_for_diagnostics(str(a), 1)
        assert [d.get("code") for d in client.diagnostics_for(str(a), fresh_only=True)] == ["T999"]
    finally:
        await client.shutdown()


# ---- seed first-push semantics --------------------------------------------------

@pytest.mark.asyncio
async def test_seed_baseline_push_never_counts_as_fresh(tmp_path):
    path = tmp_path / "seeded.py"
    path.write_text(BUGGY, encoding="utf-8")
    client = _make_client(tmp_path, extra_args=["--seed"], seed_diagnostics_on_first_push=True)
    await client.start()
    try:
        version = await client.open_file(str(path), language_id="python")
        # The unversioned seed push (stale H100 history warning) must NOT satisfy
        # the waiter; only the versioned T999 push that follows does.
        assert await client.wait_for_diagnostics(str(path), version) is True
        fresh = client.diagnostics_for(str(path), fresh_only=True)
        assert [d.get("code") for d in fresh] == ["T999"]
    finally:
        await client.shutdown()


# ---- server→client error surface ------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_server_method_returns_method_not_found(tmp_path):
    client = _make_client(tmp_path)
    await client.start()
    try:
        with pytest.raises(LSPRequestError) as excinfo:
            await client._send_request("fake/noSuchMethod", {})
        assert excinfo.value.code == ERROR_METHOD_NOT_FOUND
    finally:
        await client.shutdown()


# ---- guards on non-running clients ----------------------------------------------

@pytest.mark.asyncio
async def test_open_file_before_start_raises_protocol_error(tmp_path):
    client = _make_client(tmp_path)
    with pytest.raises(LSPProtocolError):
        await client.open_file(str(tmp_path / "never.py"))
    assert client.state == "stopped" and not client.is_running


@pytest.mark.asyncio
async def test_open_file_after_shutdown_raises_protocol_error(tmp_path):
    path = tmp_path / "late.py"
    path.write_text(CLEAN, encoding="utf-8")
    client = _make_client(tmp_path)
    await client.start()
    await client.shutdown()
    with pytest.raises(LSPProtocolError):
        await client.open_file(str(path))
