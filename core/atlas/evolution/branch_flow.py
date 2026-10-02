"""E5 批准 + 隔离分支/worktree 流程（**永不自动合并 main**）。

``approve_draft(draft_id)`` 的确定性流程：

1. 草稿必须存在且未批准过（重复批准给出中文提示）。
2. ``git`` 可用且 Atlas 目录是 git 仓库，否则优雅跳过（返回 ``ok=False`` + 中文原因）。
3. 在 ``<data>/evolution/worktrees/<slug>`` 用 ``git worktree add -b atlas-auto/<slug>``
   从 ``main``（缺失时依次回退 ``master`` / 当前 HEAD）创建**隔离**分支。
4. 在 worktree 里写 ``MERGE-PROPOSAL.md``（合并提案只是文本文件，人工执行）。
5. 记录到 ``<data>/evolution/branches.json``，草稿标记为 approved。

不变量：本模块从不执行 merge / rebase / push；main 分支的引用与工作区始终不动。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from atlas.evolution import taskbook_draft, watcher

log = structlog.get_logger()

BRANCH_PREFIX = "atlas-auto"


def worktrees_root() -> Path:
    return watcher.evolution_root() / "worktrees"


def _branches_path(meta_root: Path | None = None) -> Path:
    return (meta_root or watcher.evolution_root()) / "branches.json"


def _load_branches(meta_root: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads(_branches_path(meta_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"branches": {}}
    return data if isinstance(data, dict) and "branches" in data else {"branches": {}}


def _save_branches(data: dict[str, Any], meta_root: Path | None = None) -> None:
    path = _branches_path(meta_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _git_raw(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """不抛版本的 git 调用（探测类命令用）。"""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def is_git_repo(repo: Path) -> bool:
    code, _, _ = _git_raw(["rev-parse", "--show-toplevel"], repo)
    return code == 0


def resolve_base_ref(repo: Path) -> str | None:
    """main → master → HEAD 依次探测；都不是返回 None（由调用方跳过）。"""
    for candidate in ("main", "master"):
        code, _, _ = _git_raw(["rev-parse", "--verify", "--quiet", candidate], repo)
        if code == 0:
            return candidate
    code, _, _ = _git_raw(["rev-parse", "--verify", "--quiet", "HEAD"], repo)
    return "HEAD" if code == 0 else None


def merge_proposal_text(branch: str, base: str, worktree: Path, draft: dict[str, Any]) -> str:
    """合并提案：只是生成的文本文件，合并动作永远由人工执行。"""
    return "\n".join([
        f"# 合并提案：{branch}",
        "",
        "本文件由 Atlas 自动追新流程生成。**不会自动合并**；确认改动后由人工执行：",
        "",
        f"    git -C <Atlas 主工作区> merge --no-ff {branch}",
        "",
        f"- 草稿：{draft.get('id')}",
        f"- 能力：{draft.get('capability_id')} {draft.get('capability', '')}",
        f"- 来源：{draft.get('repo')} @ {draft.get('ref')}",
        f"- 基线：{base}",
        f"- worktree：{worktree}",
        "",
        "放弃该分支：",
        "",
        f"    git -C <Atlas 主工作区> worktree remove {worktree}",
        f"    git -C <Atlas 主工作区> branch -D {branch}",
        "",
    ])


def approve_draft(
    draft_id: str,
    *,
    meta_root: Path | None = None,
    repo: Path | None = None,
    worktree_parent: Path | None = None,
    base: str | None = None,
) -> dict[str, Any]:
    """批准草稿 → 建隔离分支 + worktree + 合并提案文本。失败时返回 ``ok=False`` 中文原因。"""
    draft = taskbook_draft.get_draft(draft_id, meta_root)
    if draft is None:
        return {"ok": False, "reason": f"未找到草稿：{draft_id}"}
    if draft.get("status") == "approved":
        return {
            "ok": False,
            "reason": f"该草稿已批准过（分支 {draft.get('branch') or '未知'}），请勿重复批准",
        }
    repo = Path(repo) if repo else _default_repo()
    if shutil.which("git") is None:
        return {"ok": False, "reason": "git 不可用，已跳过分支创建；草稿保持待批准"}
    if not is_git_repo(repo):
        return {"ok": False, "reason": f"当前目录不是 git 仓库（{repo}），已优雅跳过分支创建"}
    slug = str(draft_id).removeprefix(f"{taskbook_draft.DRAFT_PREFIX}-").lower() or "update"
    branch = f"{BRANCH_PREFIX}/{slug}"
    parent = worktree_parent or worktrees_root()
    worktree = parent / slug
    if worktree.exists():
        return {"ok": False, "reason": f"该草稿的隔离分支已存在：{branch}（{worktree}）"}

    base_ref = base or resolve_base_ref(repo)
    if base_ref is None:
        return {"ok": False, "reason": "仓库没有任何可用的基线（main/master/HEAD 均不存在）"}
    try:
        watcher._git(["worktree", "add", "-b", branch, str(worktree), base_ref], cwd=repo)
    except watcher.UpstreamUnavailable as exc:  # git 失败（含中文 stderr 摘要）
        return {"ok": False, "reason": f"创建隔离分支失败：{exc}"}
    except Exception as exc:  # noqa: BLE001 —— 环境问题不该炸路由
        return {"ok": False, "reason": f"创建隔离分支失败：{exc}"}

    proposal = worktree / "MERGE-PROPOSAL.md"
    proposal.write_text(merge_proposal_text(branch, base_ref, worktree, draft), encoding="utf-8")

    record = {
        "id": slug,
        "draft_id": draft_id,
        "branch": branch,
        "worktree": str(worktree),
        "base": base_ref,
        "merge_proposal": str(proposal),
        "status": "proposal",  # 只会是 proposal；合并永远等人工
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    branches = _load_branches(meta_root)
    branches["branches"][slug] = record
    _save_branches(branches, meta_root)
    taskbook_draft.set_draft_status(draft_id, "approved", branch=branch, meta_root=meta_root)
    log.info("evolution.branch.created", branch=branch, worktree=str(worktree))
    return {"ok": True, **record}


def _default_repo() -> Path:
    from atlas.config import PROJECT_ROOT

    return PROJECT_ROOT


def list_branches(meta_root: Path | None = None) -> list[dict[str, Any]]:
    """隔离分支记录（新→旧）。"""
    branches = _load_branches(meta_root)["branches"]
    return sorted(branches.values(), key=lambda b: str(b.get("created_at")), reverse=True)


def get_branch(slug_or_branch: str, meta_root: Path | None = None) -> dict[str, Any] | None:
    for record in list_branches(meta_root):
        if record.get("id") == slug_or_branch or record.get("branch") == slug_or_branch:
            return dict(record)
    return None
