"""Hermes pin + setup script: fresh installs must work without pip building Hermes."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from atlas import hermes_pin

pytestmark = pytest.mark.unit

CORE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("setup_hermes", CORE / "scripts" / "setup_hermes.py")
setup_hermes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_hermes)


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()


def _origin_with_two_commits(tmp_path: Path) -> tuple[Path, str, str]:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-q", cwd=origin)
    (origin / "run_agent.py").write_text("V = 1\n", encoding="utf-8")
    _git("add", ".", cwd=origin)
    _git("commit", "-q", "-m", "one", cwd=origin)
    first = _git("rev-parse", "HEAD", cwd=origin)
    (origin / "run_agent.py").write_text("V = 2\n", encoding="utf-8")
    _git("commit", "-q", "-am", "two", cwd=origin)
    return origin, first, _git("rev-parse", "HEAD", cwd=origin)


def test_hermes_is_not_a_pip_dependency_and_the_pin_is_a_full_commit() -> None:
    project = tomllib.loads((CORE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert not any(dep.replace(" ", "").startswith("hermes-agent") for dep in project["dependencies"])
    pin = hermes_pin.read_pin()
    assert len(pin["commit"]) == 40 and int(pin["commit"], 16) >= 0
    assert pin["repository"].endswith("unicorn-Y/hermes-agent.git")
    assert setup_hermes.read_pin() == (pin["repository"], pin["commit"])


def test_setup_clones_and_checks_out_the_pinned_commit(tmp_path: Path) -> None:
    origin, first, _second = _origin_with_two_commits(tmp_path)
    checkout = tmp_path / "hermes-agent"

    assert setup_hermes.ensure_checkout(checkout, str(origin), first) is True
    assert _git("rev-parse", "HEAD", cwd=checkout) == first
    assert (checkout / "run_agent.py").read_text(encoding="utf-8") == "V = 1\n"
    # Already at the pin: nothing to do.
    assert setup_hermes.ensure_checkout(checkout, str(origin), first) is False


def test_setup_moves_an_existing_checkout_to_a_new_pin(tmp_path: Path) -> None:
    origin, first, second = _origin_with_two_commits(tmp_path)
    checkout = tmp_path / "hermes-agent"
    setup_hermes.ensure_checkout(checkout, str(origin), first)

    assert setup_hermes.ensure_checkout(checkout, str(origin), second) is True
    assert _git("rev-parse", "HEAD", cwd=checkout) == second


def test_setup_refuses_to_touch_uncommitted_changes(tmp_path: Path) -> None:
    origin, first, second = _origin_with_two_commits(tmp_path)
    checkout = tmp_path / "hermes-agent"
    setup_hermes.ensure_checkout(checkout, str(origin), first)
    (checkout / "run_agent.py").write_text("local edit\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="uncommitted changes"):
        setup_hermes.ensure_checkout(checkout, str(origin), second)
    assert (checkout / "run_agent.py").read_text(encoding="utf-8") == "local edit\n"


def test_doctor_check_reports_pin_mismatch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hermes_pin, "installed_hermes_root", lambda: tmp_path)
    monkeypatch.setattr(hermes_pin, "checkout_commit", lambda _root: "0" * 40)
    result = hermes_pin.check()
    assert result["ok"] is False
    assert result["installed"] == "0" * 40
    assert "setup_hermes.py" in result["detail"]

    monkeypatch.setattr(hermes_pin, "checkout_commit", lambda _root: hermes_pin.read_pin()["commit"])
    assert hermes_pin.check()["ok"] is True


def test_memos_plugin_link_points_at_the_fork_and_stays_out_of_git_status(tmp_path: Path) -> None:
    origin, first, _ = _origin_with_two_commits(tmp_path)
    checkout = tmp_path / "hermes-agent"
    setup_hermes.ensure_checkout(checkout, str(origin), first)
    (checkout / "plugins" / "memory").mkdir(parents=True)
    fork = tmp_path / "fork" / "memos_provider"
    fork.mkdir(parents=True)
    old = tmp_path / "old" / "memos_provider"
    old.mkdir(parents=True)
    link = checkout / "plugins" / "memory" / "memtensor"
    # an install pointing somewhere else (junction on Windows: symlinks need admin)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(old)], capture_output=True, check=True)
    else:
        link.symlink_to(old, target_is_directory=True)

    setup_hermes.link_memos_plugin(checkout, target=fork)
    assert link.resolve() == fork.resolve()
    # The link is untracked; the next launch must not see a dirty checkout.
    assert setup_hermes.ensure_checkout(checkout, str(origin), first) is False
    assert _git("status", "--porcelain", cwd=checkout) == ""
