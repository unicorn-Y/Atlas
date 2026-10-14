"""参考项目动态：盯住一流 Agent 项目（Codex、Claude Code、ZCode……）每天改了什么。

和组件追新（inventory/staging）分工：那边管「我们装了/抄了的东西要不要升级」，这里管「别家
最近做了什么值得抄」。每次运行对每个项目：

- 取默认分支最新提交，和上次记录比（GitHub compare），列出提交和改动文件；
- 标出两类重点：命中我们移植过的上游文件（来自代码里的 ``Ported from`` 来源头，新抄的文件
  自动纳入），以及该项目的关注目录（主循环、工具、压缩、子 Agent 等）；
- 新发布的版本和说明；闭源项目（Claude Code）看 CHANGELOG 新增的内容。

报告写到 ``data/upstream/watch/``（``latest.md`` + 按时间存档 + ``latest.json``）。

    python -m atlas.upstream watch          立即跑一次
    scripts/atlas-watch.cmd                 一键运行并打开报告
Atlas 运行时每 24 小时自动跑一次（service.auto_loop）。额外项目写在
``data/upstream/watch.json``：``{"repos": [{"repo": "owner/name", "focus": ["src/"]}]}``。
"""

from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import structlog

from atlas.upstream import provenance, sources
from atlas.upstream.sources import LookupFailed

log = structlog.get_logger()

WATCH_INTERVAL_SECONDS = 24 * 3600
API = "https://api.github.com/repos/"
MAX_COMMITS_LISTED = 40
FIRST_RUN_DAYS = 7
MAX_FILES_LISTED = 60
RELEASE_BODY_CHARS = 1500
PORTED_TABLE = Path("core/atlas/engine_core/PORTED.md")
MAX_DIFF_CHARS = 20_000


@dataclass
class Watched:
    repo: str
    label: str
    tier: str = "主力"  # 主力 / 补充 / 观察
    focus: list[str] = field(default_factory=list)
    changelog: str = ""  # 闭源项目只看 CHANGELOG 的新增
    ported: set[str] = field(default_factory=set)
    ported_refs: list[dict[str, str]] = field(default_factory=list)


# 一流三家优先；其余是 ENGINE 计划书里用到或值得持续看的。路径是前缀匹配。
BUILTIN: list[Watched] = [
    Watched(
        "openai/codex",
        "Codex",
        focus=[
            "codex-rs/core/src/session/",
            "codex-rs/core/src/tools/",
            "codex-rs/core/src/unified_exec/",
            "codex-rs/core/src/agent/",
            "codex-rs/core/src/compact.rs",
            "codex-rs/core/src/apply_patch.rs",
            "codex-rs/core/src/responses_retry.rs",
            "codex-rs/core/src/agents_md.rs",
            "codex-rs/core/src/hook_runtime.rs",
            "codex-rs/models-manager/",
            "codex-rs/git-utils/",
        ],
    ),
    Watched(
        "anthropics/claude-code", "Claude Code（闭源，看 CHANGELOG）", changelog="CHANGELOG.md"
    ),
    Watched(
        "zai-org/ZCode",
        "ZCode",
        focus=[
            "apps/zcode-cli/packages/core/src/agent/",
            "apps/zcode-cli/packages/core/src/tool/",
            "apps/zcode-cli/packages/core/src/compact/",
            "apps/zcode-cli/packages/core/src/context/",
            "apps/zcode-cli/packages/core/src/subagent/",
            "apps/zcode-cli/packages/core/src/workflow/",
            "apps/zcode-cli/packages/dynamic-workflow/",
        ],
    ),
    Watched(
        "anomalyco/opencode",
        "OpenCode",
        tier="补充",
        focus=[
            "packages/opencode/src/session/",
            "packages/opencode/src/tool/",
            "packages/opencode/src/provider/",
            "packages/opencode/src/snapshot/",
            "packages/plugin/",
        ],
    ),
    Watched(
        "earendil-works/pi",
        "Pi",
        tier="补充",
        focus=["packages/agent/src/", "packages/coding-agent/src/core/"],
    ),
    Watched("NousResearch/hermes-agent", "Hermes", tier="补充", focus=["agent/", "tools/"]),
    Watched("openclaw/openclaw", "OpenClaw", tier="补充", focus=["src/agents/"]),
    Watched(
        "deepseek-ai/deepseek-harness",
        "DeepSeek Harness",
        tier="补充",
        focus=["packages/core/", "packages/compaction/", "packages/subagent/", "packages/llm/"],
    ),
    Watched(
        "OpenHands/software-agent-sdk",
        "OpenHands SDK",
        tier="补充",
        focus=[
            "openhands-sdk/openhands/sdk/conversation/",
            "openhands-sdk/openhands/sdk/context/",
            "openhands-sdk/openhands/sdk/agent/",
        ],
    ),
    Watched(
        "code-yeongyu/oh-my-openagent",
        "Oh My OpenAgent",
        tier="补充",
        focus=["packages/hashline-core/", "packages/delegate-core/"],
    ),
    Watched("Aider-AI/aider", "Aider", tier="补充", focus=["aider/repomap.py", "aider/coders/"]),
    Watched("mistralai/mistral-vibe", "Mistral Vibe", tier="观察", focus=["vibe/core/"]),
    Watched("google-gemini/gemini-cli", "Gemini CLI", tier="观察", focus=["packages/core/src/"]),
    Watched("MoonshotAI/kimi-code", "Kimi Code", tier="观察", focus=["packages/agent-core-v2/"]),
    Watched("QwenLM/qwen-code", "Qwen Code", tier="观察", focus=["packages/core/src/"]),
    Watched("aaif-goose/goose", "Goose", tier="观察", focus=["crates/goose/src/"]),
    Watched("cline/cline", "Cline", tier="观察"),
]


def watch_root() -> Path:
    from atlas.upstream.check import upstream_root

    root = upstream_root() / "watch"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path() -> Path:
    return watch_root() / "state.json"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"repos": {}, "last_run": 0}


def watch_due() -> bool:
    return time.time() - float(load_state().get("last_run") or 0) >= WATCH_INTERVAL_SECONDS


def watch_list(repo_root: Path | None = None) -> list[Watched]:
    """内置清单 + ``watch.json`` 里加的 + 代码里所有来源头指向的仓库。"""
    by_repo = {
        w.repo.lower(): Watched(w.repo, w.label, w.tier, list(w.focus), w.changelog)
        for w in BUILTIN
    }
    extra = watch_root().parent / "watch.json"
    if extra.exists():
        try:
            for row in json.loads(extra.read_text(encoding="utf-8")).get("repos", []):
                key = str(row["repo"]).lower()
                item = by_repo.setdefault(
                    key, Watched(row["repo"], row.get("label") or row["repo"], "自定义")
                )
                item.focus += [p for p in row.get("focus", []) if p not in item.focus]
                item.changelog = row.get("changelog", item.changelog)
        except (OSError, ValueError, KeyError) as exc:
            log.warning("upstream.watch_extra_invalid", error=str(exc))
    if repo_root is None:
        from atlas.config import PROJECT_ROOT

        repo_root = PROJECT_ROOT
    hermes = by_repo.get("nousresearch/hermes-agent")
    if hermes:
        hermes.ported_refs = read_ported_manifest(repo_root)
        hermes.ported = {row["source"] for row in hermes.ported_refs}
    for record in provenance.scan(repo_root):
        if not record.repo:
            continue
        item = by_repo.setdefault(record.repo.lower(), Watched(record.repo, record.repo, "已移植"))
        if record.path and item.repo.lower() != "nousresearch/hermes-agent":
            item.ported.add(record.path)
    return list(by_repo.values())


def read_ported_manifest(repo_root: Path) -> list[dict[str, str]]:
    """Read the authoritative Hermes source map from its Markdown table."""
    path = repo_root / PORTED_TABLE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, str]] = []
    for line in lines:
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "source" or re.fullmatch(r"[-: ]+", "".join(cells)):
            continue
        source, destination, commit = cells[:3]
        commit = commit.split()[0].strip("`()")
        commit = commit.rsplit("@", 1)[-1]
        if source and destination and re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
            rows.append({"source": source, "destination": destination, "commit": commit.lower()})
    return rows


def _ported_diffs(repo: str, head: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Fetch only manifest-listed files and produce reviewable unified diffs."""
    diffs = []
    for row in rows:
        old = _file_at(repo, row["commit"], row["source"])
        new = _file_at(repo, head, row["source"])
        if old == new:
            continue
        if old is None and new is None:
            diffs.append({**row, "head": head, "status": "source path missing at both commits",
                          "diff": ""})
            continue
        patch = "\n".join(difflib.unified_diff(
            (old or "").splitlines(), (new or "").splitlines(),
            fromfile=f"{row['source']}@{row['commit']}",
            tofile=f"{row['source']}@{head}", lineterm="",
        ))
        truncated = len(patch) > MAX_DIFF_CHARS
        status = "changed" if old is not None and new is not None else (
            "missing at source commit" if old is None else "removed upstream"
        )
        diffs.append({**row, "head": head, "status": status,
                      "diff": patch[:MAX_DIFF_CHARS], "truncated": truncated})
    return diffs


def _api(path: str) -> Any:
    try:
        return sources.get_json(API + path, headers=sources._github_headers())
    except LookupFailed:  # 偶发断连：再试一次
        time.sleep(3)
        return sources.get_json(API + path, headers=sources._github_headers())


def _by_path(item: Watched, branch: str, since_date: str, done: set[str]) -> tuple[list, list]:
    """对比结果文件太多被截断时，按路径逐个查提交，保证重点不漏。"""
    ported, focus = [], []
    for path, bucket in [
        *((x, ported) for x in sorted(item.ported)),
        *((x, focus) for x in item.focus),
    ]:
        if path in done:
            continue
        rows = _api(
            f"{item.repo}/commits?sha={branch}&path={quote(path)}&since={since_date}&per_page=100"
        )
        if rows:
            bucket.append({"file": path, "status": f"{len(rows)} 个提交", "add": None, "del": None})
    return ported, focus


def _file_at(repo: str, ref: str, path: str) -> str | None:
    return sources.github_file(repo, ref, path)


def _changelog_added(repo: str, path: str, old: str, new: str) -> str:
    before, after = _file_at(repo, old, path) or "", _file_at(repo, new, path) or ""
    if not after or before == after:
        return ""
    # CHANGELOG 新内容都在顶部：取新文件里旧文件开头之前的部分。
    head = before.strip().splitlines()[:3]
    anchor = "\n".join(head)
    cut = after.find(anchor) if anchor else -1
    added = after[:cut] if cut > 0 else after[:4000]
    return added.strip()[:6000]


def _releases_since(repo: str, last_tag: str, after: str = "") -> list[dict[str, Any]]:
    rows = _api(f"{repo}/releases?per_page=8")
    fresh = []
    for row in rows:
        if row.get("draft"):
            continue
        if (last_tag and row.get("tag_name") == last_tag) or (
            after and (row.get("published_at") or "")[:10] < after
        ):
            break
        fresh.append(
            {
                "tag": row.get("tag_name"),
                "name": row.get("name") or "",
                "date": (row.get("published_at") or "")[:10],
                "url": row.get("html_url"),
                "body": (row.get("body") or "").strip()[:RELEASE_BODY_CHARS],
            }
        )
    return fresh


def _classify(files: list[dict[str, Any]], item: Watched) -> tuple[list, list, int]:
    ported, focus, other = [], [], 0
    for f in files:
        name = f.get("filename", "")
        row = {
            "file": name,
            "status": f.get("status"),
            "add": f.get("additions", 0),
            "del": f.get("deletions", 0),
        }
        if name in item.ported:
            ported.append(row)
        elif any(name.startswith(p) for p in item.focus):
            focus.append(row)
        else:
            other += 1
    return ported, focus, other


def check_repo(item: Watched, state: dict[str, Any]) -> dict[str, Any]:
    branch = state.get("branch") or sources.github_default_branch(item.repo)
    head = _api(f"{item.repo}/commits/{branch}")["sha"]
    result: dict[str, Any] = {
        "repo": item.repo,
        "label": item.label,
        "tier": item.tier,
        "branch": branch,
        "head": head,
        "since": state.get("sha", ""),
    }
    releases_rows = _api(f"{item.repo}/releases?per_page=1")
    newest_tag = releases_rows[0].get("tag_name", "") if releases_rows else ""
    result["latest_release"] = newest_tag
    if item.repo.lower() == "nousresearch/hermes-agent" and item.ported_refs:
        result["ported_diffs"] = _ported_diffs(item.repo, head, item.ported_refs)
    since = state.get("sha", "")
    if not since:
        # 第一次：回看最近 FIRST_RUN_DAYS 天，而不是只记个基线。
        result["first_run"] = True
        cutoff = datetime.now(UTC) - timedelta(days=FIRST_RUN_DAYS)
        older = _api(
            f"{item.repo}/commits?sha={branch}&until={cutoff:%Y-%m-%dT%H:%M:%SZ}&per_page=1"
        )
        if not older:
            return result
        since = older[0]["sha"]
        result["since"] = since
        result["releases"] = _releases_since(item.repo, "", after=f"{cutoff:%Y-%m-%d}")
    elif state.get("tag") and newest_tag != state.get("tag"):
        result["releases"] = _releases_since(item.repo, state["tag"])
    if head == since:
        return result
    cmp = _api(f"{item.repo}/compare/{since}...{head}")
    commits = cmp.get("commits") or []
    result["commit_count"] = cmp.get("total_commits", len(commits))
    result["commits"] = [
        {
            "sha": c["sha"][:10],
            "date": (c["commit"]["committer"]["date"] or "")[:10],
            "msg": c["commit"]["message"].splitlines()[0][:160],
        }
        for c in reversed(commits)
    ][:MAX_COMMITS_LISTED]
    files = cmp.get("files") or []
    result["files_truncated"] = len(files) >= 300
    result["ported"], result["focus"], result["other_files"] = _classify(files, item)
    if result["files_truncated"]:
        since_date = (
            (cmp.get("base_commit") or {}).get("commit", {}).get("committer", {}).get("date", "")
        )
        done = {f["file"] for f in result["ported"] + result["focus"]}
        extra_ported, extra_focus = _by_path(item, branch, since_date, done)
        result["ported"] += extra_ported
        result["focus"] += extra_focus
    result["compare_url"] = cmp.get("html_url")
    if item.changelog:
        result["changelog"] = _changelog_added(item.repo, item.changelog, since, head)
    return result


def run_watch(repo_root: Path | None = None) -> dict[str, Any]:
    state = load_state()
    repos_state = state.setdefault("repos", {})
    report: dict[str, Any] = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "repos": []}
    for item in watch_list(repo_root):
        prev = repos_state.get(item.repo.lower(), {})
        try:
            row = check_repo(item, prev)
        except (LookupFailed, KeyError, IndexError, TypeError, ValueError) as exc:
            report["repos"].append(
                {"repo": item.repo, "label": item.label, "tier": item.tier, "error": str(exc)[:300]}
            )
            continue
        report["repos"].append(row)
        tag = (
            (row.get("releases") or [{}])[0].get("tag")
            or row.get("latest_release")
            or prev.get("tag", "")
        )
        repos_state[item.repo.lower()] = {
            "sha": row["head"],
            "branch": row["branch"],
            "tag": tag,
            "checked": report["at"],
        }
    state["last_run"] = time.time()
    _state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report)
    return report


def _file_line(f: dict[str, Any]) -> str:
    size = f" +{f['add']}/-{f['del']}" if f.get("add") is not None else ""
    return f"- `{f['file']}` {f['status']}{size}"


def _quote(text: str) -> str:
    """上游说明自带的 Markdown 标题会打乱报告结构：整段放进引用块。"""
    return "\n".join("> " + line if line.strip() else ">" for line in text.strip().splitlines())


def _changed(row: dict[str, Any]) -> bool:
    return bool(
        row.get("commits") or row.get("releases") or row.get("changelog") or row.get("ported_diffs")
    )


def render(report: dict[str, Any]) -> str:
    rows = report["repos"]
    changed = [r for r in rows if _changed(r)]
    hits = sum(len(r.get("ported") or []) for r in rows)
    lines = [
        f"# 参考项目动态 {report['at'][:16].replace('T', ' ')} UTC",
        "",
        f"{len(rows)} 个项目，{len(changed)} 个有新动态；命中我们移植过的文件 {hits} 个。",
        "",
    ]
    order = {"主力": 0, "已移植": 1, "补充": 2, "自定义": 3, "观察": 4}
    rows = sorted(rows, key=lambda r: (order.get(r.get("tier", ""), 9), r["repo"]))
    lines += [
        "| 项目 | 档 | 新版本 | 新提交 | 命中已移植 | 关注目录改动 |",
        "|---|---|---|---:|---:|---:|",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(f"| {r['label']} | {r.get('tier', '')} | 查询失败 | | | |")
            continue
        tags = "、".join(x["tag"] for x in (r.get("releases") or [])[:3])
        lines.append(
            f"| {r['label']} | {r.get('tier', '')} | {tags} | {r.get('commit_count', 0)} "
            f"| {len(r.get('ported') or [])} | {len(r.get('focus') or [])} |"
        )
    lines.append("")
    for r in rows:
        title = f"## {r['label']}（{r['repo']}，{r.get('tier', '')}）"
        if r.get("error"):
            lines += [title, f"查询失败：{r['error']}", ""]
            continue
        if not _changed(r):
            continue
        lines.append(title)
        if r.get("first_run"):
            lines += [
                f"（首次运行：列出最近 {FIRST_RUN_DAYS} 天；"
                f"最新发布 {r.get('latest_release') or '无'}）",
                "",
            ]
        for rel in r.get("releases") or []:
            lines.append(f"### 新版本 [{rel['tag']}]({rel['url']})（{rel['date']}）{rel['name']}")
            if rel["body"] and not r.get("changelog"):  # 有 CHANGELOG 时说明是重复的
                lines += ["", _quote(rel["body"])]
            lines.append("")
        if r.get("changelog"):
            lines += ["### CHANGELOG 新增", "", _quote(r["changelog"]), ""]
        if r.get("ported_diffs"):
            lines += ["**PORTED.md 来源文件 diff（只读报告；请人工审查并决定是否修改）：**"]
            for entry in r["ported_diffs"]:
                lines += [
                    "",
                    f"#### `{entry['source']}` → `{entry['destination']}`",
                    f"来源 `{entry['commit']}` → 上游 `{entry.get('head', r.get('head', ''))}` · "
                    f"{entry['status']}" + (" · diff 已截断" if entry.get("truncated") else ""),
                    "",
                    "```diff",
                    entry.get("diff", ""),
                    "```",
                ]
        if r.get("commits"):
            lines.append(
                f"{r['commit_count']} 个新提交（[完整对比]({r.get('compare_url')})）"
                + ("；文件列表已截断" if r.get("files_truncated") else "")
            )
            if r.get("ported"):
                lines.append("\n**本轮提交命中的移植来源路径：**")
                lines += [_file_line(f) for f in r["ported"]]
            if r.get("focus"):
                lines.append("\n**关注目录的改动：**")
                lines += [_file_line(f) for f in r["focus"][:MAX_FILES_LISTED]]
                if len(r["focus"]) > MAX_FILES_LISTED:
                    lines.append(f"- ……另有 {len(r['focus']) - MAX_FILES_LISTED} 个")
            if r.get("other_files"):
                more = "（GitHub 只返回前 300 个，实际更多）" if r.get("files_truncated") else ""
                lines.append(f"\n其他目录改动 {r['other_files']} 个文件{more}。")
            lines.append("\n提交：")
            lines += [f"- {c['date']} `{c['sha']}` {c['msg']}" for c in r["commits"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: dict[str, Any]) -> Path:
    root = watch_root()
    text = render(report)
    stamp = report["at"][:16].replace(":", "").replace("-", "").replace("T", "-")
    (root / f"{stamp}.md").write_text(text, encoding="utf-8")
    (root / "latest.md").write_text(text, encoding="utf-8")
    (root / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return root / "latest.md"


def latest() -> dict[str, Any]:
    root = watch_root()
    md = root / "latest.md"
    return {
        "markdown": md.read_text(encoding="utf-8") if md.exists() else "",
        "path": str(md),
        "last_run": load_state().get("last_run") or 0,
    }
