"""Persistent, user-authored skill and memory scenario bundles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

_NAME = re.compile(r"^[\w][\w .-]{0,79}$", re.UNICODE)


class ScenarioBundleStore:
    """Store bundle manifests and the currently loaded bundle on this machine."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_ROOT / "data" / "scenario-bundles.json"

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": 1, "bundles": [], "loaded": None}
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取场景包文件：{exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("bundles"), list):
            raise ValueError("场景包文件格式无效")
        data.setdefault("schema_version", 1)
        data.setdefault("loaded", None)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def validate(manifest: Any) -> dict[str, Any]:
        if not isinstance(manifest, dict):
            raise ValueError("场景包必须是对象")
        name = manifest.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name.strip()):
            raise ValueError("名称不能为空，且不能超过 80 个字符")
        result: dict[str, Any] = {"name": name.strip()}
        description = manifest.get("description", "")
        if not isinstance(description, str):
            raise ValueError("description 必须是文本")
        result["description"] = description.strip()
        for key in ("skills", "memory_collections", "tools"):
            values = manifest.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{key} 必须是非空字符串数组")
            if len({value.casefold() for value in values}) != len(values):
                raise ValueError(f"{key} 包含重复项")
            result[key] = [value.strip() for value in values]
        return result

    def list(self) -> dict[str, Any]:
        data = self._read()
        return {"bundles": data["bundles"], "loaded": data.get("loaded")}

    def save(self, manifest: Any) -> dict[str, Any]:
        item = self.validate(manifest)
        data = self._read()
        existing = next((i for i, value in enumerate(data["bundles"])
                         if value.get("name", "").casefold() == item["name"].casefold()), None)
        if existing is None:
            data["bundles"].append(item)
        else:
            data["bundles"][existing] = item
        data["bundles"].sort(key=lambda value: value["name"].casefold())
        self._write(data)
        return item

    def delete(self, name: str) -> dict[str, Any]:
        data = self._read()
        found = next((item for item in data["bundles"] if item.get("name", "").casefold() == name.casefold()), None)
        if found is None:
            raise KeyError(name)
        data["bundles"] = [item for item in data["bundles"] if item is not found]
        unloaded = data.get("loaded", {}).get("name", "").casefold() == name.casefold()
        if unloaded:
            data["loaded"] = None
        self._write(data)
        return {"deleted": name, "unloaded": unloaded}

    def load(self, name: str, installed_skills: set[str], known_memory_collections: set[str] | None = None) -> dict[str, Any]:
        data = self._read()
        bundle = next((item for item in data["bundles"] if item.get("name", "").casefold() == name.casefold()), None)
        if bundle is None:
            raise KeyError(name)
        result = self.preview(name, installed_skills, known_memory_collections)
        if result["conflicts"]:
            return {**result, "loaded": False}
        data["loaded"] = {"name": bundle["name"], "memory_collections": bundle["memory_collections"],
                          "tools": bundle["tools"]}
        self._write(data)
        return {**result, "loaded": True}

    def preview(self, name: str, installed_skills: set[str], known_memory_collections: set[str] | None = None) -> dict[str, Any]:
        data = self._read()
        bundle = next((item for item in data["bundles"] if item.get("name", "").casefold() == name.casefold()), None)
        if bundle is None:
            raise KeyError(name)
        skill_index = {value.casefold(): value for value in installed_skills}
        missing_skills = [value for value in bundle["skills"] if value.casefold() not in skill_index]
        known = {value.casefold() for value in (known_memory_collections or set())}
        missing_memory = [value for value in bundle["memory_collections"] if known and value.casefold() not in known]
        conflicts = [{"type": "missing_skill", "name": value} for value in missing_skills]
        conflicts += [{"type": "unknown_memory_collection", "name": value} for value in missing_memory]
        result = {"bundle": bundle, "conflicts": conflicts,
                  "active_skills": [skill_index[value.casefold()] for value in bundle["skills"] if value.casefold() in skill_index],
                  "memory_collections": bundle["memory_collections"], "tools": bundle["tools"]}
        return {**result, "loaded": False}

    def unload(self) -> dict[str, Any]:
        data = self._read()
        prior = data.get("loaded")
        data["loaded"] = None
        self._write(data)
        return {"unloaded": prior is not None, "previous": prior}
