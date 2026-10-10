"""查最新版本用到的外部来源：子进程（git / pip / npm）与几个公开接口。

全部短超时、失败抛 :class:`LookupFailed`（中文消息），由调用方转成该项的「查不到」状态，
单项失败不影响其它项。网络走环境里的代理设置（httpx ``trust_env``）。
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

HTTP_TIMEOUT = 12.0
GIT = ["git", "-c", "core.longpaths=true"]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LookupFailed(RuntimeError):  # noqa: N818 —— 语义名
    """查询失败（离线、超时、来源不存在）。"""


def run(
    args: list[str], cwd: Path | str | None = None, timeout: float = 120,
    env: dict[str, str] | None = None, check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """跑一个子进程并收集输出；``check`` 时非零退出码抛 :class:`LookupFailed`。

    输出写临时文件而不是管道：测试会拉起 uvicorn 之类的孙子进程，它们继承管道句柄后，
    管道版 ``subprocess.run`` 会一直等到它们退出（超时也救不回来）。超时时结束整棵进程树。
    """
    import tempfile

    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.Popen(
                args, cwd=cwd, stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=env,
                creationflags=_NO_WINDOW,
                shell=os.name == "nt" and args[0].lower().endswith((".cmd", ".bat")),
            )
        except FileNotFoundError as exc:
            raise LookupFailed(f"找不到命令：{args[0]}") from exc
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            kill_tree(process.pid)
            process.wait(timeout=30)
            raise LookupFailed(f"命令超时（{int(timeout)} 秒）：{' '.join(args[:3])}") from exc
        out.seek(0)
        err.seek(0)
        result = subprocess.CompletedProcess(
            args, code, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace"))
    if check and result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-12:]
        raise LookupFailed(f"{' '.join(args[:4])} 失败：\n" + "\n".join(tail))
    return result


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(os.getpgid(pid), 9)
        except OSError:
            pass


def kill_under(root: Path) -> int:
    """结束可执行文件位于 ``root`` 下的所有进程（预演环境里漏下的测试服务器等）。"""
    if os.name != "nt":
        return 0
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and "
              f"$_.ExecutablePath.StartsWith('{str(root)}', 'OrdinalIgnoreCase') }} | "
              "ForEach-Object { $_.ProcessId }")
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                            text=True, creationflags=_NO_WINDOW, check=False, timeout=120)
    pids = [int(line) for line in result.stdout.split() if line.isdigit() and int(line) != os.getpid()]
    for pid in pids:
        kill_tree(pid)
    return len(pids)


def git(*args: str, cwd: Path | str | None = None, timeout: float = 120, check: bool = True) -> str:
    return run([*GIT, *args], cwd=cwd, timeout=timeout, check=check).stdout.strip()


def npm_cmd() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _client() -> httpx.Client:
    headers = {"User-Agent": "atlas-upstream"}
    return httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True, headers=headers)


def get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    try:
        with _client() as client:
            response = client.get(url, headers=headers or {})
    except httpx.HTTPError as exc:
        raise LookupFailed(f"连不上 {httpx.URL(url).host}：{type(exc).__name__}") from exc
    if response.status_code != 200:
        raise LookupFailed(f"{httpx.URL(url).host} 返回 {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise LookupFailed(f"{httpx.URL(url).host} 返回的不是 JSON") from exc


def get_text(url: str) -> str | None:
    """取文本；404 返回 None（来源文件被删或改名），其它失败抛 :class:`LookupFailed`。"""
    try:
        with _client() as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise LookupFailed(f"连不上 {httpx.URL(url).host}：{type(exc).__name__}") from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise LookupFailed(f"{httpx.URL(url).host} 返回 {response.status_code}")
    return response.text


# ---------------------------------------------------------------------------
# 包管理器
# ---------------------------------------------------------------------------


def npm_latest(name: str) -> str:
    """npm 上 ``latest`` 标签的版本。"""
    quoted = name.replace("/", "%2F")
    data = get_json(f"https://registry.npmjs.org/{quoted}/latest")
    version = str(data.get("version") or "")
    if not version:
        raise LookupFailed(f"npm 上查不到 {name}")
    return version


def pip_outdated(python: str) -> dict[str, str]:
    """``pip list --outdated``：规范名 → 最新版本（只含已装、非 editable 的包）。"""
    result = run(
        [python, "-m", "pip", "list", "--outdated", "--exclude-editable", "--format=json",
         "--disable-pip-version-check"], timeout=240, check=True,
    )
    from atlas.upstream.classify import normalize_pip

    rows = json.loads(result.stdout or "[]")
    return {normalize_pip(row["name"]): str(row["latest_version"]) for row in rows}


def pip_installed(python: str) -> dict[str, str]:
    """已装的包：规范名 → 版本（含 editable）。"""
    result = run([python, "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
                 timeout=120, check=True)
    from atlas.upstream.classify import normalize_pip

    return {normalize_pip(row["name"]): str(row["version"])
            for row in json.loads(result.stdout or "[]")}


def npm_outdated(root: Path) -> dict[str, dict[str, Any]]:
    """仓库根目录（含 workspaces）的 ``npm outdated --all``：包名 → 条目列表。

    npm 有过期项时退出码为 1，属正常；输出为空或非 JSON 才算失败。
    """
    result = run([npm_cmd(), "outdated", "--all", "--json", "--workspaces",
                  "--include-workspace-root"], cwd=root, timeout=240)
    text = result.stdout.strip()
    if not text:
        if result.returncode in (0, 1):
            return {}
        raise LookupFailed("npm outdated 失败：" + result.stderr.strip()[-400:])
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LookupFailed("npm outdated 输出无法解析") from exc
    if isinstance(data, dict) and "error" in data and len(data) == 1:
        raise LookupFailed("npm outdated 失败：" + str(data["error"].get("summary", ""))[:400])
    return data


# ---------------------------------------------------------------------------
# git / GitHub
# ---------------------------------------------------------------------------


def ls_remote(url: str, ref: str = "HEAD") -> str:
    """远端某个 ref 当前指向的提交。"""
    out = git("ls-remote", url, ref, timeout=60, check=False)
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if name in {ref, f"refs/heads/{ref}", f"refs/tags/{ref}"} or ref == "HEAD":
            return sha.strip()
    raise LookupFailed(f"远端 {url} 没有 {ref}")


@lru_cache(maxsize=1)
def _github_token() -> str:
    """环境变量里的令牌，没有就借本机 gh 的登录（匿名每小时只有 60 次，很快 403）。"""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        try:
            token = run(["gh", "auth", "token"], timeout=15).stdout.strip()
        except LookupFailed:
            token = ""
    return token


def _github_headers() -> dict[str, str]:
    token = _github_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def github_default_branch(repo: str) -> str:
    data = get_json(f"https://api.github.com/repos/{repo}", headers=_github_headers())
    return str(data.get("default_branch") or "main")


def github_head(repo: str, ref: str | None = None) -> str:
    """GitHub 仓库默认分支（或 ``ref``）的最新提交（git ls-remote，不占 API 配额）。"""
    url = f"https://github.com/{repo}.git"
    return ls_remote(url, ref or "HEAD")


def github_resolve(repo: str, short: str) -> str:
    """短提交号 → 完整提交号（GitHub API）。"""
    if len(short) == 40:
        return short
    try:
        data = get_json(f"https://api.github.com/repos/{repo}/commits/{short}",
                        headers=_github_headers())
        return str(data["sha"])
    except LookupFailed:
        # 接口限流时退回：raw.githubusercontent.com 也认短提交号。
        return short


def github_file(repo: str, ref: str, path: str) -> str | None:
    return get_text(f"https://raw.githubusercontent.com/{repo}/{ref}/{path}")


# ---------------------------------------------------------------------------
# 运行时
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def node_releases() -> list[dict[str, Any]]:
    return list(get_json("https://nodejs.org/dist/index.json"))


def node_latest(major: int | None = None) -> str:
    """Node 最新 LTS（给 ``major`` 时为该大版本的最新）。返回不带 v 的版本号。"""
    for release in node_releases():
        version = str(release.get("version", "")).lstrip("v")
        if major is not None:
            if version.split(".")[0] == str(major):
                return version
        elif release.get("lts"):
            return version
    raise LookupFailed("nodejs.org 上查不到 Node 版本")


def node_sha256(version: str, archive: str) -> str:
    text = get_text(f"https://nodejs.org/dist/v{version}/SHASUMS256.txt") or ""
    for line in text.splitlines():
        digest, _, name = line.partition("  ")
        if name.strip() == archive:
            return digest.strip()
    raise LookupFailed(f"Node {version} 没有 {archive} 的校验值")


def python_latest(cycle: str) -> tuple[str, str]:
    """(该小版本的最新补丁版, 最新的小版本)。"""
    rows = get_json("https://endoflife.date/api/python.json")
    same = next((str(row["latest"]) for row in rows if str(row.get("cycle")) == cycle), "")
    newest = str(rows[0]["cycle"]) if rows else ""
    if not same:
        raise LookupFailed(f"查不到 Python {cycle} 的最新版本")
    return same, newest
