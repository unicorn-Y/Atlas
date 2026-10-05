"""Tests for cancellable, per-source marketplace search workers."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.skills import market as market_module
from atlas.skills.market import MarketUnavailableError, SkillMarket


def _market(tmp_path: Path) -> SkillMarket:
    return SkillMarket(
        registry=None,
        data_dir=tmp_path,
        user_skills_dir=tmp_path / "skills",
    )


async def _wait_for_file(path: Path) -> None:
    """Wait until the child has written its pid (existence alone races the write)."""
    deadline = asyncio.get_running_loop().time() + 8
    while not (path.exists() and path.read_text(encoding="utf-8").strip()):
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"worker did not write {path}")
        await asyncio.sleep(0.02)


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, check=False,
        )
        # tasklist prints localized text in the OEM codepage (GBK on zh-CN);
        # match bytes so the result does not depend on the active UTF-8 mode.
        return str(pid).encode() in completed.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


async def test_shutdown_cancels_and_reaps_blocked_source_worker(tmp_path: Path) -> None:
    state = market_module._search_worker_state()
    state["closing"] = False
    state["processes"].clear()
    pid_file = tmp_path / "worker.pid"
    grandchild_pid_file = tmp_path / "grandchild.pid"
    script = tmp_path / "blocked_worker.py"
    grandchild_code = (
        "import os, pathlib, sys, time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
    )
    script.write_text(
        "import os, pathlib, subprocess, sys, time\n"
        f"grandchild=subprocess.Popen([sys.executable, '-c', {grandchild_code!r}, sys.argv[2]])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "pathlib.Path(sys.argv[3]).write_text(str(grandchild.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    market = _market(tmp_path)
    market._search_worker_command = lambda: [
        sys.executable, str(script), str(pid_file), str(grandchild_pid_file),
        str(tmp_path / "child.pid"),
    ]

    search = asyncio.create_task(market._run_search_worker("github", "", 20))
    try:
        await _wait_for_file(pid_file)
        await _wait_for_file(grandchild_pid_file)
        int(pid_file.read_text(encoding="utf-8"))
        grandchild_pid = int(grandchild_pid_file.read_text(encoding="utf-8"))
        process = next(iter(state["processes"]))
        shutdown_market = _market(tmp_path / "shutdown-instance")
        # _kill_and_reap_search_worker bounds itself at taskkill 3s + reap 3s; leave slack for load.
        await asyncio.wait_for(shutdown_market.cancel_pending_searches(), timeout=10)
        with pytest.raises(MarketUnavailableError):
            await asyncio.wait_for(search, timeout=10)
        assert search.done()
        assert process.returncode is not None
        assert state["processes"] == set()
        deadline = asyncio.get_running_loop().time() + 3
        while _pid_exists(grandchild_pid) and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        assert not _pid_exists(grandchild_pid)
    finally:
        if not search.done():
            search.cancel()
            await asyncio.gather(search, return_exceptions=True)


async def test_search_worker_uses_json_stdin_and_stdout(tmp_path: Path) -> None:
    state = market_module._search_worker_state()
    state["closing"] = False
    script = tmp_path / "echo_worker.py"
    script.write_text(
        "import json, sys\n"
        "request=json.load(sys.stdin)\n"
        "print(json.dumps({'results':[{'source':request['source'],'identifier':'o/r/demo'}]}))\n",
        encoding="utf-8",
    )
    market = _market(tmp_path)
    market._search_worker_command = lambda: [sys.executable, str(script)]

    results = await market._run_search_worker("github", "demo", 7)

    assert results == [{"source": "github", "identifier": "o/r/demo"}]


def test_worker_keeps_provider_stdout_out_of_json_channel(monkeypatch) -> None:
    from atlas.skills import market_search_worker

    stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
    stdout_buffer = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_buffer, encoding="utf-8")
    stderr_buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr_buffer)

    def noisy_search(_payload):
        print("provider diagnostic")
        return {"results": []}

    monkeypatch.setattr(market_search_worker, "_search", noisy_search)

    with contextlib.redirect_stderr(stderr_buffer):
        market_search_worker.run_stdio()

    assert json.loads(stdout_buffer.getvalue()) == {"results": []}
    assert "provider diagnostic" in stderr_buffer.getvalue()


async def test_disconnected_market_search_cancels_its_worker_task(monkeypatch) -> None:
    from atlas.api import skills_market_router

    class BlockingMarket:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def search(self, **_kwargs):
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()

    class DisconnectedRequest:
        async def is_disconnected(self) -> bool:
            return True

    market = BlockingMarket()
    monkeypatch.setattr(skills_market_router, "get_market", lambda: market)

    response = await skills_market_router.market_search(
        request=DisconnectedRequest(), q="demo", source="github", limit=10,
    )

    assert response.status_code == 499
    assert market.started.is_set()
    assert market.cancelled.is_set()

