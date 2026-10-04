from __future__ import annotations

import builtins
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from atlas import desktop_entry


def test_backend_preloads_hermes_utils_before_importing_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[str] = []
    utils_module = ModuleType("utils")
    app = SimpleNamespace(state=SimpleNamespace())
    server_module = ModuleType("atlas.server")
    server_module.app = app

    class FakeConfig:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class FakeServer:
        should_exit = False

        def __init__(self, _config) -> None:
            pass

        def run(self) -> None:
            pass

    uvicorn_module = ModuleType("uvicorn")
    uvicorn_module.Config = FakeConfig
    uvicorn_module.Server = FakeServer
    original_import = builtins.__import__
    original_import_module = importlib.import_module

    def track_import(name, *args, **kwargs):
        if name == "atlas.server":
            imported.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_module)
    monkeypatch.setitem(sys.modules, "atlas.server", server_module)

    def track_import_module(name, *args, **kwargs):
        if name == "utils":
            imported.append(name)
            return utils_module
        return original_import_module(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", track_import)
    monkeypatch.setattr(importlib, "import_module", track_import_module)
    monkeypatch.setattr(sys, "argv", ["desktop_entry"])

    desktop_entry.main()

    assert imported.index("utils") < imported.index("atlas.server")


def test_skill_search_worker_dispatch_does_not_import_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    worker_module = ModuleType("atlas.skills.market_search_worker")
    worker_module.run_stdio = lambda: calls.append("worker")
    server_module = ModuleType("atlas.server")

    def reject_server_start(_name: str) -> None:
        raise AssertionError("worker dispatch must not import Atlas server")

    server_module.__getattr__ = reject_server_start
    monkeypatch.setitem(sys.modules, "atlas.skills.market_search_worker", worker_module)
    monkeypatch.setitem(sys.modules, "atlas.server", server_module)
    monkeypatch.setattr(sys, "argv", ["desktop_entry", "--atlas-skill-search-worker"])

    desktop_entry.main()

    assert calls == ["worker"]


def test_source_worker_self_exec_searches_only_an_isolated_directory_tap(tmp_path) -> None:
    skill_root = tmp_path / "tap" / "offline-demo"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: offline-demo\ndescription: Isolated worker smoke fixture\ntags: [local]\n---\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "market.json").write_text(json.dumps({
        "version": 1,
        "sources": [{
            "name": "offline-fixture",
            "kind": "directory",
            "path": str(skill_root.parent),
            "enabled": True,
        }],
    }), encoding="utf-8")
    request = {
        "query": "Isolated worker",
        "source": "offline-fixture",
        "limit": 5,
        "data_dir": str(data_dir),
        "user_skills_dir": str(tmp_path / "user-skills"),
        "project_skills_dir": None,
        "hermes_root": None,
        "hub_state_dir": str(tmp_path / "hub"),
    }
    core_dir = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "atlas.desktop_entry", "--atlas-skill-search-worker"],
        input=json.dumps(request).encode("utf-8"),
        capture_output=True,
        cwd=core_dir,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    response = json.loads(result.stdout)
    assert [item["identifier"] for item in response["results"]] == ["offline-demo"]
    assert response["results"][0]["source"] == "offline-fixture"
