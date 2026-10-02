"""Git-safety regression tests for :mod:`atlas.agent.subagent_worktree`.

Mirrors the subagent-worktree parts of tests/security/test_gitspawn_config_injection.py
from NousResearch/hermes-agent (GHSA-7x36-8jrh-v4pw and its follow-ups bba715b42d,
9c589b91bd, 803cd03521, 1ff01f4cf7; MIT, (c) Nous Research).

A repository delivered as files can carry a ``.git/config`` naming a command in an
execution sink (``core.fsmonitor``, ``core.hooksPath`` hooks, or a repository-named
clean/smudge ``filter`` driver chosen via ``.gitattributes``). Atlas creates and
inspects subagent worktrees automatically, before any human gate, so every git call
here must neutralize every sink. Skipped when ``git`` is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from atlas.agent import subagent_worktree

_HAS_GIT = shutil.which("git") is not None
pytestmark = pytest.mark.skipif(not _HAS_GIT, reason="git not installed")

_CLEAN = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str, **kwargs) -> None:
    # _CLEAN blanks global config, so every commit needs an explicit identity.
    ident = ["-c", "user.email=atlas@example.invalid", "-c", "user.name=Atlas Test"]
    subprocess.run(["git", "-C", str(repo), *ident, *args], check=True, env=_CLEAN, **kwargs)


def _config(repo: Path, key: str, value: str) -> None:
    subprocess.run(["git", "-C", str(repo), "config", key, value], check=True, env=_CLEAN)


def _fired(marker: Path) -> list[str]:
    out = []
    for sink in ("fsmonitor", "hook", "smudge", "clean"):
        path = Path(f"{marker}.{sink}")
        if path.exists():
            out.append(sink)
            path.unlink()
    return out


@pytest.fixture()
def malicious_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A repo whose .git/config arms fsmonitor and a post-checkout hook; a fired
    sink leaves ``<marker>.<sink>`` on disk."""
    repo = tmp_path / "poc"
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=_CLEAN)
    (repo / "README").write_text("hi\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    marker = tmp_path / "MARKER"
    hooks = repo / "evil-hooks"
    hooks.mkdir()
    hook = hooks / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch '{marker.as_posix()}.hook'\n", encoding="utf-8")
    hook.chmod(0o755)
    # Let git encode the values; raw Windows backslashes are escapes.
    _config(repo, "core.fsmonitor", f"touch '{marker.as_posix()}.fsmonitor'")
    _config(repo, "core.hooksPath", hooks.as_posix())
    return repo, marker


@pytest.fixture()
def filter_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A repo whose ``.gitattributes`` names a filter driver armed with smudge and
    clean commands (``required=true``); a fired filter leaves ``<marker>.<sink>``."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=_CLEAN)
    (repo / "README").write_text("hi\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("README filter=evil\n", encoding="utf-8")
    marker = (tmp_path / "FILTER").as_posix()
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    for key, value in {
        "filter.evil.smudge": f"touch '{marker}.smudge'; cat",
        "filter.evil.clean": f"touch '{marker}.clean'; cat",
        "filter.evil.required": "true",
    }.items():
        _config(repo, key, value)
    return repo, tmp_path / "FILTER"


def test_baseline_unhardened_git_fires_sinks(malicious_repo: tuple[Path, Path]) -> None:
    """Sanity: with only the standard env, the armed repo actually fires — proves a
    regression in the hardening would be detected."""
    repo, marker = malicious_repo
    subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                   capture_output=True, env=_CLEAN)
    assert "fsmonitor" in _fired(marker)


def test_create_subagent_worktree_neutralizes_fixed_sinks(
    malicious_repo: tuple[Path, Path],
) -> None:
    """``worktree add`` reads the index (fsmonitor) and checks out (hooks): the
    module's git calls must run under the isolated env."""
    repo, marker = malicious_repo
    info = subagent_worktree.create_subagent_worktree(str(repo), "sinks")
    assert info is not None
    assert (Path(info["path"]) / "README").read_text(encoding="utf-8") == "hi\n"
    assert _fired(marker) == []


def test_repo_named_filters_never_run_from_create_or_finalize(
    filter_repo: tuple[Path, Path],
) -> None:
    """Filter drivers are named by ``.gitattributes``, so the fixed env pins cannot
    reach them: ``worktree add`` runs the smudge command and the finalization
    ``status`` probe re-hashes the touched file through the clean command."""
    repo, marker = filter_repo
    info = subagent_worktree.create_subagent_worktree(str(repo), "filters")
    assert info is not None
    assert (Path(info["path"]) / "README").read_text(encoding="utf-8") == "hi\n"
    # Same content, new mtime: the finalization status probe must re-hash it.
    readme = Path(info["path"]) / "README"
    os.utime(readme, (time.time() + 120, time.time() + 120))
    payload = subagent_worktree.finalize_subagent_worktree(info, prune=False)
    assert "inspection_failed" not in payload
    assert payload["dirty"] is False and payload["commits"] == 0
    assert _fired(marker) == []


def test_finalize_prunes_a_proven_empty_worktree(filter_repo: tuple[Path, Path]) -> None:
    """Behavior preservation: the hardened probes still let a clean, empty child
    worktree be removed (worktree remove runs no filter once status is neutralized)."""
    repo, marker = filter_repo
    info = subagent_worktree.create_subagent_worktree(str(repo), "prune-me")
    assert info is not None
    payload = subagent_worktree.finalize_subagent_worktree(info, prune=True)
    assert payload["pruned"] is True and "inspection_failed" not in payload
    assert not Path(info["path"]).exists()
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", info["branch"]],
        capture_output=True, text=True, check=True,
    )
    assert branches.stdout.strip() == ""
    assert _fired(marker) == []


def test_fail_closed_when_filter_discovery_fails(
    filter_repo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When filter discovery cannot be trusted, creation is skipped and
    finalization keeps the worktree as unproven instead of probing half-hardened."""
    repo, _marker = filter_repo
    with monkeypatch.context() as patched:
        patched.setattr(subagent_worktree, "noninteractive_repo_git_env",
                        lambda *args, **kwargs: None)
        assert subagent_worktree.create_subagent_worktree(str(repo), "skip-me") is None
    info = subagent_worktree.create_subagent_worktree(str(repo), "skip-me")
    assert info is not None
    monkeypatch.setattr(subagent_worktree, "noninteractive_repo_git_env",
                        lambda *args, **kwargs: None)
    payload = subagent_worktree.finalize_subagent_worktree(info, prune=True)
    assert payload["inspection_failed"] is True
    assert payload["pruned"] is False
    assert Path(info["path"]).exists()  # preserved for review


def test_noninteractive_git_env_pins_fixed_config_keys() -> None:
    env = subagent_worktree.noninteractive_git_env({})
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    values = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert values["core.fsmonitor"] == "false"
    assert values["core.hooksPath"] == os.devnull
    assert values["credential.helper"] == ""


def test_noninteractive_repo_git_env_appends_empty_filter_commands(
    filter_repo: tuple[Path, Path],
) -> None:
    """The discovered repo-named filter keys get empty command overrides plus
    ``required=false``, appended after the fixed pins."""
    repo, _marker = filter_repo
    env = subagent_worktree.noninteractive_repo_git_env(repo)
    assert env is not None
    count = int(env["GIT_CONFIG_COUNT"])
    fixed = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(count)
        if not env[f"GIT_CONFIG_KEY_{i}"].startswith("filter.")
    }
    assert fixed["core.fsmonitor"] == "false"  # the fixed pins survive
    values = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(count)
        if env[f"GIT_CONFIG_KEY_{i}"].startswith("filter.")
    }
    assert values == {"filter.evil.smudge": "", "filter.evil.clean": "",
                      "filter.evil.required": "false"}
