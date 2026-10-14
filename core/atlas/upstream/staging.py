"""预演副本里的追新执行器（独立进程运行：``python -m atlas.upstream run --plan …``）。

正在用的 Atlas 不受影响：所有改动发生在仓库旁的 ``atlas-upstream-staging/`` 里——

- ``atlas/``  Atlas 仓库的 git 工作树（从当前提交分出）
- ``hermes/`` Hermes 源码的 git 工作树（从当前锁定的提交分出）
- ``venv/``   正在用的虚拟环境的镜像副本，装包、跑测试都在这里

步骤：准备副本 → 跑一遍测试当基线 → 按组更新（内核 → 记忆 → Python → 前端 → 运行时 →
借鉴代码），每组跑测试，只要出现基线以外的新失败就整组回退、再逐项重试找出坏的那项 →
每个通过的组提交一次 → 推送（或留给更新器在本机合并）→ 提示重启。

进度写在 ``<data>/upstream/run.json``，界面每几秒读一次。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from atlas.upstream import check, forks, inventory, provenance, sources
from atlas.upstream.classify import normalize_pip
from atlas.upstream.sources import LookupFailed

logger = structlog.get_logger()

IS_WIN = os.name == "nt"
STAGING_DIRNAME = "atlas-upstream-staging"
LOCK_FILE = Path("core") / "requirements.lock"
PENDING = "pending-merge.json"
PY_TEST_TIMEOUT = 1800
NPM_TIMEOUT = 1200

#: 组的执行顺序：(组名, 中文名, 组件 kind 集合)
GROUPS: list[tuple[str, str, set[str]]] = [
    ("hermes", "Agent 内核（Hermes）", {"fork"}),
    ("pip", "Python 依赖", {"pip", "git-pin"}),
    ("pip-transitive", "Python 间接依赖", {"pip-transitive"}),
    ("npm", "前端依赖", {"npm", "mcp-npx"}),
    ("npm-transitive", "前端间接依赖", {"npm-transitive"}),
    ("runtime", "运行时", {"node-bundled"}),
    ("borrowed", "借鉴代码", {"borrowed"}),
]


class ItemFailed(RuntimeError):  # noqa: N818
    """单项无法应用（冲突、装不上、上游删了文件……）。消息给用户看。"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def staging_root(repo: Path, data_root: Path | None = None) -> Path:
    # Profiles have separate job locks, so their mutable workspaces must also
    # be separate. Keep the historical path only for legacy callers.
    if data_root is not None:
        return data_root / "staging"
    return repo.parent / STAGING_DIRNAME


def venv_python(venv: Path) -> str:
    return str(venv / ("Scripts/python.exe" if IS_WIN else "bin/python"))


# ---------------------------------------------------------------------------
# 进度记录
# ---------------------------------------------------------------------------


class RunLog:
    def __init__(self, root: Path, plan: list[str]) -> None:
        self.path = root / "run.json"
        self.history = root / "history.jsonl"
        self.data: dict[str, Any] = {
            "id": datetime.now(UTC).strftime("%Y%m%d-%H%M%S"),
            "state": "running", "pid": os.getpid(), "started_at": _now(), "finished_at": None,
            "plan": plan, "phase": "准备", "steps": [], "results": {}, "commits": [],
            "pushed": False, "restart_required": False, "warnings": [],
        }
        self.save()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def step(self, text: str, phase: str | None = None) -> None:
        if phase:
            self.data["phase"] = phase
        self.data["steps"].append({"at": _now(), "text": text})
        self.data["steps"] = self.data["steps"][-200:]
        self.save()

    def result(self, component_id: str, status: str, **fields: Any) -> None:
        self.data["results"][component_id] = {"status": status, "at": _now(), **fields}
        self.save()

    def warn(self, text: str) -> None:
        self.data["warnings"].append(text)
        self.step(f"注意：{text}")

    def finish(self, state: str) -> None:
        self.data.update(state=state, finished_at=_now())
        self.save()
        with self.history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.data, ensure_ascii=False) + "\n")


def read_run(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((root / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("state") == "running" and not pid_alive(int(data.get("pid") or 0)):
        data["state"] = "interrupted"
    return data


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WIN:
        result = sources.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], timeout=20)
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cancel(root: Path) -> bool:
    run = read_run(root)
    pid = int(run.get("pid") or 0)
    if run.get("state") != "running" or not pid_alive(pid):
        return False
    if IS_WIN:
        sources.run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=30)
    else:
        os.kill(pid, signal.SIGTERM)
    run.update(state="cancelled", finished_at=_now())
    (root / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# 副本准备
# ---------------------------------------------------------------------------


def mirror(src: Path, dst: Path) -> None:
    """把 src 镜像到 dst（增量；dst 里多出来的删掉）。"""
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    drop_links(dst)
    if IS_WIN:
        result = sources.run(["robocopy", str(src), str(dst), "/MIR", "/MT:16", "/R:1", "/W:1",
                              "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XJ"], timeout=1800)
        if result.returncode >= 8:  # robocopy：0–7 都是成功
            raise ItemFailed(f"复制 {src} 失败（robocopy {result.returncode}）")
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)


def drop_links(directory: Path) -> None:
    """删掉 directory（及其 @scope 子目录）里的目录链接本身，不碰链接目标。

    robocopy /MIR 清理目标里「多出来」的目录时会顺着链接进去删：node_modules 里
    指回仓库的 npm 工作区链接（@atlas/frontend → frontend）曾因此把副本里的
    frontend/ 源码整个删掉。镜像完成后由 relink_junctions 重建。
    """
    if not directory.is_dir() or directory.is_junction() or directory.is_symlink():
        return
    scopes = [p for p in directory.iterdir() if p.name.startswith("@") and p.is_dir()
              and not (p.is_junction() or p.is_symlink())]
    for entry in [*directory.iterdir(), *(q for scope in scopes for q in scope.iterdir())]:
        if entry.is_junction() or entry.is_symlink():
            try:
                entry.unlink()  # 只移除链接本身
            except OSError:
                os.rmdir(entry)


def mirror_node_modules(src_repo: Path, dst_repo: Path, rel: str) -> None:
    """复制 node_modules，并把里面指回仓库的目录链接（npm 工作区包）在副本里重建。

    robocopy 用 /XJ 跳过链接（否则会把链接目标整份复制进来），所以链接要自己补。
    """
    mirror(src_repo / rel, dst_repo / rel)
    relink_junctions(src_repo, dst_repo, rel)


def relink_junctions(src_repo: Path, dst_repo: Path, rel: str) -> None:
    """按 src_repo 里 ``rel`` 下的目录链接，在 dst_repo 对应位置补上同样的链接。"""
    src, dst = src_repo / rel, dst_repo / rel
    if not src.exists():
        return
    candidates = [p for p in src.iterdir() if p.name.startswith("@") and p.is_dir()]
    entries = [p for p in src.iterdir()] + [q for scope in candidates for q in scope.iterdir()]
    for entry in entries:
        if not (entry.is_junction() or entry.is_symlink()):
            continue
        try:
            target = Path(os.readlink(entry))
        except OSError:
            continue
        if not target.is_absolute():
            target = (entry.parent / target).resolve()
        target = Path(str(target).removeprefix("\\\\?\\"))
        try:
            relative = target.resolve().relative_to(src_repo.resolve())
        except ValueError:
            continue
        link = dst / entry.relative_to(src)
        if link.exists() or link.is_junction() or link.is_symlink():
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        new_target = dst_repo / relative
        if IS_WIN:
            sources.run(["cmd", "/c", "mklink", "/J", str(link), str(new_target)], timeout=30)
        else:
            link.symlink_to(new_target, target_is_directory=True)


@dataclass
class Workspace:
    repo: Path                 # 正在用的 Atlas 仓库
    hermes_main: Path          # 正在用的 Hermes 源码目录
    root: Path                 # 预演根目录
    data: Path                 # <data>/upstream
    base: str = ""             # 预演起点（Atlas 当前提交）
    branch: str = ""           # Atlas 当前分支
    pin: str = ""              # Hermes 锁定提交
    baseline: dict[str, Any] = field(default_factory=dict)

    @property
    def atlas(self) -> Path:
        return self.root / "atlas"

    @property
    def hermes(self) -> Path:
        return self.root / "hermes"

    @property
    def venv(self) -> Path:
        return self.root / "venv"

    @property
    def python(self) -> str:
        return venv_python(self.venv)

    def git(self, *args: str, cwd: Path | None = None, timeout: float = 300,
            check: bool = True) -> str:
        return sources.git(*args, cwd=cwd or self.atlas, timeout=timeout, check=check)


def _worktree(main: Path, path: Path, commit: str) -> None:
    """在 path 放一个 main 仓库的工作树，停在 commit（已存在就复位）。"""
    if (path / ".git").exists():
        sources.git("checkout", "--force", "--detach", commit, cwd=path, timeout=600)
        sources.git("reset", "--hard", commit, cwd=path, timeout=600)
        sources.git("clean", "-fd", cwd=path, timeout=600)
        return
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    sources.git("worktree", "prune", cwd=main, check=False)
    sources.git("worktree", "add", "--force", "--detach", str(path), commit, cwd=main, timeout=900)


def prepare(ws: Workspace, log: RunLog) -> None:
    ws.base = sources.git("rev-parse", "HEAD", cwd=ws.repo)
    ws.branch = sources.git("rev-parse", "--abbrev-ref", "HEAD", cwd=ws.repo)
    ws.pin = inventory.hermes_settings(ws.repo / "core" / "pyproject.toml")["commit"]
    ws.root.mkdir(parents=True, exist_ok=True)
    log.step(f"准备预演副本 {ws.root}（Atlas {ws.base[:8]}，Hermes {ws.pin[:8]}）", "准备")
    _worktree(ws.repo, ws.atlas, ws.base)
    if (ws.hermes_main / ".git").exists():
        _worktree(ws.hermes_main, ws.hermes, ws.pin)
    log.step("复制 Python 环境与 node_modules（增量）")
    mirror(ws.repo / "core" / ".venv", ws.venv)
    venv_link = ws.atlas / "core" / ".venv"
    if not venv_link.exists() and ws.venv.exists():
        # 有的脚本和测试按仓库内的 core/.venv 找解释器：指到副本的环境。
        if IS_WIN:
            sources.run(["cmd", "/c", "mklink", "/J", str(venv_link), str(ws.venv)], timeout=30)
        else:
            venv_link.symlink_to(ws.venv, target_is_directory=True)
    for rel in ("node_modules", "frontend/node_modules"):
        mirror_node_modules(ws.repo, ws.atlas, rel)
    editables = ["-e", str(ws.atlas / "core")]
    if ws.hermes.exists():
        editables += ["-e", str(ws.hermes)]
    sources.run([ws.python, "-m", "pip", "install", "-q", "--no-deps", *editables],
                timeout=900, check=True)


# ---------------------------------------------------------------------------
# 验证（与基线比：不能出现基线以外的新失败）
# ---------------------------------------------------------------------------

_PYTEST_FAIL = re.compile(r"^(FAILED|ERROR) (\S+)", re.MULTILINE)
_VITEST_FAIL = re.compile(r"^\s*(?:FAIL|×|✗)\s+(.+?)(?:\s+\d+ms)?$", re.MULTILINE)


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("PYTHONPATH", "ATLAS_DATA_DIR", "ATLAS_ROOT", "ATLAS_API_TOKEN", "VIRTUAL_ENV"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    env["FORCE_COLOR"] = "0"
    return env


def python_gate(ws: Workspace) -> dict[str, Any]:
    """后端能导入、依赖没冲突、单元测试。"""
    env = _clean_env()
    imp = sources.run([ws.python, "-c", "import atlas.server, run_agent"], cwd=ws.atlas / "core",
                      timeout=600, env=env)
    pip_check = sources.run([ws.python, "-m", "pip", "check"], timeout=300, env=env)
    tests = sources.run(
        [ws.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "auto",
         "--timeout", "300", "-o", "console_output_style=classic"],
        cwd=ws.atlas / "core", timeout=PY_TEST_TIMEOUT, env=env,
    )
    output = tests.stdout + tests.stderr
    summary = next((line for line in reversed(output.splitlines()) if " in " in line
                    and ("passed" in line or "failed" in line)), "")
    return {
        "import_ok": imp.returncode == 0,
        "import_error": (imp.stderr or imp.stdout)[-1500:] if imp.returncode else "",
        "pip_conflicts": sorted(line for line in pip_check.stdout.splitlines()
                                if line.strip() and "No broken" not in line),
        "failures": sorted({m.group(2) for m in _PYTEST_FAIL.finditer(output)}),
        "summary": summary,
        "ran": bool(summary),
    }


def frontend_gate(ws: Workspace) -> dict[str, Any]:
    env = _clean_env()
    build = sources.run([sources.npm_cmd(), "--prefix", "frontend", "run", "build"],
                        cwd=ws.atlas, timeout=NPM_TIMEOUT, env=env)
    tests = sources.run([sources.npm_cmd(), "--prefix", "frontend", "test", "--", "--reporter=dot"],
                        cwd=ws.atlas, timeout=NPM_TIMEOUT, env=env)
    output = tests.stdout + tests.stderr
    return {
        "build_ok": build.returncode == 0,
        "build_error": (build.stdout + build.stderr)[-2500:] if build.returncode else "",
        "failures": sorted({m.group(1).strip() for m in _VITEST_FAIL.finditer(output)}),
        "tests_ok": tests.returncode == 0,
        "ran": "Test Files" in output or "Tests" in output,
    }


GATES: dict[str, Callable[[Workspace], dict[str, Any]]] = {
    "python": python_gate, "frontend": frontend_gate,
}


def regressions(kind: str, base: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """本次验证相对基线的新问题（空列表 = 通过）。"""
    problems: list[str] = []
    if kind == "python":
        if base.get("import_ok", True) and not now.get("import_ok"):
            problems.append("后端导入失败：" + now.get("import_error", "")[-600:])
        new_conflicts = sorted(
            set(now.get("pip_conflicts", [])) - set(base.get("pip_conflicts", [])))
        if new_conflicts:
            problems.append("依赖冲突：" + "；".join(new_conflicts[:8]))
        if base.get("ran") and not now.get("ran"):
            problems.append("测试没能跑完")
    else:
        if base.get("build_ok", True) and not now.get("build_ok"):
            problems.append("前端构建失败：" + now.get("build_error", "")[-1200:])
        if base.get("ran") and not now.get("ran") and now.get("build_ok"):
            problems.append("前端测试没能跑完")
    new_failures = sorted(set(now.get("failures", [])) - set(base.get("failures", [])))
    if new_failures:
        problems.append(f"新增 {len(new_failures)} 个测试失败：" + "；".join(new_failures[:10]))
    return problems


def baseline(ws: Workspace, kinds: set[str], log: RunLog) -> None:
    cache_path = ws.data / "baseline.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    key = f"{ws.base}:{ws.pin}"
    if cache.get("key") != key:
        cache = {"key": key}
    for kind in sorted(kinds):
        if kind not in cache:
            label = "后端" if kind == "python" else "前端"
            log.step(f"跑基线测试（{label}），用来对比更新后的结果", "基线")
            cache[kind] = GATES[kind](ws)
            sources.kill_under(ws.root)
        ws.baseline[kind] = cache[kind]
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 各类组件怎么改
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n" if "\r\n" not in text else "")


def set_pip_pin(pyproject: Path, name: str, version: str) -> bool:
    """把 pyproject 里 ``name==旧版本`` 改成新版本；不是 == 的写法不动。返回是否改了。"""
    text = _read(pyproject)
    pattern = re.compile(
        r'("' + r"[-_.]?".join(re.escape(part) for part in re.split(r"[-_.]+", name))
        + r'(?:\[[^\]]*\])?==)([^";,\s]+)', re.IGNORECASE)
    new, count = pattern.subn(lambda m: m.group(1) + version, text)
    if count:
        _write(pyproject, new)
    return bool(count)


def set_git_pin(pyproject: Path, old_sha: str, new_sha: str) -> None:
    text = _read(pyproject)
    if old_sha not in text:
        raise ItemFailed(f"pyproject 里找不到提交号 {old_sha[:10]}")
    _write(pyproject, text.replace(old_sha, new_sha))


def set_hermes_pin(pyproject: Path, new_sha: str) -> None:
    text = _read(pyproject)
    new, count = re.subn(r'(\[tool\.atlas\.hermes\][^\[]*?commit\s*=\s*")[0-9a-f]{40}(")',
                         lambda m: m.group(1) + new_sha + m.group(2), text, flags=re.DOTALL)
    if not count:
        raise ItemFailed("pyproject 里找不到 [tool.atlas.hermes] commit")
    _write(pyproject, new)


def write_lock(ws: Workspace) -> None:
    """``core/requirements.lock``：预演环境里所有第三方包的确切版本（不含 editable）。

    另一台电脑的更新器看到它变了就 ``pip install -r``，两边环境保持一致。
    """
    out = sources.run([ws.python, "-m", "pip", "freeze", "--exclude-editable",
                       "--disable-pip-version-check"], timeout=300, check=True).stdout
    lines = sorted(
        (line for line in out.splitlines()
         if line.strip() and not line.startswith(("-e ", "#")) and " @ file:" not in line),
        key=str.lower,
    )
    header = ("# 由 Atlas 追新（atlas.upstream）生成：后端环境里所有第三方包的确切版本。\n"
              "# 更新器在它变化时执行 pip install -r core/requirements.lock。不要手改。\n")
    _write(ws.atlas / LOCK_FILE, header + "\n".join(lines) + "\n")


def pip_install(ws: Workspace, specs: list[str]) -> None:
    result = sources.run([ws.python, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                          *specs], timeout=1800, env=_clean_env())
    if result.returncode != 0:
        raise ItemFailed("pip 安装失败：" + (result.stderr or result.stdout)[-1500:])


def restore_python(ws: Workspace) -> None:
    """回到上一次提交时的 Python 环境。"""
    lock = ws.atlas / LOCK_FILE
    if lock.exists():
        sources.run([ws.python, "-m", "pip", "install", "-q", "-r", str(lock)], timeout=1800)
    else:
        mirror(ws.repo / "core" / ".venv", ws.venv)
    editables = ["-e", str(ws.atlas / "core")]
    if ws.hermes.exists():
        editables += ["-e", str(ws.hermes)]
    sources.run([ws.python, "-m", "pip", "install", "-q", "--no-deps", *editables], timeout=900)


def _major(version: str) -> str:
    """语义化版本的「大版本」：1.x → 1；0.x 版本里次版本号就算大版本（0.13 与 0.14 不兼容）。"""
    parts = re.findall(r"\d+", version or "")
    if not parts:
        return version
    return parts[0] if parts[0] != "0" else f"0.{parts[1] if len(parts) > 1 else '0'}"


def same_major(item: dict[str, Any]) -> bool:
    if item.get("kind") not in {"pip", "npm", "mcp-npx"}:
        return False
    return _major(str(item.get("current", ""))) == _major(str(item.get("latest", "")))


def npm_spec(old_spec: str, version: str) -> str:
    match = re.match(r"^([\^~]|>=)?", old_spec)
    prefix = match.group(1) if match and match.group(1) in {"^", "~"} else ""
    return f"{prefix}{version}"


def set_npm_version(ws: Workspace, item: dict[str, Any]) -> None:
    name, latest = item["name"], item["latest"]
    for rel in item.get("locations", []):
        manifest = ws.atlas / rel
        if not manifest.exists() or not rel.endswith("package.json"):
            continue
        data = json.loads(_read(manifest))
        for section in ("dependencies", "devDependencies"):
            if name in (data.get(section) or {}):
                data[section][name] = npm_spec(str(data[section][name]), latest)
        _write(manifest, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    # npm 只认工作区根 package.json 的 allowScripts；版本号对不上时 electron 等包的安装脚本被拦，
    # 2026-10-10 就因此装出一个没有 dist/electron.exe 的 Electron，Atlas 起不来。
    for rel in {*item.get("locations", []), "package.json"}:
        manifest = ws.atlas / rel
        if not manifest.exists() or not rel.endswith("package.json"):
            continue
        data = json.loads(_read(manifest))
        scripts = data.get("allowScripts")
        keys = [k for k in scripts if k.startswith(f"{name}@")] if isinstance(scripts, dict) else []
        if keys:
            for key in keys:
                scripts[f"{name}@{latest}"] = scripts.pop(key)
            _write(manifest, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    for ref in item.get("detail", {}).get("mcp_refs", []) + (
            [{"file": "atlas.example.toml", "version": item.get("current")}]
            if item.get("kind") == "mcp-npx" else []):
        example = ws.atlas / "config" / "atlas.example.toml"
        if ref.get("file") == "atlas.example.toml" and example.exists() and ref.get("version"):
            _write(example, _read(example).replace(f"{name}@{ref['version']}", f"{name}@{latest}"))


def npm_install(ws: Workspace, args: list[str] | None = None) -> None:
    result = sources.run([sources.npm_cmd(), *(args or ["install"]), "--no-audit", "--no-fund"],
                         cwd=ws.atlas, timeout=NPM_TIMEOUT, env=_clean_env())
    if result.returncode != 0:
        raise ItemFailed("npm 失败：" + (result.stderr or result.stdout)[-1500:])


def restore_npm(ws: Workspace) -> None:
    sources.run([sources.npm_cmd(), "ci", "--no-audit", "--no-fund"], cwd=ws.atlas,
                timeout=NPM_TIMEOUT, env=_clean_env())


def _push_urls(directory: Path, remote: str = "origin") -> list[str]:
    url = sources.git("remote", "get-url", remote, cwd=directory, check=False)
    urls = [url] if url else []
    match = re.match(r"https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
    if match:
        urls.append(f"git@github.com:{match.group(1)}.git")
    return urls


def push(directory: Path, refspec: str) -> str:
    """推送；HTTPS 不行（Windows 网络登录没有凭据）就换 SSH。返回成功的地址或空串。"""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    for url in _push_urls(directory):
        result = sources.run([*sources.GIT, "push", url, refspec], cwd=directory, timeout=600,
                             env=env)
        if result.returncode == 0:
            return url
    return ""


def _identity(directory: Path) -> list[str]:
    """仓库没配提交身份时补一个，免得 merge/commit 失败。"""
    if sources.git("config", "user.email", cwd=directory, check=False):
        return []
    return ["-c", "user.name=Atlas 追新", "-c", "user.email=atlas-upstream@localhost"]


def apply_hermes(ws: Workspace, item: dict[str, Any], log: RunLog) -> str:
    settings = inventory.hermes_settings(ws.atlas / "core" / "pyproject.toml")
    target = f"upstream/{settings['upstream_ref']}"
    if not ws.hermes.exists():
        raise ItemFailed("找不到 Hermes 源码目录")
    sources.git("fetch", "--quiet", "upstream", settings["upstream_ref"], cwd=ws.hermes,
                timeout=600)
    behind = sources.git("rev-list", "--count", f"{ws.pin}..{target}", cwd=ws.hermes)
    log.step(f"合并 Hermes 上游 {behind} 个提交")
    describe = sources.git("describe", "--tags", "--always", target, cwd=ws.hermes, check=False)
    merge = sources.run([*sources.GIT, *_identity(ws.hermes), "merge", "--no-edit", "-m",
                         f"merge: upstream {settings['upstream_ref']} ({describe}) into atlas",
                         target], cwd=ws.hermes, timeout=900)
    if merge.returncode != 0:
        conflicts = sources.git("diff", "--name-only", "--diff-filter=U", cwd=ws.hermes,
                                check=False).splitlines()
        sources.git("merge", "--abort", cwd=ws.hermes, check=False)
        raise ItemFailed("合并有冲突，需要人工（或交给 Agent）处理：" + "、".join(conflicts[:20]))
    new_sha = sources.git("rev-parse", "HEAD", cwd=ws.hermes)
    log.step("装上合并后的 Hermes（含它新增的依赖）")
    pip_install(ws, ["-e", str(ws.hermes)])
    tests = [path for path in ("tests/agent/test_atlas_hooks.py",
                               "tests/agent/test_atlas_context_handoff.py")
             if (ws.hermes / path).exists()]
    if tests:
        result = sources.run([ws.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
                             cwd=ws.hermes, timeout=900, env=_clean_env())
        if result.returncode != 0:
            raise ItemFailed("Atlas 在 Hermes 里的补丁测试失败：" + result.stdout[-1500:])
    set_hermes_pin(ws.atlas / "core" / "pyproject.toml", new_sha)
    item["_push"] = (ws.hermes, f"{new_sha}:refs/heads/{settings['branch']}")
    return f"{ws.pin[:10]} → {new_sha[:10]}（{describe}）"


def apply_borrowed(ws: Workspace, item: dict[str, Any], ctx: inventory.Context) -> str:
    detail = item.get("detail") or {}
    repo, path = detail.get("repo"), detail.get("path")
    base_sha, head = detail.get("base_sha"), detail.get("latest_sha")
    if not (repo and path and base_sha and head):
        raise ItemFailed("来源信息不全（仓库/路径/提交号），无法自动合并")
    target = ws.atlas / item["name"]
    base = inventory.upstream_file(ctx, repo, base_sha, path)
    theirs = inventory.upstream_file(ctx, repo, head, path)
    if base is None or theirs is None:
        raise ItemFailed("上游文件找不到了（被删除或改名）")
    ours = target.read_text(encoding="utf-8")
    merged, clean = forks.merge_text(ours, base, theirs)
    if not clean:
        review = ws.data / "reviews"
        review.mkdir(exist_ok=True)
        diff_path = review / (re.sub(r"[^\w.-]+", "_", item["name"]) + ".diff")
        diff_path.write_text(forks.unified_diff(base, theirs, path), encoding="utf-8")
        raise ItemFailed(f"Atlas 改过的地方和上游改动重叠，需要人工合并。上游改动：{diff_path}")
    record = provenance.Provenance(file=item["name"], repo=repo, sha=detail.get("sha", ""),
                                   path=path, line=int(item["locations"][0].rsplit(":", 1)[1]),
                                   text="")
    target.write_text(provenance.replace_sha(merged, record, head), encoding="utf-8", newline="")
    return f"合并上游 {base_sha[:10]} → {head[:10]}"


def apply_node_bundled(ws: Workspace, item: dict[str, Any]) -> str:
    path = ws.atlas / "frontend" / "node-runtime.json"
    data = json.loads(_read(path))
    old, version = data["version"], item["latest"]
    archive = f"node-v{version}-win-x64.zip"
    data.update(version=version, archive=archive,
                source=f"https://nodejs.org/dist/v{version}/{archive}",
                sha256=sources.node_sha256(version, archive))
    _write(path, json.dumps(data, indent=2) + "\n")
    return f"{old} → {version}"


# ---------------------------------------------------------------------------
# 分组执行
# ---------------------------------------------------------------------------


@dataclass
class Group:
    key: str
    label: str
    items: list[dict[str, Any]]

    @property
    def gates(self) -> set[str]:
        if self.key in {"npm", "npm-transitive"}:
            return {"frontend"}
        if self.key == "runtime":
            return set()
        return {"python"}


class Runner:
    def __init__(self, ws: Workspace, log: RunLog, components: list[dict[str, Any]],
                 push_enabled: bool) -> None:
        self.ws = ws
        self.log = log
        self.components = {item["id"]: item for item in components}
        self.push_enabled = push_enabled
        self.ctx = inventory.Context(repo=ws.repo, python=sys.executable,
                                     hermes_dir=ws.hermes_main, fetch=False)
        self.pending_pushes: list[tuple[Path, str]] = []

    # -- 单组 ---------------------------------------------------------------

    def apply_items(self, group: Group, items: list[dict[str, Any]]) -> dict[str, str]:
        """应用一批同组的项，返回 id → 说明。任一项失败抛 ItemFailed（带 id）。"""
        notes: dict[str, str] = {}
        ws = self.ws
        if group.key == "hermes":
            for item in items:
                notes[item["id"]] = apply_hermes(ws, item, self.log)
        elif group.key == "pip":
            specs = []
            pyproject = ws.atlas / "core" / "pyproject.toml"
            for item in items:
                if item["kind"] == "git-pin":
                    detail = item["detail"]
                    set_git_pin(pyproject, detail["sha"], detail["latest_sha"])
                    specs.append(f"{item['name']} @ git+https://github.com/{detail['repo']}"
                                 f"@{detail['latest_sha']}")
                else:
                    set_pip_pin(pyproject, item["name"], item["latest"])
                    specs.append(f"{item['name']}=={item['latest']}")
                notes[item["id"]] = f"{item['current']} → {item['latest']}"
            pip_install(ws, specs)
            # 刷新 atlas-core 的已安装元数据，否则 pip check 还拿旧 pin 报「依赖冲突」。
            pip_install(ws, ["--no-deps", "-e", str(ws.atlas / "core")])
            write_lock(ws)
        elif group.key == "pip-transitive":
            packages = [row["name"] for row in items[0]["detail"].get("packages", [])]
            ok, skipped = self._pip_upgrade_each(packages)
            write_lock(ws)
            kept = f"，{len(skipped)} 个因版本冲突保持原样：{'、'.join(skipped[:12])}"
            notes[items[0]["id"]] = f"更新 {len(ok)} 个" + (kept if skipped else "")
        elif group.key == "npm":
            for item in items:
                set_npm_version(ws, item)
                notes[item["id"]] = f"{item['current']} → {item['latest']}"
            npm_install(ws)
        elif group.key == "npm-transitive":
            npm_install(ws, ["update", "--workspaces", "--include-workspace-root"])
            notes[items[0]["id"]] = "按版本范围更新了 package-lock.json"
        elif group.key == "runtime":
            for item in items:
                notes[item["id"]] = apply_node_bundled(ws, item)
        elif group.key == "borrowed":
            # 合并冲突的文件当场记失败、不写入；只拿能干净合并的去跑测试。
            for item in items:
                try:
                    notes[item["id"]] = apply_borrowed(ws, item, self.ctx)
                except (ItemFailed, LookupFailed) as exc:
                    self._fail([item], str(exc))
        return notes

    def _pip_upgrade_each(self, packages: list[str]) -> tuple[list[str], list[str]]:
        """间接依赖逐个升级：升完 pip check 出新冲突的退回原版本。"""
        ok, skipped = [], []
        base_conflicts = set(self.ws.baseline.get("python", {}).get("pip_conflicts", []))
        for name in packages:
            before = sources.pip_installed(self.ws.python).get(normalize_pip(name), "")
            try:
                pip_install(self.ws, ["--upgrade", name])
            except ItemFailed:
                skipped.append(name)
                continue
            check_out = sources.run([self.ws.python, "-m", "pip", "check"], timeout=300).stdout
            conflicts = {line for line in check_out.splitlines()
                         if line.strip() and "No broken" not in line}
            if conflicts - base_conflicts and before:
                pip_install(self.ws, [f"{name}=={before}"])
                skipped.append(name)
            else:
                ok.append(name)
        return ok, skipped

    def rollback(self, group: Group) -> None:
        ws = self.ws
        ws.git("reset", "--hard", "HEAD")
        ws.git("clean", "-fd")
        if group.key in {"hermes", "pip", "pip-transitive"}:
            if group.key == "hermes" and ws.hermes.exists():
                head_pin = inventory.hermes_settings(ws.atlas / "core" / "pyproject.toml")["commit"]
                sources.git("reset", "--hard", head_pin, cwd=ws.hermes, check=False)
            restore_python(ws)
        if group.key in {"npm", "npm-transitive"}:
            self.restore_node()

    def verify(self, group: Group) -> list[str]:
        problems = []
        for kind in sorted(group.gates):
            self.log.step(f"验证：{'后端测试' if kind == 'python' else '前端构建与测试'}")
            problems += regressions(kind, self.ws.baseline.get(kind, {}), GATES[kind](self.ws))
            # 测试会拉起后端服务器等子进程，失败或超时时可能漏下来：每轮验证后清干净。
            sources.kill_under(self.ws.root)
        return problems

    def commit(self, group: Group, notes: dict[str, str]) -> None:
        ws = self.ws
        ws.git("add", "-A")
        if not ws.git("status", "--porcelain"):
            return
        lines = [f"- {self.components[cid]['name']}: {note}" for cid, note in notes.items()]
        message = (f"chore(upstream): {group.label}追到最新\n\n" + "\n".join(lines)
                   + "\n\n由 Atlas 追新（atlas.upstream）在预演副本里应用并验证。\n")
        ws.git(*_identity(ws.atlas), "commit", "-q", "-m", message)
        self.log.data["commits"].append({"group": group.label, "sha": ws.git("rev-parse", "HEAD")})
        self.log.save()

    def try_batch(self, group: Group, items: list[dict[str, Any]]) -> tuple[bool, str]:
        """应用并验证一批；不通过就回退。返回 (是否通过, 原因)。"""
        try:
            notes = self.apply_items(group, items)
        except (ItemFailed, LookupFailed) as exc:
            self.rollback(group)
            return False, str(exc)
        if not notes:
            self.rollback(group)
            return True, ""  # 这批都已当场记为失败，没有要验证的
        problems = self.verify(group)
        if problems:
            self.rollback(group)
            return False, "\n".join(problems)
        for item in items:
            if "_push" in item:
                self.pending_pushes.append(item.pop("_push"))
        self.commit(group, notes)
        for cid, note in notes.items():
            self.log.result(cid, "applied", note=note, version=self.components[cid].get("latest"))
            check.clear_failure(cid, self.ws.data)
        return True, ""

    def run_group(self, group: Group) -> None:
        self.log.step(f"更新 {group.label}（{len(group.items)} 项）", group.label)
        if group.key in {"npm", "npm-transitive"}:
            self.snapshot_node()
        ok, reason = self.try_batch(group, group.items)
        if ok:
            return
        # 当场已记失败的（比如合并冲突）不再重试
        failed_now = {cid for cid, res in self.log.data["results"].items()
                      if res.get("status") == "failed"}
        remaining = [item for item in group.items if item["id"] not in failed_now]
        if len(remaining) <= 1 or group.key in {"pip-transitive", "npm-transitive"}:
            self._fail(remaining, reason)
            return
        # 先把不跨大版本的一起再试一次（通常都能过），跨大版本的逐个试。
        safe = [item for item in remaining if same_major(item)]
        risky = [item for item in remaining if not same_major(item)]
        self.log.step(f"{group.label} 整组没通过：先试 {len(safe)} 个小版本更新，"
                      f"再逐个试 {len(risky)} 个大版本更新")
        if len(safe) > 1 and len(risky) > 0:
            ok, reason = self.try_batch(group, safe)
            if not ok:
                risky = safe + risky
        else:
            risky = safe + risky
        for item in risky:
            ok, reason = self.try_batch(group, [item])
            if not ok:
                self._fail([item], reason)

    # -- node_modules 快照：前端组回退时整份换回，比重新 npm ci 快得多 ----------------

    NODE_DIRS = ("node_modules", "frontend/node_modules")

    def snapshot_node(self) -> None:
        for rel in self.NODE_DIRS:
            mirror(self.ws.atlas / rel, self.ws.root / "node-snapshot" / rel)

    def restore_node(self) -> None:
        snap = self.ws.root / "node-snapshot"
        if not snap.exists():
            restore_npm(self.ws)
            return
        for rel in self.NODE_DIRS:
            mirror(snap / rel, self.ws.atlas / rel)
            relink_junctions(self.ws.repo, self.ws.atlas, rel)

    def _fail(self, items: list[dict[str, Any]], reason: str) -> None:
        for item in items:
            text = reason
            prefix = f"{item['id']}::"
            if prefix in text:
                text = text.split(prefix, 1)[1]
            self.log.result(item["id"], "failed", reason=text[-3000:], version=item.get("latest"))
            check.record_failure(item["id"], str(item.get("latest", "")), text, self.ws.data)

    # -- 收尾 ---------------------------------------------------------------

    def publish(self) -> None:
        ws, log = self.ws, self.log
        head = ws.git("rev-parse", "HEAD")
        if head == ws.base:
            return
        ws.git("branch", "-f", "upstream/latest", head)
        log.data["restart_required"] = True
        if self.push_enabled:
            for directory, refspec in self.pending_pushes:
                log.step("推送 Hermes fork")
                if not push(directory, refspec):
                    log.warn("Hermes fork 没推送成功：另一台电脑拉不到新内核，本机不受影响")
            log.step(f"推送 Atlas 到远端分支 {ws.branch}")
            if push(ws.atlas, f"{head}:refs/heads/{ws.branch}"):
                log.data["pushed"] = True
        pending = {"commit": head, "base": ws.base, "branch": ws.branch,
                   "pushed": log.data["pushed"], "at": _now(),
                   "summary": [c["group"] for c in log.data["commits"]]}
        (ws.data / PENDING).write_text(json.dumps(pending, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        log.save()


def group_plan(components: list[dict[str, Any]], plan: list[str]) -> list[Group]:
    chosen = [item for item in components if item["id"] in plan]
    groups = []
    for key, label, kinds in GROUPS:
        items = [item for item in chosen if item.get("kind") in kinds]
        if items:
            groups.append(Group(key, label, items))
    return groups


JOB_LOCK_MAX_AGE_SECONDS = 6 * 3600  # 追新任务至多几十分钟；比这还旧的锁视为遗留


def _lock_is_live(lock: Path) -> bool:
    """锁存在、年龄正常、且其 PID 仍活着时，才算确有任务在跑。

    只看 PID 会把"进程已死、但 PID 被系统复用"的陈旧锁误判成正在运行，
    从而永久挡住后续追新。
    """
    try:
        age = time.time() - lock.stat().st_mtime
        pid = int(lock.read_text(encoding="utf-8") or 0)
    except (OSError, ValueError):
        return False
    return bool(pid) and age < JOB_LOCK_MAX_AGE_SECONDS and pid_alive(pid)


def run(plan: list[str], data_root: Path | None = None, repo: Path | None = None) -> dict[str, Any]:
    """执行一次追新（阻塞，几分钟到几十分钟）。"""
    from atlas.config import PROJECT_ROOT

    data_root = data_root or check.upstream_root()
    repo = repo or PROJECT_ROOT
    status = check.load_status(data_root)
    components = check.decorate(status.get("components") or [], data_root)
    lock = data_root / "job.lock"
    if _lock_is_live(lock):
        # 不碰正在跑的那个任务的 run.json，只告诉调用方这次没执行。
        return {"state": "skipped", "reason": "已有一个追新任务在跑", "results": {},
                "commits": [], "pushed": False}
    log = RunLog(data_root, plan)
    owned = False
    try:
        lock.write_text(str(os.getpid()))
        owned = True
        groups = group_plan(components, plan)
        skipped = [cid for cid in plan
                   if not any(cid == item["id"] for group in groups for item in group.items)]
        for cid in skipped:
            log.result(cid, "skipped", reason="这一项不在预演里处理（即时更新或需手动）")
        if not groups:
            log.step("没有需要在预演里更新的项")
            log.finish("nothing")
            return log.data
        ws = Workspace(repo=repo, hermes_main=inventory.hermes_checkout(repo),
                       root=staging_root(repo, data_root), data=data_root)
        prepare(ws, log)
        baseline(ws, set().union(*(group.gates for group in groups)), log)
        runner = Runner(ws, log, components, bool(check.load_settings(data_root).get("push")))
        for group in groups:
            runner.run_group(group)
        runner.publish()
        results = log.data["results"].values()
        applied = sum(r["status"] == "applied" for r in results)
        failed = sum(r["status"] == "failed" for r in results)
        log.step(f"完成：更新 {applied} 项，失败 {failed} 项", "完成")
        log.finish("succeeded" if not failed else ("partial" if applied else "failed"))
    except Exception as exc:  # 任务进程顶层：一切异常都要落到 run.json
        logger.exception("upstream.run_failed")
        log.step("出错：" + str(exc))
        log.data["error"] = traceback.format_exc()[-4000:]
        log.finish("failed")
    finally:
        try:
            sources.kill_under(staging_root(repo, data_root))
        except Exception:  # 清理失败不影响结果
            logger.warning("upstream.cleanup_failed", exc_info=True)
        if owned:
            try:
                lock.unlink()
            except OSError:
                pass
        _notify(log.data)
    return log.data


def _notify(data: dict[str, Any]) -> None:
    """Windows 通知（复用 Atlas 的通知通道）；失败不影响结果。"""
    results = list((data.get("results") or {}).values())
    applied = sum(r["status"] == "applied" for r in results)
    failed = sum(r["status"] == "failed" for r in results)
    if data.get("state") in {"nothing", "skipped"}:
        return
    title = "Atlas 追新完成" if data.get("state") != "failed" else "Atlas 追新没成功"
    body = f"更新 {applied} 项" + (f"，{failed} 项没通过验证" if failed else "")
    if data.get("restart_required"):
        body += "。重启 Atlas 后生效。"
    try:
        import asyncio

        from atlas.notifications.apprise import AppriseNotifier

        asyncio.run(AppriseNotifier().notify(title, body))
    except Exception:  # 通知是附带的
        logger.warning("upstream.notify_failed", exc_info=True)


def wait_for_exit(pid: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.5)
