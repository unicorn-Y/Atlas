"""自动盘点 Atlas 里所有第三方组件，并查各自的最新版本。

每个扫描器只读文件、跑只读命令（``git fetch`` 只更新远端引用，不动工作区），失败时产出一条
``error`` 状态的组件而不是抛错，所以一处查不到不会让整张清单空掉。
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from packaging.requirements import InvalidRequirement, Requirement

from atlas.upstream import provenance, sources
from atlas.upstream.classify import normalize_pip, npm_category, pip_category
from atlas.upstream.model import (
    AUTO,
    ERROR,
    HOT,
    LATEST,
    MANUAL,
    OUTDATED,
    REVIEW,
    UNKNOWN,
    Component,
)
from atlas.upstream.sources import LookupFailed

log = structlog.get_logger()

@dataclass
class Context:
    repo: Path
    python: str
    atlas_dir: Path
    config_path: Path | None = None
    fetch: bool = True               # 允许 git fetch / 联网查询
    errors: list[str] = field(default_factory=list)

    @property
    def pyproject(self) -> Path:
        return self.repo / "core" / "pyproject.toml"


def default_context(fetch: bool = True) -> Context:
    import sys

    from atlas.config import CONFIG_PATH, PROJECT_ROOT

    return Context(repo=PROJECT_ROOT, python=sys.executable,
                   atlas_dir=PROJECT_ROOT,
                   config_path=CONFIG_PATH, fetch=fetch)


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def _requirements(pyproject: Path) -> list[tuple[Requirement, str]]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    rows: list[tuple[Requirement, str]] = []
    groups = [("", data.get("dependencies", []))]
    groups += list((data.get("optional-dependencies") or {}).items())
    for group, specs in groups:
        for spec in specs:
            try:
                rows.append((Requirement(spec), group))
            except InvalidRequirement:
                log.warning("upstream.bad_requirement", spec=spec)
    return rows


def scan_pip(ctx: Context) -> list[Component]:
    installed = sources.pip_installed(ctx.python)
    outdated = sources.pip_outdated(ctx.python) if ctx.fetch else {}
    direct: set[str] = set()
    items: list[Component] = []
    for req, group in _requirements(ctx.pyproject):
        name = normalize_pip(req.name)
        direct.add(name)
        if req.url:
            continue  # git 直引由 scan_git_pins 处理
        current = installed.get(name)
        if current is None:
            continue  # 没装的可选依赖组
        component = Component(
            id=f"pip:{name}", name=req.name, category=pip_category(name, group), kind="pip",
            current=current, latest=outdated.get(name, current) if ctx.fetch else "",
            spec=str(req.specifier), source="PyPI", url=f"https://pypi.org/project/{name}/",
            locations=["core/pyproject.toml"],
            note=("开发依赖" if group in {"dev", "release"}
                  else (f"可选组 [{group}]" if group else "")),
        )
        component.resolve_status()
        items.append(component)
    rest = [
        {"name": name, "current": installed.get(name, ""), "latest": latest}
        for name, latest in sorted(outdated.items())
        if name not in direct
    ]
    items.append(Component(
        id="pip:*transitive", name="Python 间接依赖", category="transitive", kind="pip-transitive",
        current=f"{len(rest)} 个可更新" if rest else "全部最新",
        latest="", status=(OUTDATED if rest else LATEST) if ctx.fetch else UNKNOWN,
        source="PyPI", locations=["core/requirements.lock"],
        detail={"packages": rest},
    ))
    return items


_GIT_URL = re.compile(r"^git\+(https://github\.com/([\w.-]+/[\w.-]+?))(?:\.git)?@([0-9a-f]{7,40})$")


def scan_git_pins(ctx: Context) -> list[Component]:
    items = []
    for req, group in _requirements(ctx.pyproject):
        if not req.url:
            continue
        match = _GIT_URL.match(req.url)
        name = normalize_pip(req.name)
        component = Component(
            id=f"git:{name}", name=req.name, category=pip_category(name, group), kind="git-pin",
            strategy=AUTO, source="GitHub", locations=["core/pyproject.toml"],
            note=f"可选组 [{group}]" if group else "",
        )
        if not match:
            component.status, component.note = MANUAL, "不是 GitHub 提交号形式的引用"
            component.strategy = MANUAL
            items.append(component)
            continue
        url, repo, sha = match.groups()
        component.url = f"https://github.com/{repo}"
        component.current = sha[:10]
        component.detail = {"repo": repo, "sha": sha}
        if ctx.fetch:
            head = sources.github_head(repo)
            component.latest = head[:10]
            component.detail["latest_sha"] = head
        component.resolve_status()
        items.append(component)
    return items


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


def _package_jsons(repo: Path) -> list[tuple[str, Path]]:
    """(工作区名, package.json)。根目录 + workspaces + 带依赖的 backend-adapter。"""
    root = repo / "package.json"
    found = [("atlas", root)] if root.exists() else []
    if root.exists():
        for pattern in json.loads(root.read_text(encoding="utf-8")).get("workspaces", []):
            for path in sorted(repo.glob(f"{pattern}/package.json")):
                found.append((path.parent.name, path))
    adapter = repo / "backend-adapter" / "package.json"
    if adapter.exists() and all(path != adapter for _, path in found):
        found.append(("backend-adapter", adapter))
    return found


def _installed_npm(repo: Path, workspace_dir: Path, name: str) -> str:
    for base in (workspace_dir / "node_modules", repo / "node_modules"):
        manifest = base / name / "package.json"
        if manifest.exists():
            try:
                return str(json.loads(manifest.read_text(encoding="utf-8")).get("version", ""))
            except ValueError:
                return ""
    return ""


def scan_npm(ctx: Context) -> list[Component]:
    outdated = sources.npm_outdated(ctx.repo) if ctx.fetch else {}

    def latest_of(name: str) -> str:
        entry = outdated.get(name)
        if isinstance(entry, list):
            entry = entry[0] if entry else None
        return str(entry.get("latest", "")) if isinstance(entry, dict) else ""

    items: dict[str, Component] = {}
    declared: set[str] = set()
    for workspace, manifest in _package_jsons(ctx.repo):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        rel = manifest.relative_to(ctx.repo).as_posix()
        for section, dev in (("dependencies", False), ("devDependencies", True)):
            for name, spec in (data.get(section) or {}).items():
                declared.add(name)
                if str(spec).startswith(("file:", "link:", "workspace:")):
                    continue
                key = f"npm:{name}"
                if key in items:
                    items[key].locations.append(rel)
                    continue
                current = _installed_npm(ctx.repo, manifest.parent, name)
                component = Component(
                    id=key, name=name, category=npm_category(name, dev), kind="npm",
                    current=current, latest=(latest_of(name) or current) if ctx.fetch else "",
                    spec=str(spec), source="npm", url=f"https://www.npmjs.com/package/{name}",
                    locations=[rel], note="开发依赖" if dev else "",
                    detail={"workspace": workspace, "dev": dev},
                )
                if not current:
                    component.status, component.note = UNKNOWN, "还没装（先 npm ci）"
                else:
                    component.resolve_status()
                items[key] = component
    rest = []
    for name, entry in sorted(outdated.items()):
        if name in declared:
            continue
        entries = entry if isinstance(entry, list) else [entry]
        for row in entries:
            if row.get("current") and row.get("current") != row.get("latest"):
                rest.append({"name": name, "current": row.get("current"),
                             "latest": row.get("latest"), "wanted": row.get("wanted"),
                             "dependent": row.get("dependent")})
                break
    in_range = [row for row in rest if row.get("wanted") and row["wanted"] != row["current"]]
    transitive = Component(
        id="npm:*transitive", name="前端间接依赖", category="transitive", kind="npm-transitive",
        current=f"{len(in_range)} 个可在范围内更新" if in_range else "范围内已最新",
        status=(OUTDATED if in_range else LATEST) if ctx.fetch else UNKNOWN,
        source="npm", locations=["package-lock.json"],
        note=(f"另有 {len(rest) - len(in_range)} 个受上层包的版本范围限制，随上层包更新"
              if len(rest) > len(in_range) else ""),
        detail={"packages": rest},
    )
    return [*items.values(), transitive]


# ---------------------------------------------------------------------------
# MCP / 运行时
# ---------------------------------------------------------------------------

_NPX_SPEC = re.compile(r"^(@[\w.-]+/[\w.-]+|[\w.-]+)@(\d[\w.+-]*)$")


def _mcp_servers(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    return dict((data.get("tools") or {}).get("servers") or {})


def scan_mcp(ctx: Context, npm_items: dict[str, Component]) -> list[Component]:
    """MCP 启动参数里锁的包版本。同名包若也是 npm 依赖，就并到那一项里（一起更新）。"""
    files = [ctx.repo / "config" / "atlas.example.toml"]
    if ctx.config_path and ctx.config_path.exists() and ctx.config_path not in files:
        files.append(ctx.config_path)
    seen: dict[str, Component] = {}
    for path in files:
        label = path.name
        for server, spec in _mcp_servers(path).items():
            if not isinstance(spec, dict) or spec.get("transport", "stdio") != "stdio":
                continue
            command = Path(str(spec.get("command", ""))).stem.lower()
            args = [str(arg) for arg in spec.get("args") or []]
            if command not in {"npx", "uvx", "bunx", "pnpx"}:
                key = f"mcp:{server}"
                seen.setdefault(key, Component(
                    id=key, name=server, category="mcp", kind="mcp-command", strategy=MANUAL,
                    status=UNKNOWN, current=str(spec.get("command", "")), locations=[label],
                    note="本机命令启动，版本由它自己的安装方式管理"))
                continue
            package = next((arg for arg in args if not arg.startswith("-")), "")
            match = _NPX_SPEC.match(package)
            name = match.group(1) if match else package
            version = match.group(2) if match else ""
            npm_key = f"npm:{name}"
            if npm_key in npm_items:
                npm_items[npm_key].detail.setdefault("mcp_refs", []).append(
                    {"file": label, "server": server, "version": version})
                continue
            key = f"mcp:{name}"
            if key in seen:
                seen[key].locations.append(label)
                continue
            component = Component(
                id=key, name=name, category="mcp", kind="mcp-npx", strategy=HOT,
                current=version or "未锁版本", locations=[label], source="npm",
                url=f"https://www.npmjs.com/package/{name}",
                detail={"server": server, "command": command},
            )
            if not version:
                component.status, component.note = LATEST, "未锁版本，启动时自动取最新"
            elif ctx.fetch and command != "uvx":
                component.latest = sources.npm_latest(name)
                component.resolve_status()
            seen[key] = component
    return list(seen.values())


def scan_runtime(ctx: Context) -> list[Component]:
    import platform

    items = []
    node_manifest = ctx.repo / "frontend" / "node-runtime.json"
    if node_manifest.exists():
        manifest = json.loads(node_manifest.read_text(encoding="utf-8"))
        current = str(manifest.get("version", ""))
        component = Component(
            id="runtime:node-bundled", name="安装包内置 Node", category="runtime",
            kind="node-bundled", current=current, source="nodejs.org",
            url="https://nodejs.org/en/about/previous-releases",
            locations=["frontend/node-runtime.json"],
            note="打一体化安装包时带进去的 Node（跟到最新 LTS）",
        )
        if ctx.fetch:
            component.latest = sources.node_latest()
        component.resolve_status()
        items.append(component)
    version = platform.python_version()
    cycle = ".".join(version.split(".")[:2])
    python = Component(
        id="runtime:python", name="Python", category="runtime", kind="python",
        strategy=MANUAL, current=version, source="python.org",
        url="https://www.python.org/downloads/", locations=["core/.venv"],
        note="换 Python 版本要重建虚拟环境，这里只提示",
    )
    if ctx.fetch:
        same, newest = sources.python_latest(cycle)
        python.latest = same
        if newest and newest != cycle:
            python.note = f"Python {newest} 已发布；{python.note}"
    python.resolve_status()
    items.append(python)
    return items


# ---------------------------------------------------------------------------
# 借鉴代码
# ---------------------------------------------------------------------------


def upstream_file(ctx: Context, repo: str, ref: str, path: str) -> str | None:
    """上游某提交下的文件内容；不存在返回 None。"""
    return sources.github_file(repo, ref, path)


def scan_borrowed(ctx: Context) -> list[Component]:
    records = provenance.scan(ctx.repo)
    heads: dict[str, str] = {}
    full_shas: dict[tuple[str, str], str] = {}

    def head_of(repo: str) -> str:
        if repo not in heads:
            heads[repo] = sources.github_head(repo)
        return heads[repo]

    def resolve(repo: str, sha: str) -> str:
        key = (repo, sha)
        if key not in full_shas:
            full_shas[key] = sources.github_resolve(repo, sha)
        return full_shas[key]

    def one(record: provenance.Provenance) -> Component:
        component = Component(
            id=f"borrowed:{record.file}", name=record.file, category="borrowed",
            kind="borrowed", strategy=REVIEW, current=record.sha[:10], source=record.repo,
            url=f"https://github.com/{record.repo}" if record.repo else "",
            locations=[f"{record.file}:{record.line}"],
            detail={"repo": record.repo, "sha": record.sha, "path": record.path,
                    "header": record.text},
        )
        if not record.repo:
            component.status, component.strategy = UNKNOWN, MANUAL
            component.note = "来源标注里没写仓库（owner/repo），无法跟踪"
            return component
        if not ctx.fetch:
            return component
        try:
            head = head_of(record.repo)
            component.latest = head[:10]
            component.detail["latest_sha"] = head
            if not record.path:
                component.status, component.strategy = UNKNOWN, MANUAL
                component.note = "来源标注里没写上游文件路径，只能看仓库动态"
                return component
            base_sha = resolve(record.repo, record.sha)
            component.detail["base_sha"] = base_sha
            if base_sha == head:
                component.status = LATEST
                return component
            old = upstream_file(ctx, record.repo, base_sha, record.path)
            new = upstream_file(ctx, record.repo, head, record.path)
        except LookupFailed as exc:
            component.status, component.note = ERROR, str(exc)
            return component
        if old is None:
            component.status, component.strategy = UNKNOWN, MANUAL
            component.note = f"上游在 {record.sha[:10]} 找不到 {record.path}"
        elif new is None:
            component.status, component.strategy = OUTDATED, MANUAL
            component.note = "上游已删除或移动这个文件，需要人工看"
        elif old == new:
            component.status = LATEST
            component.note = "上游这个文件没变"
        else:
            component.status = OUTDATED
            component.note = "上游这个文件有改动"
        return component

    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, records))


# ---------------------------------------------------------------------------
# 技能（运行中的 Atlas 才有技能市场实例）
# ---------------------------------------------------------------------------


def skills_from_updates(rows: list[dict[str, Any]]) -> list[Component]:
    items = []
    for row in rows:
        status = {"update_available": OUTDATED, "up_to_date": LATEST}.get(
            row.get("status"), UNKNOWN)
        items.append(Component(
            id=f"skill:{row['name']}", name=row["name"], category="skills", kind="skill",
            strategy=HOT, status=status, current=str(row.get("version", "")),
            latest=str(row.get("latest_version") or row.get("version", "")),
            source=str(row.get("source") or ""), note=str(row.get("message") or ""),
            detail={"identifier": row.get("identifier")},
        ))
    return items


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

Scanner = Callable[[Context], list[Component]]


def scan_all(ctx: Context) -> list[Component]:
    """跑全部扫描器（相互独立的并行）。单个扫描器失败变成一条 error 组件。"""
    def guarded(name: str, fn: Scanner) -> list[Component]:
        try:
            return fn(ctx)
        except Exception as exc:  # 每个扫描器的失败都要落到清单上
            log.warning("upstream.scan_failed", scanner=name, exc_info=True)
            ctx.errors.append(f"{name}: {exc}")
            return [Component(id=f"scan:{name}", name=f"{name} 扫描失败", category="backend",
                              kind="scan", status=ERROR, strategy=MANUAL, note=str(exc)[:500])]

    scanners: dict[str, Scanner] = {
        "pip": scan_pip, "git": scan_git_pins, "npm": scan_npm, "runtime": scan_runtime,
    }
    with ThreadPoolExecutor(max_workers=len(scanners) + 1) as pool:
        futures = {name: pool.submit(guarded, name, fn) for name, fn in scanners.items()}
        futures["borrowed"] = pool.submit(guarded, "borrowed", scan_borrowed)
        results = {name: future.result() for name, future in futures.items()}
    npm_items = {item.id: item for item in results["npm"]}
    mcp = guarded("mcp", lambda c: scan_mcp(c, npm_items))
    ordered = ["pip", "git", "npm", "runtime", "borrowed"]
    items = [item for name in ordered for item in results[name]] + mcp
    return items
