# Ported from NousResearch/hermes-agent@330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3:
# tools/subagent_worktree.py (MIT, (c) Nous Research).
# Git-safety hardening backported from upstream commits bba715b42d, 9c589b91bd,
# 803cd03521 and 1ff01f4cf7 (GHSA-7x36-8jrh-v4pw follow-ups): every git child runs
# under a noninteractive, config-isolated environment, and repository-named
# clean/smudge/process filters (worktree add's smudge, the finalization status
# probe's clean) are neutralized via noninteractive_repo_git_env. Filter discovery
# is fail-closed: creation is skipped and finalization keeps the tree unproven.
# Changes: Atlas branch naming and subprocess integration; no engine runtime
# imports (noninteractive_git_env / noninteractive_repo_git_env inlined below).
"""Git worktree helpers for isolated Atlas children.

An empty, clean child worktree may be removed after both git probes succeed. Any
commit, dirty file, or failed inspection leaves the worktree and branch in place.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Mapping

log = logging.getLogger(__name__)
_GIT_TIMEOUT = 30

# Fixed config overrides for internal git children: no credential/askpass prompts,
# no repo-configured fsmonitor/hooks/pager/editor programs (GHSA-7x36-8jrh-v4pw).
_GIT_CONFIG_INJECT_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
_GIT_CONFIG_OVERRIDES = {
    "credential.helper": "",
    "core.askPass": "",
    "core.fsmonitor": "false",
    "core.untrackedCache": "false",
    "core.hooksPath": os.devnull,
    "core.pager": "cat",
    "core.editor": "true",
    "sequence.editor": "true",
    "diff.external": "",
}

_SAFE_DIRECTORY_CACHE: dict[tuple, list[str]] = {}


def _safe_directory_cache_key(env: Mapping[str, str]) -> tuple:
    """Everything that selects which files ``git config --global/--system`` read,
    plus the candidates' mtimes so an edited config is picked up without a restart."""
    home = env.get("HOME", "") or os.path.expanduser("~")
    xdg = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    candidates = (
        env.get("GIT_CONFIG_SYSTEM") or "/etc/gitconfig",
        env.get("GIT_CONFIG_GLOBAL") or os.path.join(home, ".gitconfig"),
        os.path.join(xdg, "git", "config"),
    )
    stamps: list[str | None] = []
    for path in candidates:
        try:
            stamps.append(str(os.stat(path).st_mtime_ns))
        except OSError:
            stamps.append(None)
    return (env.get("GIT_CONFIG_GLOBAL"), env.get("GIT_CONFIG_SYSTEM"),
            env.get("GIT_CONFIG_NOSYSTEM"), home, env.get("XDG_CONFIG_HOME"),
            env.get("PATH"), *stamps)


def _user_safe_directories(base_env: Mapping[str, str]) -> list[str]:
    """The user's configured ``safe.directory`` values, in git's effective order.

    Read under the caller's untouched environment and replayed into the isolated
    config block: ``GIT_CONFIG_GLOBAL``/``SYSTEM`` are blanked below, and without
    the replay a shared-ownership repo would fail "dubious ownership". Ordered
    multi-valued, with empty reset markers preserved verbatim (no de-duplication),
    so a revoked wildcard stays revoked. Best-effort: any failure yields [].
    """
    cache_key = _safe_directory_cache_key(base_env)
    cached = _SAFE_DIRECTORY_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    env = dict(base_env)
    for key in list(env):
        if key == "GIT_CONFIG_PARAMETERS" or key.startswith(_GIT_CONFIG_INJECT_PREFIXES):
            env.pop(key)
    env.pop("GIT_CONFIG_COUNT", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    values: list[str] = []
    for scope in ("--system", "--global"):
        try:
            proc = subprocess.run(
                ["git", "config", scope, "-z", "--get-all", "safe.directory"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=5, stdin=subprocess.DEVNULL, env=env, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0:
            continue
        records = proc.stdout.split("\0")
        if records and records[-1] == "":
            records.pop()
        values.extend(records)
    _SAFE_DIRECTORY_CACHE[cache_key] = list(values)
    return values


def noninteractive_git_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for *internal* git invocations that must never prompt (GHSA-7x36-8jrh-v4pw).

    Copy of ``base`` (default ``os.environ``) with ``GIT_TERMINAL_PROMPT=0``,
    ``GCM_INTERACTIVE=Never``, and isolated git config: inherited ``GIT_CONFIG_*``
    injection, global/system config, pagers, editors, fsmonitor and hooks are all
    disabled so a user's repo/global config cannot hang or mutate these plumbing
    calls. Pair with ``stdin=subprocess.DEVNULL``.
    """
    env = dict(base if base is not None else os.environ)
    safe_directories = _user_safe_directories(base if base is not None else os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    # Drop caller-supplied config injection; the config block is rebuilt below.
    for key in list(env):
        if key == "GIT_CONFIG_PARAMETERS" or key.startswith(_GIT_CONFIG_INJECT_PREFIXES):
            env.pop(key)
    env.pop("GIT_CONFIG_COUNT", None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_PAGER"] = "cat"
    env["PAGER"] = "cat"
    env["GIT_EDITOR"] = "true"
    overrides = list(_GIT_CONFIG_OVERRIDES.items())
    # safe.directory is honoured only from global/system config, both blanked above.
    overrides.extend(("safe.directory", value) for value in safe_directories)
    env["GIT_CONFIG_COUNT"] = str(len(overrides))
    for idx, (key, value) in enumerate(overrides):
        env[f"GIT_CONFIG_KEY_{idx}"] = key
        env[f"GIT_CONFIG_VALUE_{idx}"] = value
    return env


# A repository names its filter drivers through .gitattributes, so the fixed pins
# above cannot enumerate them; discovered keys get empty-command overrides instead.
_FILTER_COMMAND_KEY = re.compile(r"^filter\..+\.(?:clean|smudge|process)$", re.IGNORECASE)


def noninteractive_repo_git_env(
    cwd: str | os.PathLike[str],
    base: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    """Harden internal git for one repository, including named clean/smudge/process filters.

    Discover this checkout's effective filter command keys and append empty command
    overrides plus ``required=false`` to the already-isolated config block.
    Discovery is bounded and fail-closed: when it cannot be trusted, ``None`` is
    returned and callers skip the automatic git operation instead of running it
    half-hardened (upstream bba715b42d/9c589b91bd/803cd03521/1ff01f4cf7).
    """
    env = noninteractive_git_env(base)
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(cwd), "config", "--includes", "--name-only", "-z",
                "--get-regexp", r"^filter\..*\.(clean|smudge|process)$",
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=2, stdin=subprocess.DEVNULL, env=env, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode not in (0, 1):
        return None

    keys: list[str] = []
    required: list[str] = []
    seen: set[str] = set()
    for raw in proc.stdout.split("\0"):
        key = raw.strip()
        lowered = key.lower()
        if not key or lowered in seen or not _FILTER_COMMAND_KEY.fullmatch(key):
            continue
        seen.add(lowered)
        keys.append(key)
        required_key = key.rsplit(".", 1)[0] + ".required"
        if required_key.lower() not in seen:
            seen.add(required_key.lower())
            required.append(required_key)

    start = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    overrides = [(key, "") for key in keys] + [(key, "false") for key in required]
    for offset, (key, value) in enumerate(overrides):
        env[f"GIT_CONFIG_KEY_{start + offset}"] = key
        env[f"GIT_CONFIG_VALUE_{start + offset}"] = value
    env["GIT_CONFIG_COUNT"] = str(start + len(overrides))
    return env


def _run_git(
    args: list[str], *, cwd: str, env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run git capturing output; never raises on non-zero exit.

    Defaults to :func:`noninteractive_git_env`: this runs unattended against
    whatever repository the session sits in (GHSA-7x36-8jrh-v4pw).
    """
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=_GIT_TIMEOUT,
        stdin=subprocess.DEVNULL, check=False, env=env or noninteractive_git_env(),
    )


def resolve_repo_root(path: str | None) -> str | None:
    candidate = os.path.abspath(os.path.expanduser(path or ""))
    if not candidate or not os.path.isdir(candidate):
        return None
    try:
        result = _run_git(["rev-parse", "--show-toplevel"], cwd=candidate)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _ensure_gitignore_entry(repo_root: str) -> None:
    """Keep worktrees out of the parent repository's status output."""
    path = Path(repo_root) / ".gitignore"
    try:
        content = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if ".worktrees/" not in content.splitlines():
            with path.open("a", encoding="utf-8") as handle:
                handle.write(("" if not content or content.endswith("\n") else "\n")
                             + ".worktrees/\n")
    except OSError as exc:
        log.warning("Could not add .worktrees/ to %s: %s", path, exc)


_ORPHAN_MIN_AGE_SECONDS = 3600


def prune_orphan_worktrees(repo_root: str, *, min_age_seconds: float = _ORPHAN_MIN_AGE_SECONDS) -> list[str]:
    """Remove leftover child worktrees whose finalizer never ran (Atlas killed or crashed mid-run).

    Only trees older than ``min_age_seconds`` that are clean and whose branch tip is already
    contained in a non-subagent branch (so no unique commits) are removed; anything else stays
    for review, same rule as :func:`finalize_subagent_worktree`.
    """
    import time

    removed: list[str] = []
    container = Path(repo_root) / ".worktrees"
    if not container.is_dir():
        return removed
    for tree in sorted(container.glob("subagent-*")):
        try:
            if not tree.is_dir() or time.time() - tree.stat().st_mtime < min_age_seconds:
                continue
            env = noninteractive_repo_git_env(str(tree))
            if env is None:
                continue
            status = _run_git(["status", "--porcelain"], cwd=str(tree), env=env)
            if status.returncode or status.stdout.strip():
                continue
            branch = f"atlas-subagent/{tree.name.removeprefix('subagent-')}"
            containing = _run_git(["branch", "--format=%(refname:short)", "--contains", "HEAD"], cwd=str(tree), env=env)
            if containing.returncode:
                continue
            others = [line.strip() for line in containing.stdout.splitlines()
                      if line.strip() and not line.strip().startswith("atlas-subagent/")]
            if not others:
                continue  # has commits no regular branch contains: keep for review
            result = _run_git(["worktree", "remove", "--force", str(tree)], cwd=repo_root)
            if result.returncode == 0:
                _run_git(["branch", "-D", branch], cwd=repo_root)
                removed.append(str(tree))
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("Subagent orphan worktree sweep skipped %s: %s", tree, exc)
    if removed:
        _run_git(["worktree", "prune"], cwd=repo_root)
    return removed


def create_subagent_worktree(
    parent_cwd: str | None, subagent_id: str | None = None,
) -> dict[str, str] | None:
    """Create `<repo>/.worktrees/subagent-<id>` and an Atlas-owned branch."""
    repo_root = resolve_repo_root(parent_cwd)
    if not repo_root:
        return None
    try:
        prune_orphan_worktrees(repo_root)
    except Exception as exc:  # the sweep must never block creating the child's tree
        log.warning("Subagent orphan worktree sweep failed: %s", exc)
    suffix = re.sub(r"[^A-Za-z0-9._-]", "-", subagent_id or uuid.uuid4().hex[:8])
    name = f"subagent-{suffix}"
    branch = f"atlas-subagent/{suffix}"
    worktree = Path(repo_root) / ".worktrees" / name
    try:
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _ensure_gitignore_entry(repo_root)
        base = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
        if base.returncode:
            return None
        # The checkout runs the repo-named smudge filter; skip isolation when it
        # cannot be neutralized rather than run the child's checkout half-hardened.
        add_env = noninteractive_repo_git_env(repo_root)
        if add_env is None:
            log.warning("Subagent worktree: filter discovery failed; not creating a worktree")
            return None
        result = _run_git(
            ["worktree", "add", str(worktree), "-b", branch, base.stdout.strip()],
            cwd=repo_root, env=add_env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Subagent worktree creation failed: %s", exc)
        return None
    if result.returncode:
        log.warning("Subagent worktree creation failed: %s", result.stderr.strip())
        return None
    return {"path": str(worktree), "branch": branch, "repo_root": repo_root,
            "base_commit": base.stdout.strip()}


def _base_payload(info: dict[str, str]) -> dict[str, Any]:
    return {"path": info.get("path", ""), "branch": info.get("branch", ""),
            "commits": 0, "dirty": False, "pruned": False}


def mark_worktree_payload_unproven(
    payload: dict[str, Any], reason: str, *, unmeasured: str = "commits/dirty",
) -> dict[str, Any]:
    path, branch = payload.get("path", ""), payload.get("branch", "")
    payload["inspection_failed"] = True
    payload["note"] = (
        f"Git 检查失败（{reason}）：{unmeasured} 未知，不能确认工作树为空且干净。"
        f"已保留目录 {path} 和分支 {branch}，请检查后再处理。"
    )
    log.warning("Git inspection failed; preserving child worktree %s (%s)", path, branch)
    return payload


def unproven_worktree_payload(info: dict[str, str], reason: str) -> dict[str, Any]:
    return mark_worktree_payload_unproven(_base_payload(info), reason)


def finalize_subagent_worktree(
    info: dict[str, str], *, prune: bool = True,
) -> dict[str, Any]:
    """Remove only a proven empty worktree; otherwise preserve it for review."""
    path, branch, base = info.get("path", ""), info.get("branch", ""), info.get("base_commit", "")
    payload = _base_payload(info)
    if not path or not os.path.isdir(path):
        payload["pruned"] = True
        return payload
    if not base:
        return mark_worktree_payload_unproven(
            payload, "base_commit is missing", unmeasured="commits",
        )
    # The status probe re-hashes files the child touched, which runs repo-named
    # clean filters; keep the tree as unproven when they cannot be neutralized.
    probe_env = noninteractive_repo_git_env(path)
    if probe_env is None:
        return mark_worktree_payload_unproven(payload, "filter discovery failed", unmeasured="dirty")
    probes = (
        ("commits", "rev-list", ["rev-list", "--count", f"{base}..HEAD"],
         lambda value: int(value or 0)),
        ("dirty", "status", ["status", "--porcelain"], bool),
    )
    failed: list[str] = []
    unmeasured: list[str] = []
    try:
        for field, label, args, parse in probes:
            result = _run_git(args, cwd=path, env=probe_env)
            if result.returncode == 0:
                payload[field] = parse(result.stdout.strip())
            else:
                failed.append(f"{label} exit {result.returncode}: {result.stderr.strip()[:200]}")
                unmeasured.append(field)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return mark_worktree_payload_unproven(payload, f"inspection raised: {exc}")
    if failed:
        return mark_worktree_payload_unproven(
            payload, "; ".join(failed), unmeasured="/".join(unmeasured),
        )
    if prune and payload["commits"] == 0 and not payload["dirty"]:
        try:
            removed = _run_git(["worktree", "remove", "--force", path], cwd=info.get("repo_root", path))
            if removed.returncode == 0:
                _run_git(["branch", "-D", branch], cwd=info.get("repo_root", path))
                payload["pruned"] = True
        except (OSError, subprocess.SubprocessError) as exc:
            return mark_worktree_payload_unproven(payload, f"cleanup raised: {exc}")
    return payload
