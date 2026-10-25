"""Offline-first dependency and local configuration security audit."""

from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_OSV_BATCH = "https://api.osv.dev/v1/querybatch"


def _version(value: Any) -> str:
    return str(value or "").strip().lstrip("=v")


def _dependencies(root: Path) -> list[dict[str, str]]:
    found: dict[tuple[str, str, str], dict[str, str]] = {}
    lock = root / "core" / "uv.lock"
    if lock.is_file():
        data = tomllib.loads(lock.read_text(encoding="utf-8"))
        for row in data.get("package", []):
            name, version = str(row.get("name") or ""), _version(row.get("version"))
            if name and version:
                found[("PyPI", name.lower(), version)] = {"ecosystem": "PyPI", "name": name, "version": version, "lockfile": "core/uv.lock"}
    for relative in ("frontend/package-lock.json", "package-lock.json"):
        path = root / relative
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        packages = data.get("packages")
        if isinstance(packages, dict):
            for location, row in packages.items():
                if not location or not isinstance(row, dict):
                    continue
                name = str(row.get("name") or location.rsplit("node_modules/", 1)[-1])
                version = _version(row.get("version"))
                if name and version:
                    found[("npm", name.lower(), version)] = {"ecosystem": "npm", "name": name, "version": version, "lockfile": relative}
    return list(found.values())


def _at(mapping: Any, dotted: str) -> Any:
    value = mapping
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _config_findings(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    paths = [root / "config" / "atlas.toml", root / "config" / "atlas.example.toml"]
    for path in paths:
        if not path.is_file():
            continue
        rel = str(path.relative_to(root))
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            findings.append({"id": "ATLAS-CONFIG-PARSE", "severity": "error", "file": rel,
                             "evidence": f"TOML 无法解析：{type(exc).__name__}", "recommendation": "修复配置语法后重跑审计。"})
            continue
        for key in ("models.gateway.api_key", "gateway.api_key"):
            if isinstance(_at(data, key), str) and _at(data, key).strip():
                findings.append({"id": "ATLAS-CONFIG-PLAINTEXT-SECRET", "severity": "high", "file": rel,
                                 "evidence": f"{key} 存在非空内联密钥（值已隐藏）",
                                 "recommendation": "清除配置文件中的密钥，将其存入本机凭据库或环境变量。"})
        host = str(_at(data, "server.host") or "").strip().lower()
        if host and host not in {"127.0.0.1", "::1", "localhost"}:
            findings.append({"id": "ATLAS-CONFIG-NONLOOPBACK-BIND", "severity": "medium", "file": rel,
                             "evidence": f"server.host 配置为 {host}", "recommendation": "确认此监听地址只暴露在可信网络；不需要远程访问时绑定 127.0.0.1。"})
    settings_path = root / "data" / "user-settings.json"
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            network = settings.get("model_network", {}) if isinstance(settings, dict) else {}
            ca_path = network.get("ca_bundle_path") if isinstance(network, dict) else None
            if isinstance(ca_path, str) and ca_path.strip() and not Path(ca_path).expanduser().is_file():
                findings.append({"id": "ATLAS-CONFIG-CA-MISSING", "severity": "medium", "file": "data/user-settings.json",
                                 "evidence": "model_network.ca_bundle_path 指向不存在的文件",
                                 "recommendation": "修复 CA 路径或清除自定义 CA 配置。"})
        except (OSError, json.JSONDecodeError):
            findings.append({"id": "ATLAS-SETTINGS-PARSE", "severity": "medium", "file": "data/user-settings.json",
                             "evidence": "本机设置文件不可读或 JSON 无效", "recommendation": "备份后修复本机设置 JSON。"})
    return findings


def refresh_advisories(root: Path, cache_path: Path) -> dict[str, Any]:
    """Refresh an exact-version OSV snapshot. Secrets and arbitrary config are never sent."""
    packages = _dependencies(root)
    results: dict[str, list[dict[str, Any]]] = {}
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        for offset in range(0, len(packages), 1000):
            batch = packages[offset:offset + 1000]
            queries = [{"package": {"ecosystem": row["ecosystem"], "name": row["name"]}, "version": row["version"]} for row in batch]
            response = client.post(_OSV_BATCH, json={"queries": queries})
            response.raise_for_status()
            rows = response.json().get("results", [])
            for package, result in zip(batch, rows):
                key = "|".join((package["ecosystem"], package["name"].lower(), package["version"]))
                results[key] = result.get("vulns", []) if isinstance(result, dict) else []
    snapshot = {"schema_version": 1, "source": _OSV_BATCH,
                "updated_at": datetime.now(timezone.utc).isoformat(), "package_count": len(packages), "results": results}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(cache_path)
    return snapshot


def audit(root: Path, cache_path: Path) -> dict[str, Any]:
    packages = _dependencies(root)
    findings = _config_findings(root)
    snapshot: dict[str, Any] = {}
    cache_status = "missing"
    if cache_path.is_file():
        try:
            snapshot = json.loads(cache_path.read_text(encoding="utf-8"))
            cache_status = "available" if snapshot.get("schema_version") == 1 else "invalid"
        except (OSError, json.JSONDecodeError):
            cache_status = "invalid"
    indexed = snapshot.get("results", {}) if isinstance(snapshot, dict) else {}
    exact_indexed = 0
    for package in packages:
        key = "|".join((package["ecosystem"], package["name"].lower(), package["version"]))
        if key not in indexed:
            continue
        exact_indexed += 1
        for vuln in indexed[key]:
            aliases = vuln.get("aliases") or []
            identifier = next((item for item in aliases if str(item).startswith("CVE-")), None) or vuln.get("id", "OSV-UNKNOWN")
            findings.append({"id": identifier, "osv_id": vuln.get("id"), "severity": "unrated",
                             "package": package["name"], "version": package["version"], "ecosystem": package["ecosystem"],
                             "file": package["lockfile"], "evidence": f"锁定版本 {package['version']} 命中 OSV {vuln.get('id')}",
                             "risk": "OSV advisory match; CVSS severity is not included by querybatch",
                             "recommendation": "查看 OSV 公告的受影响范围和严重度，再升级到首个修复版本并重新生成锁文件。"})
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "advisory_source": snapshot.get("source") if snapshot else _OSV_BATCH,
            "advisory_updated_at": snapshot.get("updated_at"), "advisory_cache": cache_status,
            "offline": True, "dependency_count": len(packages), "indexed_dependency_count": exact_indexed,
            "dependency_coverage": "complete" if exact_indexed == len(packages) else "partial_or_missing",
            "findings": findings}

