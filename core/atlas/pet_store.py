"""Local pet package installation and active-pet selection."""
from __future__ import annotations

import json
import io
import re
import shutil
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from atlas import config


_PET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_AVATAR_EXTENSIONS = {".png", ".gif", ".webp", ".jpg", ".jpeg"}
_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
_MAX_UNPACKED_BYTES = 100 * 1024 * 1024
_MAX_PACKAGE_FILES = 300


class PetPackageError(ValueError):
    """A user-provided pet package is incomplete or invalid."""


class PetStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or (config.DATA_ROOT / "data" / "pets")).resolve()
        self.packages = self.root / "packages"
        self.active_file = self.root / "active.json"
        self._lock = threading.RLock()

    @staticmethod
    def builtin() -> dict[str, Any]:
        return {"id": "atlas-companion", "name": "Atlas 小伙伴", "description": "随 Atlas 运行状态变换动作。",
                "emoji": "🐈", "color": "#8277f4", "avatar": None, "builtin": True, "version": "1"}

    def _active_id(self) -> str:
        try:
            row = json.loads(self.active_file.read_text(encoding="utf-8"))
            pet_id = row.get("pet_id") if isinstance(row, dict) else None
            return pet_id if isinstance(pet_id, str) and pet_id else "atlas-companion"
        except (OSError, json.JSONDecodeError):
            return "atlas-companion"

    def _read_package(self, directory: Path) -> dict[str, Any] | None:
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(manifest, dict) or not _PET_ID.fullmatch(str(manifest.get("id") or "")):
            return None
        pet_id = str(manifest["id"])
        if directory.name != pet_id:
            return None
        avatar = manifest.get("avatar")
        if avatar is not None:
            if not isinstance(avatar, str) or not self._is_safe_relative_file(avatar):
                avatar = None
            else:
                image = directory.joinpath(*PurePosixPath(avatar).parts)
                if image.suffix.lower() not in _AVATAR_EXTENSIONS or not image.is_file():
                    avatar = None
        return {
            "id": pet_id,
            "name": str(manifest.get("name") or pet_id)[:80],
            "description": str(manifest.get("description") or "")[:400],
            "emoji": str(manifest.get("emoji") or "🐾")[:8],
            "color": str(manifest.get("color") or "#8277f4") if _COLOR.fullmatch(str(manifest.get("color") or "")) else "#8277f4",
            "avatar": avatar,
            "builtin": False,
            "version": str(manifest.get("version") or "1")[:40],
        }

    @staticmethod
    def _is_safe_relative_file(value: str) -> bool:
        path = PurePosixPath(value.replace("\\", "/"))
        return (not path.is_absolute() and "\x00" not in value and ":" not in value and bool(path.parts)
                and all(part not in {"", ".", ".."} for part in path.parts))

    @staticmethod
    def _valid_avatar(data: bytes, suffix: str) -> bool:
        signatures = {
            ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            ".gif": data.startswith((b"GIF87a", b"GIF89a")),
            ".webp": len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
            ".jpg": data.startswith(b"\xff\xd8\xff"),
            ".jpeg": data.startswith(b"\xff\xd8\xff"),
        }
        return signatures.get(suffix.lower(), False)

    def list(self) -> dict[str, Any]:
        with self._lock:
            rows = [self.builtin()]
            if self.packages.is_dir():
                for directory in sorted(self.packages.iterdir(), key=lambda path: path.name.lower()):
                    if directory.is_dir():
                        package = self._read_package(directory)
                        if package:
                            rows.append(package)
            active_id = self._active_id()
            if active_id not in {row["id"] for row in rows}:
                active_id = "atlas-companion"
            return {"pets": rows, "active_id": active_id}

    def active(self) -> dict[str, Any]:
        listing = self.list()
        return next(row for row in listing["pets"] if row["id"] == listing["active_id"])

    def activate(self, pet_id: str) -> dict[str, Any]:
        with self._lock:
            listing = self.list()
            package = next((row for row in listing["pets"] if row["id"] == pet_id), None)
            if package is None:
                raise KeyError("找不到这只宠物")
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.active_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"pet_id": pet_id}, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.replace(self.active_file)
            return package

    def hatch(self, name: str, emoji: str, color: str) -> dict[str, Any]:
        clean_name = name.strip()[:80]
        if not clean_name:
            raise PetPackageError("请给新宠物起个名字")
        if not _COLOR.fullmatch(color):
            raise PetPackageError("颜色请使用六位十六进制颜色，例如 #8277f4")
        pet_id = f"pet-{uuid.uuid4().hex[:12]}"
        manifest = {"id": pet_id, "name": clean_name, "description": "在 Atlas 本地孵化的宠物。",
                    "emoji": (emoji.strip() or "🐾")[:8], "color": color.lower(), "version": "1", "avatar": None}
        with self._lock:
            directory = self.packages / pet_id
            directory.mkdir(parents=True, exist_ok=False)
            (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return self.activate(pet_id)

    def install_archive(self, raw: bytes) -> dict[str, Any]:
        if not raw or len(raw) > _MAX_ARCHIVE_BYTES:
            raise PetPackageError("宠物包必须是非空 ZIP，且压缩文件不超过 50 MiB")
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
        except (OSError, zipfile.BadZipFile) as exc:
            raise PetPackageError("宠物包不是有效 ZIP 文件") from exc
        with archive:
            members = archive.infolist()
            if len(members) > _MAX_PACKAGE_FILES:
                raise PetPackageError("宠物包文件数超过 300")
            total_size = sum(member.file_size for member in members)
            if total_size > _MAX_UNPACKED_BYTES:
                raise PetPackageError("宠物包解压后超过 100 MiB")
            files: dict[str, bytes] = {}
            for member in members:
                name = member.filename.replace("\\", "/")
                if member.is_dir():
                    continue
                if not self._is_safe_relative_file(name):
                    raise PetPackageError("宠物包包含无效文件路径")
                if name in files:
                    raise PetPackageError("宠物包包含重复文件路径")
                mode = member.external_attr >> 16
                if mode & 0o170000 == 0o120000:
                    raise PetPackageError("宠物包不能包含符号链接")
                files[name] = archive.read(member)
        raw_manifest = files.get("manifest.json")
        if raw_manifest is None:
            raise PetPackageError("宠物包根目录需要 manifest.json")
        try:
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PetPackageError("manifest.json 不是有效 UTF-8 JSON") from exc
        if not isinstance(manifest, dict):
            raise PetPackageError("manifest.json 顶层必须是对象")
        pet_id = str(manifest.get("id") or "")
        if not _PET_ID.fullmatch(pet_id) or pet_id == "atlas-companion":
            raise PetPackageError("宠物 id 需用 1–48 位小写字母、数字、下划线或连字符")
        name = str(manifest.get("name") or "").strip()
        if not name or len(name) > 80:
            raise PetPackageError("宠物名称不能为空且不能超过 80 字")
        avatar = manifest.get("avatar")
        if avatar is not None:
            if not isinstance(avatar, str) or not self._is_safe_relative_file(avatar):
                raise PetPackageError("头像路径必须是宠物包内的相对路径")
            avatar_suffix = PurePosixPath(avatar).suffix.lower()
            if avatar_suffix not in _AVATAR_EXTENSIONS or avatar not in files or not self._valid_avatar(files[avatar], avatar_suffix):
                raise PetPackageError("头像仅支持包内的 PNG、JPEG、WebP 或 GIF 文件")
        color = str(manifest.get("color") or "#8277f4")
        if not _COLOR.fullmatch(color):
            raise PetPackageError("manifest.json 的 color 必须是六位十六进制颜色")
        normalized = {"id": pet_id, "name": name, "description": str(manifest.get("description") or "")[:400],
                      "emoji": str(manifest.get("emoji") or "🐾")[:8], "color": color.lower(),
                      "version": str(manifest.get("version") or "1")[:40], "avatar": avatar}
        with self._lock:
            target = self.packages / pet_id
            if target.exists():
                raise PetPackageError("这只宠物已经安装")
            target.mkdir(parents=True, exist_ok=False)
            try:
                for name, data in files.items():
                    destination = target.joinpath(*PurePosixPath(name).parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                (target / "manifest.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
        return self._read_package(target) or normalized | {"builtin": False}

    def remove(self, pet_id: str) -> None:
        if pet_id == "atlas-companion":
            raise PetPackageError("内置宠物不能移除")
        with self._lock:
            target = self.packages / pet_id
            if not _PET_ID.fullmatch(pet_id) or not target.is_dir():
                raise KeyError("找不到这只宠物")
            if self._active_id() == pet_id:
                self.activate("atlas-companion")
            shutil.rmtree(target)

    def avatar_path(self, pet_id: str) -> Path | None:
        with self._lock:
            listing = self.list()
            package = next((row for row in listing["pets"] if row["id"] == pet_id), None)
            if not package or not package.get("avatar"):
                return None
            path = (self.packages / pet_id).joinpath(*PurePosixPath(package["avatar"]).parts).resolve()
            if self.packages not in path.parents or not path.is_file():
                return None
            return path


__all__ = ["PetPackageError", "PetStore"]
