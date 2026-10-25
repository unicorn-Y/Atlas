"""Local, versioned website artifacts and an opt-in filesystem static host adapter."""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from atlas.config import DATA_ROOT

router = APIRouter(prefix="/api/artifact-sites")
_lock = RLock()
_SITE_ID = re.compile(r"^[a-f0-9]{32}$")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_MAX_FILES = 5000
_MAX_BYTES = 100 * 1024 * 1024
_SKIP_DIRS = {".git", "node_modules", ".atlas-worktrees"}
_DEFAULT_SETTINGS: dict[str, Any] = {
    "adapter": "filesystem", "target_root": "", "public_base_url": "",
    "terms_title": "静态站点托管条款", "terms_text": "", "terms_url": "",
}


def _root() -> Path:
    return DATA_ROOT / "artifact-sites"


def _records_path() -> Path:
    return _root() / "sites.json"


def _settings_path() -> Path:
    return _root() / "hosting.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _records() -> dict[str, dict[str, Any]]:
    value = _read_json(_records_path(), {})
    return value if isinstance(value, dict) else {}


def _settings() -> dict[str, Any]:
    value = _read_json(_settings_path(), {})
    settings = {**_DEFAULT_SETTINGS, **(value if isinstance(value, dict) else {})}
    settings["terms_version"] = _terms_version(settings)
    return settings


def _terms_version(settings: dict[str, Any]) -> str:
    material = "\0".join(str(settings.get(key) or "") for key in (
        "adapter", "target_root", "public_base_url", "terms_title", "terms_text", "terms_url",
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _site(site_id: str) -> dict[str, Any]:
    if not _SITE_ID.fullmatch(site_id):
        raise HTTPException(status_code=404, detail="站点不存在")
    site = _records().get(site_id)
    if not isinstance(site, dict):
        raise HTTPException(status_code=404, detail="站点不存在")
    return site


def _local_source(workspace: Any, raw_source: Any) -> tuple[Path, Path]:
    if not isinstance(workspace, str) or not workspace.strip():
        raise HTTPException(status_code=422, detail="需要本地工作目录")
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=422, detail="工作目录不存在或不是本地目录")
    if not isinstance(raw_source, str) or not raw_source.strip():
        raise HTTPException(status_code=422, detail="需要网页产物路径")
    candidate = Path(raw_source).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents if parent.exists()):
        raise HTTPException(status_code=422, detail="网页产物路径中不能包含符号链接")
    source = candidate.resolve()
    allowed = source == root or root in source.parents
    artifacts_root = (DATA_ROOT / "artifacts").resolve()
    allowed = allowed or source == artifacts_root or artifacts_root in source.parents
    if not allowed or not source.exists() or source.is_symlink() or not (source.is_file() or source.is_dir()):
        raise HTTPException(status_code=422, detail="产物必须位于当前工作目录或 Atlas 本地产物目录，且不能是符号链接")
    if source.is_file() and source.suffix.lower() not in {".html", ".htm", ".svg"}:
        raise HTTPException(status_code=415, detail="网页站点只接受 HTML、HTM、SVG 文件或包含 index.html 的目录")
    return root, source


def _copy_site(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise HTTPException(status_code=409, detail="站点版本目录已存在")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    count = 0
    total = 0
    try:
        if source.is_dir():
            if source.is_symlink():
                raise HTTPException(status_code=422, detail="站点目录不能是符号链接")
            temp.mkdir()
            for current, dirs, files in os.walk(source, followlinks=False):
                current_path = Path(current)
                dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and not (current_path / name).is_symlink()]
                relative = current_path.relative_to(source)
                target_dir = temp / relative
                target_dir.mkdir(parents=True, exist_ok=True)
                for name in files:
                    file = current_path / name
                    if file.is_symlink() or not file.is_file():
                        continue
                    count += 1
                    total += file.stat().st_size
                    if count > _MAX_FILES or total > _MAX_BYTES:
                        raise HTTPException(status_code=413, detail="站点超过 5000 个文件或 100 MB 限制")
                    shutil.copyfile(file, target_dir / name)
            if not (temp / "index.html").is_file():
                candidates = sorted(temp.glob("*.htm"))
                candidates += sorted(temp.glob("*.html"))
                if candidates:
                    shutil.copyfile(candidates[0], temp / "index.html")
                elif (temp / "index.svg").is_file():
                    (temp / "index.html").write_text('<!doctype html><meta charset="utf-8"><img src="index.svg" alt="">', encoding="utf-8")
                else:
                    raise HTTPException(status_code=422, detail="站点目录需要 index.html、HTML 页面或 index.svg")
        else:
            count, total = 1, source.stat().st_size
            if total > _MAX_BYTES:
                raise HTTPException(status_code=413, detail="网页产物超过 100 MB 限制")
            temp.mkdir()
            if source.suffix.lower() == ".svg":
                shutil.copyfile(source, temp / "index.svg")
                (temp / "index.html").write_text('<!doctype html><meta charset="utf-8"><img src="index.svg" alt="">', encoding="utf-8")
            else:
                shutil.copyfile(source, temp / "index.html")
        os.replace(temp, destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return {"files": count, "bytes": total}


def _page_navigation(pages: list[str], *, nested: bool = False) -> str:
    prefix = "../" if nested else ""
    home = "../" if nested else "./"
    links = "".join(f'<a href="{prefix}{html.escape(item)}/">{html.escape(item)}</a> ' for item in pages)
    return f'<!--atlas-pages-nav--><nav aria-label="子页面"><a href="{home}">首页</a> {links}</nav><!--/atlas-pages-nav-->'


def _inject_page_navigation(path: Path, pages: list[str]) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"<!--atlas-pages-nav-->.*?<!--/atlas-pages-nav-->", "", text, flags=re.DOTALL)
    nav = _page_navigation(pages)
    match = re.search(r"</body\s*>", text, flags=re.IGNORECASE)
    if match:
        text = text[:match.start()] + nav + text[match.start():]
    else:
        text += nav
    path.write_text(text, encoding="utf-8")


def _new_version(site_id: str, source: Path, *, workspace: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    with _lock:
        records = _records()
        site = records.get(site_id)
        if not isinstance(site, dict):
            raise HTTPException(status_code=404, detail="站点不存在")
        number = int(site.get("version") or 0) + 1
        version = f"v{number:04d}"
        destination = _root() / site_id / "versions" / version
        stats = _copy_site(source, destination)
        pages = sorted({str(item) for item in site.get("pages", []) if _SLUG.fullmatch(str(item))})
        previous = _root() / site_id / "versions" / f"v{int(site.get('version') or 0):04d}"
        for slug in pages:
            old_page = previous / slug
            new_page = destination / slug
            if old_page.is_dir() and not new_page.exists():
                shutil.copytree(old_page, new_page, symlinks=False)
                for file in new_page.rglob("*"):
                    if file.is_file():
                        stats["files"] += 1
                        stats["bytes"] += file.stat().st_size
        _inject_page_navigation(destination / "index.html", pages)
        site = {**site, "version": number, "updated_at": datetime.now(UTC).isoformat(),
                "pages": pages, "version_stats": stats, "published_version": site.get("published_version")}
        if workspace is not None:
            site["workspace"] = str(workspace)
        site["source_path"] = str(source)
        records[site_id] = site
        _write_json(_records_path(), records)
        return site, stats


@router.get("")
async def list_sites() -> dict[str, Any]:
    records = _records()
    sites = sorted(records.values(), key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return {"sites": sites, "hosting": _settings()}


@router.get("/hosting")
async def get_hosting_settings() -> dict[str, Any]:
    return _settings()


@router.put("/hosting")
async def put_hosting_settings(body: dict[str, Any]) -> dict[str, Any]:
    base = str(body.get("public_base_url") or "").strip().rstrip("/")
    target_raw = str(body.get("target_root") or "").strip()
    terms_text = str(body.get("terms_text") or "").strip()
    terms_url = str(body.get("terms_url") or "").strip()
    if base and not re.fullmatch(r"https?://[^\s]+", base, flags=re.IGNORECASE):
        raise HTTPException(status_code=422, detail="公开基础 URL 必须是 http:// 或 https:// 地址")
    if target_raw:
        target = Path(target_raw).expanduser()
        if not target.is_absolute():
            raise HTTPException(status_code=422, detail="静态站点目标目录必须是绝对路径")
        target_root = target.resolve()
        if target_root == _root().resolve() or _root().resolve() in target_root.parents or target_root in _root().resolve().parents:
            raise HTTPException(status_code=422, detail="托管目录不能覆盖 Atlas 站点数据目录")
    else:
        target_root = Path()
    if terms_url and not re.fullmatch(r"https?://[^\s]+", terms_url, flags=re.IGNORECASE):
        raise HTTPException(status_code=422, detail="条款链接必须是 http:// 或 https:// 地址")
    settings = {
        "adapter": "filesystem", "target_root": str(target_root) if target_raw else "",
        "public_base_url": base, "terms_title": str(body.get("terms_title") or "静态站点托管条款")[:120],
        "terms_text": terms_text[:12000], "terms_url": terms_url,
    }
    _write_json(_settings_path(), settings)
    return {**settings, "terms_version": _terms_version(settings)}


@router.post("", status_code=201)
async def create_site(body: dict[str, Any]) -> dict[str, Any]:
    workspace, source = _local_source(body.get("workspace"), body.get("source_path"))
    site_id = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    record = {"id": site_id, "title": str(body.get("title") or source.stem or "网页产物")[:160],
              "workspace": str(workspace), "source_path": str(source), "version": 0,
              "published_version": None, "created_at": now, "updated_at": now, "pages": []}
    with _lock:
        records = _records()
        records[site_id] = record
        _write_json(_records_path(), records)
        try:
            _new, stats = _new_version(site_id, source, workspace=workspace)
        except Exception:
            records = _records()
            records.pop(site_id, None)
            _write_json(_records_path(), records)
            shutil.rmtree(_root() / site_id, ignore_errors=True)
            raise
        records = _records()
        records[site_id] = {**record, **_new, "version_stats": stats}
        _write_json(_records_path(), records)
    return {"site": records[site_id], "local_url": f"/api/artifact-sites/{site_id}/"}


@router.post("/{site_id}/versions")
async def update_site_version(site_id: str, body: dict[str, Any]) -> dict[str, Any]:
    current = _site(site_id)
    workspace, source = _local_source(body.get("workspace") or current.get("workspace"), body.get("source_path") or current.get("source_path"))
    site, stats = _new_version(site_id, source, workspace=workspace)
    return {"site": site, "local_url": f"/api/artifact-sites/{site_id}/", "stats": stats}


@router.post("/{site_id}/pages", status_code=201)
async def add_site_page(site_id: str, body: dict[str, Any]) -> dict[str, Any]:
    site = _site(site_id)
    slug = str(body.get("slug") or "").strip().lower()
    title = str(body.get("title") or "").strip()[:160]
    content = str(body.get("content") or "")
    if not _SLUG.fullmatch(slug) or slug in {"api", "assets", "versions"}:
        raise HTTPException(status_code=422, detail="子页面路径只接受小写字母、数字和短横线")
    if not title or len(content) > 200_000:
        raise HTTPException(status_code=422, detail="需要标题，页面内容不能超过 200 KB")
    with _lock:
        source = _root() / site_id / "versions" / f"v{int(site['version']):04d}"
        number = int(site.get("version") or 0) + 1
        version = f"v{number:04d}"
        destination = _root() / site_id / "versions" / version
        temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        shutil.copytree(source, temp, symlinks=False)
        page_dir = temp / slug
        if page_dir.exists():
            shutil.rmtree(temp, ignore_errors=True)
            raise HTTPException(status_code=409, detail="此子页面路径已经存在")
        page_dir.mkdir(parents=True)
        pages = sorted(set(site.get("pages", [])) | {slug})
        escaped_title = html.escape(title)
        escaped_content = html.escape(content).replace("\n", "<br>\n")
        page = (f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{escaped_title}</title><body>{_page_navigation(pages, nested=True)}<main><h1>{escaped_title}</h1><p>{escaped_content}</p></main></body></html>')
        (page_dir / "index.html").write_text(page, encoding="utf-8")
        _inject_page_navigation(temp / "index.html", pages)
        os.replace(temp, destination)
        records = _records()
        current = records[site_id]
        current = {**current, "version": number, "pages": pages, "updated_at": datetime.now(UTC).isoformat(), "published_version": site.get("published_version")}
        records[site_id] = current
        _write_json(_records_path(), records)
    return {"site": current, "local_url": f"/api/artifact-sites/{site_id}/{slug}/"}


@router.post("/{site_id}/publish")
async def publish_site(site_id: str, body: dict[str, Any]) -> dict[str, Any]:
    site = _site(site_id)
    settings = _settings()
    if settings["adapter"] != "filesystem" or not settings["target_root"] or not settings["public_base_url"]:
        raise HTTPException(status_code=409, detail="尚未配置静态站点托管目录和公开基础 URL；本地产物不会自动上传")
    if not settings["terms_text"].strip():
        raise HTTPException(status_code=409, detail="请先填写并保存托管目标的发布条款")
    if body.get("confirmed") is not True or body.get("terms_version") != settings["terms_version"]:
        raise HTTPException(status_code=428, detail="请查看当前条款并明确确认后再发布")
    version_dir = _root() / site_id / "versions" / f"v{int(site['version']):04d}"
    if not version_dir.is_dir():
        raise HTTPException(status_code=404, detail="当前站点版本的文件缺失")
    target_root = Path(str(settings["target_root"])).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / site_id
    if destination.exists() and site.get("published_version") is None:
        raise HTTPException(status_code=409, detail="托管目录中已经有同 ID 内容；Atlas 不会覆盖未登记的目录")
    stage = target_root / f".{site_id}.{uuid.uuid4().hex}.staging"
    backup = target_root / f".{site_id}.{uuid.uuid4().hex}.backup"
    shutil.copytree(version_dir, stage, symlinks=False)
    try:
        if destination.exists():
            os.replace(destination, backup)
        os.replace(stage, destination)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise HTTPException(status_code=500, detail=f"静态站点部署失败：{exc}") from exc
    with _lock:
        records = _records()
        current = records[site_id]
        current = {**current, "published_version": int(site["version"]), "published_at": datetime.now(UTC).isoformat(),
                   "share_url": f"{settings['public_base_url']}/{site_id}/", "updated_at": datetime.now(UTC).isoformat()}
        records[site_id] = current
        _write_json(_records_path(), records)
    return {"site": current, "share_url": current["share_url"], "published_version": current["published_version"],
            "files": sum(1 for path in destination.rglob("*") if path.is_file())}


def _static_file(site_id: str, asset_path: str) -> FileResponse:
    site = _site(site_id)
    version_dir = (_root() / site_id / "versions" / f"v{int(site['version']):04d}").resolve()
    requested = asset_path.strip("/") or "index.html"
    if "\\" in requested or any(part in {".", ".."} for part in requested.split("/")):
        raise HTTPException(status_code=404, detail="文件不存在")
    target = (version_dir / requested).resolve()
    if version_dir not in target.parents and target != version_dir:
        raise HTTPException(status_code=404, detail="文件不存在")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file() or target.is_symlink():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-popups; default-src 'self' data: blob: https:; script-src 'self' 'unsafe-inline' https:; style-src 'self' 'unsafe-inline' https:; connect-src 'none'; object-src 'none'; base-uri 'none'"}
    return FileResponse(target, media_type=media_type, headers=headers)


@router.get("/{site_id}")
@router.get("/{site_id}/")
async def open_site(site_id: str) -> FileResponse:
    return _static_file(site_id, "index.html")


@router.get("/{site_id}/{asset_path:path}")
async def open_site_asset(site_id: str, asset_path: str) -> FileResponse:
    return _static_file(site_id, asset_path)
