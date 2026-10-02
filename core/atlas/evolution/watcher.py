"""E1 上游/更新监视（“自动追新”的取数层）。

策略（确定性、绝不阻塞启动）：

- 优先本地 git：``git -C <mirror> fetch <remote>`` 再读提交/标签
  （hermes-agent 本地镜像 D:/hermes-agent）。
- 无镜像时走 GitHub REST（httpx，短超时），``releases`` 类来源只看发布页。
- 任何失败都转成 :class:`UpstreamUnavailable`（中文错误），``run_check`` 按来源收集错误、
  继续服务缓存数据；监视只在按需调用（POST /api/evolution/check）时运行。

缓存布局（``<data>/evolution/sources.json``）::

    {
      "sources":  [{id, repo, kind, mirror_path?, remote, ref}, ...],
      "state":    {"<source_id>": {last_id?, seen_ids?: [...], last_checked_at?, last_ok_at?}},
      "entries":  {"<source_id>": [entry, ...]}   # 最新在前，每来源封顶 MAX_ENTRIES
    }

entry 结构（纯 dict，方便测试与序列化）::

    {"id", "kind": "commit"|"tag"|"release", "repo", "ref", "title", "subject",
     "body", "files": [...], "published_at", "url"}
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# 每来源单次最多读取的条数与缓存封顶。
FETCH_LIMIT = 30
MAX_ENTRIES = 200
# seen_ids 集合封顶（防止 sources.json 无限膨胀；超出部分丢弃最旧的 id）。
MAX_SEEN_IDS = 500
# 网络短超时（秒），离线时快速失败，绝不拖住请求。
HTTP_TIMEOUT_SECONDS = 8.0
GIT_TIMEOUT_SECONDS = 20

#: 本地 hermes-agent 镜像（可被环境变量覆盖，测试里通常用 tmp 仓库）。
HERMES_MIRROR = os.environ.get("ATLAS_HERMES_MIRROR", "D:/hermes-agent")


def evolution_root() -> Path:
    """evolution 数据根目录：``get_config().db_path.parent / "evolution"``。"""
    from atlas.config import get_config

    return get_config().db_path.parent / "evolution"


class UpstreamUnavailable(RuntimeError):  # noqa: N818 —— 名称面向调用方语义，保持无后缀
    """上游暂不可达（离线 / 超时 / 非镜像且无网络）。消息面向用户，中文。"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "src"


# ---------------------------------------------------------------------------
# 默认监视清单（与 docs/plan/SOURCE-MAP.md 对齐）
# ---------------------------------------------------------------------------

def default_sources() -> list[dict[str, Any]]:
    """默认监视来源；克隆 hermes-agent 时才启用本地镜像来源。"""
    sources: list[dict[str, Any]] = [
        {"id": "hermes-agent", "repo": "NousResearch/hermes-agent", "kind": "commit",
         "mirror_path": HERMES_MIRROR, "remote": "upstream", "ref": "main"},
        {"id": "codex", "repo": "openai/codex", "kind": "commit",
         "remote": "origin", "ref": "main"},
        # anthropics/claude-code 没有可读的 main 历史（闭源发行），只看 releases。
        {"id": "claude-code", "repo": "anthropics/claude-code", "kind": "release",
         "remote": "origin", "ref": "main"},
        {"id": "opencode", "repo": "anomalyco/opencode", "kind": "commit",
         "remote": "origin", "ref": "main"},
        {"id": "pi-mono", "repo": "badlogic/pi-mono", "kind": "commit",
         "remote": "origin", "ref": "main"},
        {"id": "browser-use", "repo": "browser-use/browser-use", "kind": "release",
         "remote": "origin", "ref": "main"},
        {"id": "stagehand", "repo": "browserbase/stagehand", "kind": "release",
         "remote": "origin", "ref": "main"},
    ]
    # 本地镜像不存在时退回 GitHub REST，一样能追新。
    if not Path(HERMES_MIRROR).is_dir():
        sources[0].pop("mirror_path", None)
        sources[0]["remote"] = "origin"
    return sources


_KINDS = {"commit", "tag", "release"}


# ---------------------------------------------------------------------------
# 存储层（sources.json）
# ---------------------------------------------------------------------------

class EvolutionStore:
    """sources.json 的读写封装；每次写入都是“整体替换 + 原子改名”。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else evolution_root()
        self.path = self.root / "sources.json"
        self.data: dict[str, Any] = {"sources": [], "state": {}, "entries": {}}
        self.load()

    # -- io --

    def load(self) -> None:
        try:
            import json

            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            log.warning("evolution.store.corrupt", path=str(self.path))
            return
        if isinstance(raw, dict):
            self.data = {
                "sources": raw.get("sources") or [],
                "state": raw.get("state") or {},
                "entries": raw.get("entries") or {},
            }

    def save(self) -> None:
        import json

        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # -- sources --

    def list_sources(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self.data["sources"]]

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        for source in self.data["sources"]:
            if source.get("id") == source_id:
                return dict(source)
        return None

    def add_source(self, source: dict[str, Any]) -> dict[str, Any]:
        repo = str(source.get("repo", "")).strip()
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise ValueError("仓库格式应为 owner/name，例如 openai/codex")
        kind = str(source.get("kind", "commit")).strip().lower()
        if kind not in _KINDS:
            raise ValueError("kind 只支持 commit / tag / release")
        source_id = str(source.get("id") or "").strip() or _slug(repo.split("/")[-1])
        if self.get_source(source_id) is not None:
            raise ValueError(f"来源已存在：{source_id}")
        record = {
            "id": source_id,
            "repo": repo,
            "kind": kind,
            "remote": str(source.get("remote") or "origin"),
            "ref": str(source.get("ref") or "main"),
        }
        if source.get("mirror_path"):
            record["mirror_path"] = str(source["mirror_path"])
        self.data["sources"].append(record)
        self.save()
        return record

    def remove_source(self, source_id: str) -> bool:
        before = len(self.data["sources"])
        self.data["sources"] = [s for s in self.data["sources"] if s.get("id") != source_id]
        removed = len(self.data["sources"]) < before
        if removed:
            self.data["state"].pop(source_id, None)
            self.data["entries"].pop(source_id, None)
            self.save()
        return removed

    def ensure_defaults(self) -> None:
        if not self.data["sources"]:
            self.data["sources"] = default_sources()
            self.save()

    # -- state / entries --

    def get_state(self, source_id: str) -> dict[str, Any]:
        return dict(self.data["state"].get(source_id) or {})

    def set_state(self, source_id: str, **fields: Any) -> None:
        state = self.data["state"].setdefault(source_id, {})
        state.update(fields)

    def cached_entries(self, source_id: str) -> list[dict[str, Any]]:
        return list(self.data["entries"].get(source_id) or [])

    def append_entries(self, source_id: str, new_entries: list[dict[str, Any]]) -> None:
        """新条目插到最前（fetch 返回最新在前），并封顶。"""
        merged = list(new_entries) + self.cached_entries(source_id)
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for entry in merged:
            key = str(entry.get("id"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        self.data["entries"][source_id] = unique[:MAX_ENTRIES]

    def all_entries(self) -> list[dict[str, Any]]:
        """全部缓存条目（附 source 字段），最新来源顺序稳定，供离线分类。"""
        flat: list[dict[str, Any]] = []
        for source in self.data["sources"]:
            sid = str(source["id"])
            for entry in self.data["entries"].get(sid) or []:
                item = dict(entry)
                item.setdefault("source", sid)
                flat.append(item)
        return flat


# ---------------------------------------------------------------------------
# 本地 git 读取（离线安全：fetch 失败仍可读本地已有的引用）
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit={proc.returncode}"
        raise UpstreamUnavailable(f"git 命令失败（{' '.join(args[:3])}…）：{detail}")
    return proc.stdout


def _entry_from_commit(
    repo: str, ref: str, header: list[str], files: list[str], body: str = "",
) -> dict[str, Any]:
    sha, subject, header_body, date = (header + ["", "", "", ""])[:4]
    return {
        "id": sha,
        "kind": "commit",
        "repo": repo,
        "ref": ref,
        "title": subject,
        "subject": subject,
        "body": (body or header_body).strip(),
        "files": files,
        "published_at": date,
        "url": f"https://github.com/{repo}/commit/{sha}",
    }


def _read_local_commits(source: dict[str, Any], last_id: str | None) -> list[dict[str, Any]]:
    """读取镜像里 ``<remote>/<ref>`` 的最近提交；遇到上次见过的 sha 即停。"""
    mirror = Path(str(source["mirror_path"]))
    remote = str(source.get("remote") or "origin")
    ref = str(source.get("ref") or "main")
    output = _git(
        ["log", f"-n{FETCH_LIMIT}", "--date=iso-strict",
         "--format=%H%x1f%s%x1f%b%x1f%cI", "--name-status", f"{remote}/{ref}"],
        cwd=mirror,
    )
    entries: list[dict[str, Any]] = []
    header: list[str] | None = None
    files: list[str] = []
    body: list[str] = []
    for line in output.splitlines():
        if "\x1f" in line:  # 新提交的头（sha␟subject␟body␟date）
            if header is not None:
                entries.append(_entry_from_commit(
                    source["repo"], ref, header, files, "\n".join(body)))
                if last_id and entries[-1]["id"] == last_id:
                    return entries
            header = line.split("\x1f")
            files = []
            body = []
        elif not line.strip() or header is None:
            continue
        elif "\t" in line:  # --name-status 行形如 “M\tpath” / “R100\told\tnew”
            files.append(line.strip().split("\t")[-1])
        else:  # 多行 commit body 的续行
            body.append(line)
    if header is not None:
        entries.append(_entry_from_commit(
            source["repo"], ref, header, files, "\n".join(body)))
    return entries


def _read_local_tags(source: dict[str, Any], last_id: str | None) -> list[dict[str, Any]]:
    """读取本地全部标签（最新在前；fetch 由 :func:`_fetch_local_git` 统一负责，失败容忍）。

    不按 ``last_id`` 提前截断：同秒创建的标签 creatordate 相同，排序不稳定，
    “见过哪些”由 ``run_check`` 的 seen_ids 集合兜底。
    """
    mirror = Path(str(source["mirror_path"]))
    output = _git(
        ["for-each-ref", "refs/tags", "--sort=-creatordate",
         "--format=%(refname:short)%09%(creatordate:iso-strict)%09%(contents:subject)"],
        cwd=mirror,
    )
    entries: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = (line.split("\t") + ["", ""])[:3]
        name, date, subject = parts
        if not name:
            continue
        entries.append({
            "id": name,
            "kind": "tag",
            "repo": source["repo"],
            "ref": name,
            "title": subject or name,
            "subject": subject or name,
            "body": "",
            "files": [],
            "published_at": date,
            "url": f"https://github.com/{source['repo']}/releases/tag/{name}",
        })
    return entries[:FETCH_LIMIT]


def _fetch_local_git(source: dict[str, Any], last_id: str | None) -> list[dict[str, Any]]:
    mirror = Path(str(source["mirror_path"]))
    if not (mirror / ".git").exists() and not (mirror / "HEAD").exists():
        raise UpstreamUnavailable(f"本地镜像不存在：{source['mirror_path']}")
    try:
        _git(["fetch", str(source.get("remote") or "origin"), "--quiet"], cwd=mirror)
    except UpstreamUnavailable as exc:  # 离线：退回本地已有引用，读得到就用缓存
        log.warning("evolution.fetch.offline_git", source=source["id"], error=str(exc))
    if source.get("kind") == "tag":
        return _read_local_tags(source, last_id)
    return _read_local_commits(source, last_id)


# ---------------------------------------------------------------------------
# GitHub REST 读取（httpx，短超时）
# ---------------------------------------------------------------------------

def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "atlas-evolution/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("ATLAS_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_github(source: dict[str, Any], last_id: str | None) -> list[dict[str, Any]]:
    import httpx

    repo = source["repo"]
    if source.get("kind") == "release":
        url = f"https://api.github.com/repos/{repo}/releases"
        params = {"per_page": FETCH_LIMIT}
    else:
        url = f"https://api.github.com/repos/{repo}/commits"
        params = {"per_page": FETCH_LIMIT, "sha": str(source.get("ref") or "main")}
    try:
        resp = httpx.get(
            url, params=params, headers=_github_headers(),
            timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 —— 网络层一切失败都转成统一的中文离线错误
        raise UpstreamUnavailable(
            f"上游 {repo} 暂不可达（离线或网络超时），本次使用缓存数据"
        ) from exc
    if not isinstance(payload, list):
        raise UpstreamUnavailable(f"上游 {repo} 返回了意外格式，本次使用缓存数据")

    entries: list[dict[str, Any]] = []
    for item in payload:
        if source.get("kind") == "release":
            tag = str(item.get("tag_name") or "")
            if not tag:
                continue
            entries.append({
                "id": tag,
                "kind": "release",
                "repo": repo,
                "ref": tag,
                "title": str(item.get("name") or tag),
                "subject": str(item.get("name") or tag),
                "body": str(item.get("body") or ""),
                "files": [],
                "published_at": item.get("published_at") or "",
                "url": str(item.get("html_url") or f"https://github.com/{repo}/releases/tag/{tag}"),
            })
        else:
            sha = str(item.get("sha") or "")
            commit = item.get("commit") or {}
            message = str(commit.get("message") or "")
            subject, _, body = message.partition("\n")
            entries.append({
                "id": sha,
                "kind": "commit",
                "repo": repo,
                "ref": str(source.get("ref") or "main"),
                "title": subject.strip(),
                "subject": subject.strip(),
                "body": body.strip(),
                "files": [],
                "published_at": str((commit.get("author") or {}).get("date") or ""),
                "url": f"https://github.com/{repo}/commit/{sha}",
            })
        if last_id and entries[-1]["id"] == last_id:
            break
    return entries


#: 取数函数签名：(source, last_id) -> entries（最新在前）。测试注入 fake。
Fetcher = Callable[[dict[str, Any], str | None], list[dict[str, Any]]]


def default_fetcher(source: dict[str, Any], last_id: str | None) -> list[dict[str, Any]]:
    """镜像存在走本地 git，否则走 GitHub REST。"""
    if source.get("mirror_path"):
        return _fetch_local_git(source, last_id)
    return _fetch_github(source, last_id)


# ---------------------------------------------------------------------------
# run_check —— 按需执行的一次监视
# ---------------------------------------------------------------------------

def run_check(
    store: EvolutionStore | None = None,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """对所有来源跑一轮监视；单来源失败不影响其它来源，也绝不抛出。

    “新条目”的判定用 ``seen_ids`` 集合（而不是只比最新 id）：标签/发布可能同秒
    创建导致排序不稳，集合兜底才确定。fetcher 仍收到 ``last_id`` 供提前截断。
    """
    store = store or EvolutionStore()
    store.ensure_defaults()
    fetch = fetcher or default_fetcher
    checked_at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []
    for source in store.list_sources():
        sid = str(source["id"])
        state = store.get_state(sid)
        store.set_state(sid, last_checked_at=checked_at)
        try:
            fetched = fetch(source, state.get("last_id"))
        except UpstreamUnavailable as exc:
            results.append({"id": sid, "repo": source["repo"], "ok": False, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 —— fetcher 实现自身的 bug 也不拖垮整轮
            log.exception("evolution.check.failed", source=sid)
            results.append({
                "id": sid, "repo": source["repo"], "ok": False,
                "error": f"读取上游失败：{exc}",
            })
            continue
        seen: set[str] = set(state.get("seen_ids") or [])
        new_entries = [e for e in fetched if e.get("id") and str(e["id"]) not in seen]
        seen.update(str(e["id"]) for e in fetched if e.get("id"))
        store.append_entries(sid, new_entries)
        newest = new_entries[0]["id"] if new_entries else state.get("last_id")
        store.set_state(sid, last_id=newest, last_ok_at=checked_at,
                        seen_ids=sorted(seen)[-MAX_SEEN_IDS:])
        results.append({
            "id": sid, "repo": source["repo"], "ok": True,
            "new_entries": len(new_entries), "total_entries": len(store.cached_entries(sid)),
        })
    store.save()
    errors = [r for r in results if not r["ok"]]
    return {
        "checked_at": checked_at,
        "ok": not errors,
        "checked": len(results),
        "results": results,
        "errors": [r["error"] for r in errors],
    }


def list_sources(store: EvolutionStore | None = None) -> list[dict[str, Any]]:
    """来源清单（附带各自的状态与缓存条数）。"""
    store = store or EvolutionStore()
    store.ensure_defaults()
    out: list[dict[str, Any]] = []
    for source in store.list_sources():
        sid = str(source["id"])
        out.append({**source, "state": store.get_state(sid),
                    "cached_entries": len(store.cached_entries(sid))})
    return out
