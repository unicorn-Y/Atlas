"""ACP 官方注册表（agentclientprotocol.com/registry）：挑选、安装、升级挂件。

注册表每条记录的 distribution 有三种：npx / uvx（包名里带版本，天然钉死）和 binary
（按平台下载压缩包，校验 sha256 后解到挂件的 bin/）。
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from atlas.workbench.store import AgentManifest, WorkbenchStore, workbench_root

REGISTRY_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
_CACHE_TTL = 3600.0


def _cache_path() -> Path:
    return workbench_root() / "registry-cache.json"


def platform_key() -> str:
    system = {"Windows": "windows", "Darwin": "darwin", "Linux": "linux"}.get(platform.system(), "linux")
    machine = platform.machine().lower()
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    return f"{system}-{arch}"


async def fetch_registry(force: bool = False) -> dict[str, Any]:
    cache = _cache_path()
    if not force and cache.is_file() and time.time() - cache.stat().st_mtime < _CACHE_TTL:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(REGISTRY_URL)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        if cache.is_file():
            return json.loads(cache.read_text(encoding="utf-8"))
        raise
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def describe(entry: dict[str, Any]) -> dict[str, Any]:
    """注册表条目 → 界面卡片：能不能在本机装、怎么装。"""
    dist = entry.get("distribution") or {}
    method = "npx" if "npx" in dist else "uvx" if "uvx" in dist else None
    if method is None and platform_key() in (dist.get("binary") or {}):
        method = "binary"
    return {
        "id": entry.get("id", ""), "name": entry.get("name", ""), "version": entry.get("version", ""),
        "description": entry.get("description", ""), "icon": entry.get("icon", ""),
        "repository": entry.get("repository") or entry.get("website") or "",
        "license": entry.get("license", ""), "install": method,
    }


def manifest_from_entry(entry: dict[str, Any], agent_id: str) -> AgentManifest:
    dist = entry.get("distribution") or {}
    common = dict(
        id=agent_id, name=entry.get("name") or agent_id, mode="acp",
        description=entry.get("description", ""), version=entry.get("version", ""),
        source=f"registry:{entry.get('id')}", icon=entry.get("icon", ""),
        repository=entry.get("repository") or entry.get("website") or "",
    )
    if "npx" in dist:
        spec = dist["npx"]
        return AgentManifest(command="npx", args=["--yes", spec["package"], *spec.get("args", [])],
                             env=dict(spec.get("env") or {}), **common)
    if "uvx" in dist:
        spec = dist["uvx"]
        return AgentManifest(command="uvx", args=[spec["package"], *spec.get("args", [])],
                             env=dict(spec.get("env") or {}), **common)
    target = (dist.get("binary") or {}).get(platform_key())
    if not target:
        raise ValueError(f"{common['name']} 没有本机（{platform_key()}）可用的安装包")
    cmd = str(target.get("cmd", "")).lstrip("./").lstrip(".\\")
    return AgentManifest(command=f"bin/{cmd}", args=list(target.get("args", [])),
                         env=dict(target.get("env") or {}), **common)


async def _download_binary(entry: dict[str, Any], folder: Path) -> None:
    target = (entry.get("distribution") or {}).get("binary", {}).get(platform_key())
    if not target:
        return
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        response = await client.get(target["archive"])
        response.raise_for_status()
        payload = response.content
    expected = str(target.get("sha256") or "").lower()
    if expected and hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("下载的安装包校验不一致（sha256），已放弃安装")
    bin_dir = folder / "bin"
    staging = folder / "bin.new"
    if staging.exists():
        import shutil

        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    url = target["archive"].lower()
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            _safe_extract_zip(archive, staging)
    elif url.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")):
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            archive.extractall(staging, filter="data")
    else:
        name = url.rsplit("/", 1)[-1] or "agent"
        (staging / name).write_bytes(payload)
    if bin_dir.exists():
        import shutil

        shutil.rmtree(bin_dir)
    staging.replace(bin_dir)


def _safe_extract_zip(archive: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for member in archive.infolist():
        path = (dest / member.filename).resolve()
        if root not in path.parents and path != root:
            raise ValueError("安装包里有越界路径，已放弃安装")
    archive.extractall(dest)


async def install(store: WorkbenchStore, registry_id: str, agent_id: str | None = None) -> AgentManifest:
    """从注册表装一个新挂件（同一个 agent 可以装多份，各自独立）。"""
    data = await fetch_registry()
    entry = next((item for item in data.get("agents", []) if item.get("id") == registry_id), None)
    if entry is None:
        raise KeyError(registry_id)
    new_id = agent_id or store.unique_id(registry_id)
    manifest = manifest_from_entry(entry, new_id)
    store.save(manifest, create=True)
    if manifest.command.startswith("bin/"):
        try:
            await _download_binary(entry, store.agent_dir(new_id))
        except Exception:
            store.delete(new_id)
            raise
    return manifest


async def upgrade(store: WorkbenchStore, agent_id: str) -> AgentManifest:
    """把注册表来的挂件升到注册表当前版本；保留名字、环境变量、权限等用户设置。"""
    current = store.get(agent_id)
    if not current.source.startswith("registry:"):
        raise ValueError("这个挂件不是从注册表装的，没法自动升级")
    data = await fetch_registry(force=True)
    registry_id = current.source.split(":", 1)[1]
    entry = next((item for item in data.get("agents", []) if item.get("id") == registry_id), None)
    if entry is None:
        raise KeyError(registry_id)
    fresh = manifest_from_entry(entry, agent_id)
    if fresh.command.startswith("bin/"):
        await _download_binary(entry, store.agent_dir(agent_id))
    current.command, current.args, current.version = fresh.command, fresh.args, fresh.version
    current.env = {**fresh.env, **current.env}
    return store.save(current)
