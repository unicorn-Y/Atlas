#!/usr/bin/env python3
"""Isolated S7 preparation: snapshot production SQLite files, estimate work, and rehearse cutover.

This script is intentionally Windows-oriented. It never writes to the production
Atlas data/config paths or D:\\MemoryOSData. Production SQLite is opened read-only
and copied with SQLite's backup API; all import, chat, restart, and rollback work
is confined to a caller-supplied run root outside those locations.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import os
import re
import signal
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlsplit

ATLAS_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ATLAS_DB = ATLAS_ROOT / "data" / "atlas.db"
DEFAULT_ATLAS_CONFIG = ATLAS_ROOT / "config" / "atlas.toml"
DEFAULT_MEMORYOS_DB = Path(r"D:\MemoryOSData\db\memoryos.sqlite3")
DEFAULT_MEMORYOS_ROOT = Path(r"D:\MemoryOS")
DEFAULT_ATLAS_PYTHON = ATLAS_ROOT / "core" / ".venv" / "Scripts" / "python.exe"
DEFAULT_MEMORYOS_PYTHON = DEFAULT_MEMORYOS_ROOT / "service" / ".venv" / "Scripts" / "python.exe"
PROTECTED_ROOTS = (
    ATLAS_ROOT / "data",
    ATLAS_ROOT / "config",
    Path(r"D:\MemoryOS"),
    Path(r"D:\MemoryOSData"),
)
SAFE_MODEL_FIELDS = ("id", "name", "provider", "litellm_model", "category", "custom")
SAFE_KEY_FIELDS = ("id", "label", "added_at")
ALLOWED_API_MODES = {"openai", "chat_completions", "anthropic_messages", "codex_responses"}
REHEARSAL_SUBJECT = "f2-c-isolated"


class RehearsalError(RuntimeError):
    """A precondition or isolated rehearsal stage failed safely."""


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def assert_run_root_isolated(run_root: Path, *, protected_roots: Iterable[Path] = PROTECTED_ROOTS,
                             repo_root: Path = ATLAS_ROOT) -> Path:
    root = _resolved(run_root)
    repo = _resolved(repo_root)
    if root == repo or _is_relative_to(root, repo):
        raise RehearsalError("run root must be outside the Atlas checkout")
    for protected in protected_roots:
        protected_path = _resolved(protected)
        if root == protected_path or _is_relative_to(root, protected_path):
            raise RehearsalError("run root overlaps a protected production path")
    return root


def _assert_copy_destination(source: Path, destination: Path,
                             protected_roots: Iterable[Path]) -> tuple[Path, Path]:
    src = _resolved(source)
    dst = _resolved(destination)
    if src == dst or _is_relative_to(dst, src):
        raise RehearsalError("SQLite backup destination overlaps its source")
    if dst.exists():
        raise RehearsalError("refusing to overwrite an existing SQLite backup")
    for protected in protected_roots:
        protected_path = _resolved(protected)
        if dst == protected_path or _is_relative_to(dst, protected_path):
            raise RehearsalError("SQLite backup destination overlaps a protected production path")
    return src, dst


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_hash_or_absent(path: Path) -> str:
    return sha256_file(path) if path.is_file() else "absent"


def _readonly_uri(path: Path) -> str:
    value = quote(_resolved(path).as_posix(), safe="/:\\")
    return f"file:{value}?mode=ro"


def sqlite_backup_readonly(source: Path, destination: Path, *,
                           protected_roots: Iterable[Path] = PROTECTED_ROOTS) -> dict[str, Any]:
    """Copy a SQLite source snapshot without opening it for writes."""
    src, dst = _assert_copy_destination(source, destination, protected_roots)
    if not src.is_file():
        raise RehearsalError("source SQLite database does not exist")
    before = sha256_file(src)
    wal = src.with_name(src.name + "-wal")
    wal_before = _file_hash_or_absent(wal)
    dst.parent.mkdir(parents=True, exist_ok=True)
    source_conn = target_conn = None
    try:
        source_conn = sqlite3.connect(_readonly_uri(src), uri=True, timeout=30)
        source_conn.execute("PRAGMA query_only=ON")
        target_conn = sqlite3.connect(str(dst), timeout=30)
        source_conn.backup(target_conn, pages=512, sleep=0.05)
        target_conn.commit()
        integrity = str(target_conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity.casefold() != "ok":
            raise RehearsalError("SQLite backup integrity check failed")
    finally:
        if target_conn is not None:
            target_conn.close()
        if source_conn is not None:
            source_conn.close()
    after = sha256_file(src)
    wal_after = _file_hash_or_absent(wal)
    return {
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_wal_sha256_before": wal_before,
        "source_wal_sha256_after": wal_after,
        "snapshot_sha256": sha256_file(dst),
        "snapshot_bytes": dst.stat().st_size,
        "source_hash_changed_during_copy": before != after or wal_before != wal_after,
        "snapshot_method": "sqlite_backup_api_read_only_source",
        "integrity_check": "ok",
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_event_type(value: Any) -> str:
    candidate = str(value or "UNKNOWN")
    if re.fullmatch(r"[A-Z0-9_.-]{1,48}", candidate):
        return candidate
    return "OTHER"


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def database_summary(db_path: Path, *, now: datetime | None = None,
                     recent_days: int = 30) -> dict[str, Any]:
    """Return row counts and date/event aggregates; never return payload contents."""
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        tables = _table_names(conn)
        summary: dict[str, Any] = {
            "database_sha256": sha256_file(db_path),
            "integrity_check": str(conn.execute("PRAGMA integrity_check").fetchone()[0]),
            "tables": {},
        }
        for table in ("evidence_events", "memories", "memory_embeddings", "facts",
                      "memory_candidates", "knowledge"):
            if table in tables:
                summary["tables"][table] = int(conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        if "evidence_events" not in tables:
            summary["evidence_events"] = {"present": False}
            return summary

        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cutoff = current - timedelta(days=max(1, int(recent_days)))
        rows = conn.execute(
            "SELECT recorded_at,event_type,length(payload_json) AS payload_chars,"
            "length(CAST(payload_json AS BLOB)) AS payload_bytes "
            "FROM evidence_events").fetchall()
        all_types: Counter[str] = Counter()
        recent_types: Counter[str] = Counter()
        recent_rows = 0
        recent_chars = 0
        recent_utf8_bytes = 0
        invalid_timestamps = 0
        timestamps: list[datetime] = []
        for row in rows:
            event_type = _safe_event_type(row["event_type"])
            all_types[event_type] += 1
            recorded = _parse_timestamp(row["recorded_at"])
            if recorded is None:
                invalid_timestamps += 1
                continue
            timestamps.append(recorded)
            if recorded >= cutoff:
                recent_rows += 1
                recent_types[event_type] += 1
                recent_chars += int(row["payload_chars"] or 0)
                recent_utf8_bytes += int(row["payload_bytes"] or 0)
        summary["evidence_events"] = {
            "present": True,
            "total": len(rows),
            "by_event_type": dict(sorted(all_types.items())),
            "window_start_utc": cutoff.isoformat(),
            "window_end_utc": current.isoformat(),
            "recent_30_day_count": recent_rows,
            "recent_30_day_by_event_type": dict(sorted(recent_types.items())),
            "recent_30_day_payload_chars": recent_chars,
            "recent_30_day_payload_utf8_bytes": recent_utf8_bytes,
            "invalid_recorded_at_rows": invalid_timestamps,
            "oldest_recorded_at_utc": min(timestamps).isoformat() if timestamps else None,
            "newest_recorded_at_utc": max(timestamps).isoformat() if timestamps else None,
        }
        if "memory_embeddings" in tables:
            cols = {str(row["name"]) for row in conn.execute(
                "PRAGMA table_info(memory_embeddings)").fetchall()}
            if "status" in cols:
                summary["memory_embeddings_by_status"] = {
                    str(row["status"] or "UNKNOWN"): int(row["n"])
                    for row in conn.execute(
                        "SELECT status,COUNT(*) AS n FROM memory_embeddings GROUP BY status")
                }
        return summary
    finally:
        conn.close()


def build_isolated_user_settings(source_path: Path, *, memory_model: str) -> dict[str, Any]:
    """Copy provider/model metadata while excluding all credential values."""
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RehearsalError("could not read Atlas model settings") from exc
    if not isinstance(source, dict):
        raise RehearsalError("Atlas model settings are not a JSON object")
    model_id = str(memory_model or "").strip()
    if not model_id:
        model_id = str(source.get("memory_model") or "").strip()
    candidates = source.get("custom_models")
    safe_models = [
        {key: item[key] for key in SAFE_MODEL_FIELDS if key in item}
        for item in candidates if isinstance(item, dict) and str(item.get("id") or "") == model_id
    ] if isinstance(candidates, list) else []
    if not safe_models:
        raise RehearsalError("the configured memory model is not present in custom_models")
    provider_names = {str(item.get("provider") or "") for item in safe_models}
    if provider_names != {"custom"}:
        raise RehearsalError("the configured memory model is not on the custom Gemini route")
    providers = source.get("providers")
    provider = providers.get("custom") if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise RehearsalError("the custom Gemini provider is not configured")
    parsed = urlsplit(str(provider.get("base_url") or ""))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RehearsalError("the Gemini provider must use a loopback reverse proxy")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RehearsalError("the Gemini proxy URL must not embed credentials or query data")
    keys = provider.get("keys")
    safe_keys = [
        {key: item[key] for key in SAFE_KEY_FIELDS if key in item}
        for item in keys if isinstance(item, dict) and str(item.get("id") or "").strip()
    ] if isinstance(keys, list) else []
    if not safe_keys:
        raise RehearsalError("the custom provider has no credential metadata reference")
    safe_provider: dict[str, Any] = {
        "base_url": str(provider.get("base_url") or "").rstrip("/"),
        "keys": safe_keys,
    }
    api_mode = provider.get("api_mode_override")
    if api_mode in ALLOWED_API_MODES:
        safe_provider["api_mode_override"] = api_mode
    result = {
        "custom_models": safe_models,
        "providers": {"custom": safe_provider},
        "memory_model": model_id,
    }
    encoded = json.dumps(result, ensure_ascii=False)
    for forbidden in ("api_key", "secret", "token_value", "credential_value"):
        if forbidden in encoded.casefold():
            raise RehearsalError("isolated settings unexpectedly include a credential value field")
    return result


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _checkpoint(artifact_dir: Path, report: dict[str, Any], completed_stage: str) -> None:
    """Persist only the sanitized report so a later failure keeps prior evidence."""
    report["checkpoint_completed_stage"] = completed_stage
    report["checkpoint_updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(artifact_dir / "F2-C-lifecycle-rehearsal.partial.json", report)


def _source_hashes(*, atlas_db: Path, memoryos_db: Path,
                   settings_source: Path,
                   atlas_config_source: Path = DEFAULT_ATLAS_CONFIG) -> dict[str, str]:
    return {
        "atlas_db": sha256_file(atlas_db),
        "atlas_db_wal": _file_hash_or_absent(atlas_db.with_name(atlas_db.name + "-wal")),
        "memoryos_db": sha256_file(memoryos_db),
        "memoryos_db_wal": _file_hash_or_absent(
            memoryos_db.with_name(memoryos_db.name + "-wal")),
        "settings_source": sha256_file(settings_source),
        "atlas_config_source": _file_hash_or_absent(atlas_config_source),
    }


def _source_files_modified(before: Any, after: Any) -> bool | None:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    if not before or before.keys() != after.keys():
        return None
    return before != after


def _bind_parent_process_to_isolated_roots(*, atlas_data: Path, memoryos_data: Path,
                                           memoryos_db: Path, hermes_home: Path) -> None:
    # ModelManager reads Atlas settings during import/construction. Set every
    # data root before importing Atlas modules so parent-process probes cannot
    # inherit production settings or the user's normal Hermes home.
    if "atlas.config" in sys.modules or "atlas.models" in sys.modules:
        raise RehearsalError("Atlas config/model modules loaded before isolation roots were bound")
    os.environ.update({
        "ATLAS_ROOT": str(ATLAS_ROOT),
        "ATLAS_DATA_DIR": str(atlas_data),
        "MEMORYOS_DATA_ROOT": str(memoryos_data),
        "MEMORYOS_DB_PATH": str(memoryos_db),
        "HERMES_HOME": str(hermes_home),
    })


def _server_cleanup_passed(server_runs: Any) -> bool:
    required = {"enable_chat", "restart", "rollback"}
    if not isinstance(server_runs, list) or len(server_runs) != len(required):
        return False
    if {entry.get("phase") for entry in server_runs if isinstance(entry, dict)} != required:
        return False
    return all(
        entry.get("atlas_exit_code") is not None
        and entry.get("atlas_listener_after_cleanup") is False
        and entry.get("memoryos_listener_after_cleanup") is False
        for entry in server_runs
    )


def _set_stage(run_root: Path, stage: str) -> None:
    (run_root / ".f2c-stage").write_text(stage, encoding="ascii")


def _cleanup_sensitive_run_artifacts(run_root: Path) -> None:
    """Remove raw export and process logs while retaining isolated DB clones."""
    try:
        root = assert_run_root_isolated(run_root)
    except RehearsalError:
        return
    export_dir = root / "legacy-export"
    if export_dir.exists() and not export_dir.is_symlink():
        resolved_export = _resolved(export_dir)
        if _is_relative_to(resolved_export, root) and resolved_export != root:
            shutil.rmtree(resolved_export)
    for pattern in ("*.log", "semantic-trace.jsonl"):
        for path in root.glob(pattern):
            if path.is_file() and not path.is_symlink():
                path.unlink(missing_ok=True)


def _write_isolated_atlas_config(data_root: Path, *, enabled: bool,
                                 service_url: str, memoryos_root: Path,
                                 model_id: str, atlas_port: int) -> None:
    config_path = data_root / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = f'''[general]
name = "Atlas F2-C isolated rehearsal"

[server]
host = "127.0.0.1"
port = {atlas_port}

[models]
default = {json.dumps(model_id)}

[memory]
db_path = "./data/atlas.db"

[memory.unified]
enabled = {str(bool(enabled)).lower()}
capture_mode = "enabled"
subject_binding = {json.dumps(REHEARSAL_SUBJECT)}
service_url = {json.dumps(service_url)}
service_dir = {json.dumps(str(memoryos_root).replace('\\', '/'))}

[scheduler]
enabled = false

[tools]
auto_start = []
'''
    config_path.write_text(config, encoding="utf-8")


def _isolated_environment(run_root: Path, *, atlas_data: Path, memoryos_data: Path,
                          memoryos_db: Path, service_url: str,
                          internal_token: str) -> dict[str, str]:
    # Keep only OS basics needed for Python, Windows Credential Manager, and
    # the existing local model proxy. Never inherit production Atlas/MemoryOS
    # roots or unrelated credential variables into the rehearsal processes.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "USERPROFILE", "HOMEDRIVE",
               "HOMEPATH", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "COMSPEC"}
    env = {name: value for name, value in os.environ.items() if name in allowed}
    env.update({
        "ATLAS_ROOT": str(ATLAS_ROOT),
        "ATLAS_DATA_DIR": str(atlas_data),
        "MEMORYOS_DATA_ROOT": str(memoryos_data),
        "MEMORYOS_DB_PATH": str(memoryos_db),
        "MEMORYOS_SERVICE_URL": service_url,
        "MEMORYOS_INTERNAL_TOKEN": internal_token,
        "MEMORYOS_MEMORY_SUBJECT_ID": REHEARSAL_SUBJECT,
        "MEMORYOS_SEMANTIC_RECALL_ENABLED": "1",
        "MEMORYOS_EMBEDDING_ALLOW_DOWNLOAD": "0",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": "",
        "MEMORYOS_SHADOW_TRACE_PATH": str(run_root / "semantic-trace.jsonl"),
        "HERMES_HOME": str(run_root / "hermes-home"),
    })
    return env


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def _process_children(pid: int, target_port: int) -> list[Any]:
    try:
        import psutil
        root = psutil.Process(pid)
        found = []
        for child in root.children(recursive=True):
            try:
                args = child.cmdline()
                if str(target_port) in args and any("uvicorn" in arg for arg in args):
                    found.append((child, child.create_time()))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found
    except Exception:
        return []


def _stop_atlas_process(process: subprocess.Popen[Any], *, atlas_port: int, memoryos_port: int,
                        graceful: bool = True) -> dict[str, Any]:
    child_records = _process_children(process.pid, memoryos_port)
    used_graceful_signal = False
    if process.poll() is None and graceful and os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            used_graceful_signal = True
        except (OSError, ValueError):
            used_graceful_signal = False
    if process.poll() is None and not used_graceful_signal:
        process.terminate()
    try:
        process.wait(timeout=35 if used_graceful_signal else 12)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)
    child_stopped_by_lifespan = not _port_is_listening(memoryos_port)
    if not child_stopped_by_lifespan:
        # Only terminate process identities captured as descendants of this Atlas
        # instance and matching the isolated MemoryOS port.
        try:
            import psutil
            for child, created in child_records:
                try:
                    if child.is_running() and abs(child.create_time() - created) < 0.01:
                        child.terminate()
                        child.wait(timeout=5)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    continue
        except Exception:
            pass
    return {
        "atlas_exit_code": process.returncode,
        "atlas_listener_after_cleanup": _port_is_listening(atlas_port),
        "used_graceful_signal": used_graceful_signal,
        "memoryos_stopped_by_atlas_lifespan": child_stopped_by_lifespan,
        "memoryos_listener_after_cleanup": _port_is_listening(memoryos_port),
        "captured_memoryos_child_count": len(child_records),
    }


def _run_captured(command: list[str], *, cwd: Path, env: dict[str, str],
                  log_path: Path, timeout: int = 300) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        completed = subprocess.run(command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    if completed.returncode != 0:
        raise RehearsalError(f"isolated command failed with exit code {completed.returncode}")
    return {"exit_code": completed.returncode, "log_path": str(log_path)}


async def _resolve_model_route(model_id: str) -> dict[str, Any]:
    """Resolve the actual configured ModelRouter route without returning its key."""
    from atlas.models import ModelManager

    manager = ModelManager()
    if not hasattr(manager, "model_router"):
        raise RehearsalError("Atlas ModelRouter is unavailable")
    route = await manager.model_router.resolve(model_id, purpose="memory_observe")
    parts = urlsplit(str(getattr(route, "base_url", "") or ""))
    key = str(getattr(route, "key", "") or "")
    if not key:
        raise RehearsalError("ModelRouter could not resolve a credential reference")
    if parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RehearsalError("ModelRouter did not resolve to the local reverse proxy")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise RehearsalError("ModelRouter returned a URL with embedded credential material")
    return {
        "model_id": str(getattr(route, "wire_model", None) or getattr(route, "model", None) or model_id),
        "provider": str(getattr(route, "provider", "")),
        "base_url": str(getattr(route, "base_url", "")),
        "host": parts.hostname,
        "port": parts.port,
        "path": parts.path,
        "key": key,
    }


def _extract_total_tokens(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("totalTokens", "total_tokens", "promptTokenCount", "input_tokens"):
        value = payload.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    usage = payload.get("usageMetadata")
    if isinstance(usage, dict):
        for key in ("promptTokenCount", "totalTokenCount"):
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                return value
    return None


def _conservative_payload_token_bound(utf8_bytes: int) -> dict[str, Any]:
    return {
        "estimated_payload_tokens_upper_bound": max(0, int(utf8_bytes)),
        "token_estimate_kind": "conservative_utf8_byte_upper_bound",
        "tokenizer_exact": False,
    }


async def _count_tokens_proxy(route: dict[str, Any], texts: list[str]) -> dict[str, Any]:
    """Try Gemini's countTokens endpoints through the configured local proxy."""
    import httpx

    base = str(route["base_url"]).rstrip("/")
    parsed = urlsplit(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    model = quote(str(route["model_id"]), safe="-._")
    candidates = [
        base + f"/models/{model}:countTokens",
        origin + f"/v1beta/models/{model}:countTokens",
        origin + f"/v1/models/{model}:countTokens",
    ]
    headers = {
        "Authorization": "Bearer " + str(route["key"]),
        "x-goog-api-key": str(route["key"]),
        "Content-Type": "application/json",
    }
    payload = {"contents": [{"role": "user", "parts": [{"text": texts[0] if texts else "token probe"}]}]}
    status_codes: list[int] = []
    timeout = httpx.Timeout(25, connect=5)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        for url in candidates:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.HTTPError:
                status_codes.append(0)
                continue
            status_codes.append(int(response.status_code))
            if response.is_success:
                total = _extract_total_tokens(response.json())
                if total is not None:
                    return {"status": "supported", "endpoint_path": urlsplit(url).path,
                            "probe_tokens": total, "status_codes": status_codes}
    return {"status": "unsupported", "status_codes": status_codes}


def _iter_payload_batches(db_path: Path, *, cutoff: datetime,
                          max_chars: int = 40000) -> Iterable[list[str]]:
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    batch: list[str] = []
    chars = 0
    try:
        for row in conn.execute(
            "SELECT recorded_at,payload_json FROM evidence_events ORDER BY recorded_at"):
            recorded = _parse_timestamp(row["recorded_at"])
            if recorded is None or recorded < cutoff:
                continue
            payload = str(row["payload_json"] or "")
            if batch and chars + len(payload) > max_chars:
                yield batch
                batch = []
                chars = 0
            # A very large single event is split by characters so count requests
            # remain bounded; reports make this conservative batching explicit.
            if len(payload) > max_chars:
                if batch:
                    yield batch
                    batch = []
                    chars = 0
                for start in range(0, len(payload), max_chars):
                    yield [payload[start:start + max_chars]]
                continue
            batch.append(payload)
            chars += len(payload)
        if batch:
            yield batch
    finally:
        conn.close()


async def estimate_recent_tokens(db_path: Path, *, model_settings_path: Path,
                                 model_id: str, now: datetime | None = None) -> dict[str, Any]:
    """Count bounded recent evidence payloads through Gemini countTokens when exposed."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(days=30)
    batches = iter(_iter_payload_batches(db_path, cutoff=cutoff))
    first_batch = next(batches, None)
    if first_batch is None:
        return {"status": "no_recent_evidence", "window_start_utc": cutoff.isoformat(),
                "window_end_utc": current.isoformat(), "event_payload_batches": 0}

    data_root = _resolved(model_settings_path).parents[1]
    os.environ["ATLAS_ROOT"] = str(ATLAS_ROOT)
    os.environ["ATLAS_DATA_DIR"] = str(data_root)
    route = await _resolve_model_route(model_id)
    endpoint = await _count_tokens_proxy(route, ["F2-C Gemini token counter probe"])
    batch_stream = itertools.chain((first_batch,), batches)
    result: dict[str, Any] = {
        "status": "counted" if endpoint["status"] == "supported" else "proxy_counter_unavailable",
        "model_id": model_id,
        "provider": route["provider"],
        "proxy": {"scheme": "http", "host": route["host"], "port": route["port"],
                  "path": route["path"]},
        "proxy_count_tokens": endpoint,
        "window_start_utc": cutoff.isoformat(),
        "window_end_utc": current.isoformat(),
        "event_payload_batches": None,
        "batch_char_limit": 40000,
        "raw_payload_characters": 0,
        "raw_payload_utf8_bytes": 0,
        "raw_payload_tokens": None,
        "estimated_payload_tokens_upper_bound": None,
        "token_estimate_kind": None,
        "tokenizer_exact": False,
        "observer_prompt_tokens": None,
        "observer_input_tokens_estimate": None,
        "output_tokens_estimate": None,
        "estimated_total_tokens": None,
        "price_usd": None,
        "assumptions": [
            "Counts full evidence payload_json strings as an upper bound, including metadata.",
            "The recent window is selected by evidence_events.recorded_at in UTC.",
            "Output token and repeated prompt overhead are not included unless the proxy exposes countTokens.",
        ],
    }
    import httpx
    count_url = None
    headers = None
    if endpoint["status"] == "supported":
        base = str(route["base_url"]).rstrip("/")
        parsed = urlsplit(base)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        model = quote(str(route["model_id"]), safe="-._")
        count_url = base + f"/models/{model}:countTokens"
        if endpoint["endpoint_path"] != urlsplit(count_url).path:
            count_url = origin + endpoint["endpoint_path"]
        headers = {"Authorization": "Bearer " + route["key"],
                   "x-goog-api-key": route["key"], "Content-Type": "application/json"}
    token_total = 0
    request_count = 0
    probe_failure: str | None = None
    client_context = httpx.AsyncClient(timeout=httpx.Timeout(40, connect=5), trust_env=False)
    async with client_context as client:
        for batch_index, batch in enumerate(batch_stream):
            result["event_payload_batches"] = batch_index + 1
            result["raw_payload_characters"] += sum(len(item) for item in batch)
            result["raw_payload_utf8_bytes"] += sum(len(item.encode("utf-8")) for item in batch)
            if endpoint["status"] != "supported" or probe_failure is not None:
                continue
            material = "\n".join(batch)
            body = {"contents": [{"role": "user", "parts": [{"text": material}]}]}
            try:
                response = await client.post(count_url, headers=headers, json=body)
                response.raise_for_status()
                count = _extract_total_tokens(response.json())
            except (httpx.HTTPError, ValueError):
                probe_failure = "proxy_count_tokens_failed_during_estimate"
                result["status"] = probe_failure
                result["failed_batch_index"] = batch_index
                continue
            if count is None:
                probe_failure = "proxy_count_tokens_response_unrecognized"
                result["status"] = probe_failure
                result["failed_batch_index"] = batch_index
                continue
            token_total += count
            request_count += 1

    if endpoint["status"] != "supported" or probe_failure is not None:
        result.update({
            **_conservative_payload_token_bound(result["raw_payload_utf8_bytes"]),
            "assumptions": [
                "The configured proxy did not provide an exact tokenizer count for every batch.",
                "UTF-8 payload bytes are used as a conservative upper bound on payload token count.",
                "Observer prompt overhead and generated output tokens are excluded.",
                "The recent window is selected by evidence_events.recorded_at in UTC.",
            ],
        })
        return result
    result.update({
        "status": "counted",
        "proxy_payload_count_requests": request_count,
        "raw_payload_tokens": token_total,
        "token_estimate_kind": "gemini_count_tokens",
        "tokenizer_exact": True,
        "observer_input_tokens_estimate": token_total,
        "estimated_total_tokens": token_total,
        "assumptions": [
            "Gemini countTokens was called through the configured loopback reverse proxy.",
            "Counts full evidence payload_json strings as an upper bound, including metadata.",
            "Observer prompt overhead and generated output tokens are excluded; total is a lower bound for full Observer replay.",
            "The recent window is selected by evidence_events.recorded_at in UTC.",
        ],
    })
    return result


def _service_url(memory_port: int) -> str:
    return f"http://127.0.0.1:{memory_port}"


def _write_runtime_settings(data_root: Path, source_settings: Path, model_id: str) -> Path:
    settings = build_isolated_user_settings(source_settings, memory_model=model_id)
    path = data_root / "data" / "user-settings.json"
    _write_json(path, settings)
    return path


def _start_atlas(*, run_root: Path, atlas_data: Path, memoryos_data: Path,
                 memoryos_db: Path, memoryos_root: Path, model_id: str,
                 atlas_python: Path, service_port: int, atlas_port: int,
                 enabled: bool, settings_source: Path, internal_token: str,
                 log_path: Path) -> tuple[subprocess.Popen[Any], dict[str, str], Path]:
    if _port_is_listening(service_port):
        raise RehearsalError("isolated MemoryOS port is already occupied")
    service_url = _service_url(service_port)
    _write_isolated_atlas_config(
        atlas_data, enabled=enabled, service_url=service_url,
        memoryos_root=memoryos_root, model_id=model_id, atlas_port=atlas_port,
    )
    settings_path = _write_runtime_settings(atlas_data, settings_source, model_id)
    env = _isolated_environment(run_root, atlas_data=atlas_data,
                                memoryos_data=memoryos_data, memoryos_db=memoryos_db,
                                service_url=service_url, internal_token=internal_token)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("wb")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(atlas_python), "-m", "uvicorn", "atlas.server:app", "--host", "127.0.0.1",
         "--port", str(atlas_port), "--log-level", "warning"],
        cwd=str(ATLAS_ROOT / "core"), env=env, stdin=subprocess.DEVNULL,
        stdout=log_handle, stderr=subprocess.STDOUT, creationflags=creationflags,
    )
    # Keep the stream open for the child's lifetime; the parent process object
    # owns the descriptor until _close_log_handle closes it.
    setattr(process, "_f2c_log_handle", log_handle)
    return process, env, settings_path


def _close_log_handle(process: subprocess.Popen[Any]) -> None:
    handle = getattr(process, "_f2c_log_handle", None)
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass


async def _wait_http(url: str, *, timeout: float, expected: int = 200) -> dict[str, Any]:
    import httpx

    started = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=0.5), trust_env=False) as client:
        while time.monotonic() - started < timeout:
            try:
                response = await client.get(url)
                if response.status_code == expected:
                    try:
                        body = response.json()
                    except ValueError:
                        body = None
                    return {"status_code": response.status_code,
                            "elapsed_seconds": round(time.monotonic() - started, 3),
                            "body": body}
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
    raise RehearsalError("isolated HTTP readiness check timed out")


async def _create_and_send_real_chat(*, atlas_url: str, model_id: str,
                                     workspace: Path, prompt: str,
                                     expected_marker: str | None = None,
                                     raw_receipt_path: Path | None = None) -> dict[str, Any]:
    import httpx
    from websockets.asyncio.client import connect

    workspace.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=atlas_url, timeout=30, trust_env=False) as client:
        response = await client.post("/api/conversations", json={
            "title": "F2-C isolated marker verification",
        })
        if response.status_code != 200:
            raise RehearsalError("could not create an isolated Atlas conversation")
        conversation_id = str(response.json().get("id") or "")
    if not conversation_id:
        raise RehearsalError("isolated Atlas conversation response had no id")

    run_id = uuid.uuid4().hex
    ws_url = atlas_url.replace("http://", "ws://", 1) + "/ws/chat"
    chunks: list[str] = []
    event_types: list[str] = []
    terminal = ""
    usage: dict[str, int] = {}
    async with connect(ws_url, open_timeout=20, close_timeout=5, max_size=8_000_000,
                       additional_headers={"Origin": atlas_url}) as ws:
        await ws.send(json.dumps({
            "type": "run.start", "run_id": run_id, "content": prompt,
            "conversation_id": conversation_id, "workspace": str(workspace),
            "model": model_id, "mode": "act", "permission_mode": "read_only",
            "active_skills": [],
        }, ensure_ascii=False))
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
            try:
                envelope = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(envelope, dict) or envelope.get("run_id") != run_id:
                continue
            event = str(envelope.get("event") or "")
            event_types.append(event)
            data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
            if event == "message.delta":
                delta = data.get("text") or data.get("delta") or data.get("content") or ""
                if isinstance(delta, str):
                    chunks.append(delta)
            if event in {"run.completed", "run.failed", "run.cancelled"}:
                terminal = event
                for key in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
                    value = data.get(key)
                    if isinstance(value, int) and value >= 0:
                        usage[key] = value
                break
        if not terminal:
            raise RehearsalError("real Atlas WebSocket chat did not reach a terminal event")
    answer = "".join(chunks).strip()
    if terminal != "run.completed" or not answer:
        raise RehearsalError("real Atlas WebSocket chat failed")
    exact_marker_answer = answer.strip().strip("`'\" .。!！?？") == expected_marker if expected_marker else False
    if raw_receipt_path is not None:
        raw_receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt = {
            "conversation_id": conversation_id,
            "prompt": prompt,
            "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
            "answer_chars": len(answer),
            "answer_matches_expected_marker": bool(expected_marker and expected_marker.casefold() in answer.casefold()),
            "answer_output": answer if exact_marker_answer else "[redacted; output was not exactly the synthetic marker]",
        }
        with raw_receipt_path.open("a", encoding="utf-8") as raw_file:
            raw_file.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    return {
        "status": "completed",
        "real_model_router": True,
        "model_id": model_id,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "conversation_id": conversation_id,
        "run_id": run_id,
        "terminal_event": terminal,
        "event_count": len(event_types),
        "event_types": event_types,
        "answer_chars": len(answer),
        "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        "answer_matches_expected_marker": bool(expected_marker and expected_marker.casefold() in answer.casefold())
            if expected_marker else None,
        "answer_is_exact_expected_marker": exact_marker_answer if expected_marker else None,
        "provider_usage": usage,
    }


def _count_marker_evidence(db_path: Path, marker: str) -> int:
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True, timeout=30)
    conn.execute("PRAGMA query_only=ON")
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_events'").fetchone()
        if not exists:
            return 0
        return int(conn.execute(
            "SELECT COUNT(*) FROM evidence_events WHERE instr(payload_json, ?) > 0",
            (marker,),
        ).fetchone()[0])
    finally:
        conn.close()


async def _verify_unified_recall(*, service_url: str, internal_token: str,
                                 marker: str, runtime_session_id: str) -> dict[str, Any]:
    import httpx

    context = {
        "owner_id": "owner-local",
        "memory_subject_id": REHEARSAL_SUBJECT,
        "client_id": "atlas-f2-c-isolated",
        "actor_id": "atlas-f2-c-isolated",
        "runtime_session_id": runtime_session_id,
        "environment_id": "isolated-rehearsal",
    }
    body = {"context": context, "query": marker, "purpose": "CONVERSATION"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=3), trust_env=False) as client:
        try:
            response = await client.post(
                service_url.rstrip("/") + "/v1/unified/recall", json=body,
                headers={"Authorization": "Bearer " + internal_token},
            )
        except httpx.HTTPError:
            return {"status": "request_failed", "http_status": None,
                    "query_sha256": hashlib.sha256(marker.encode("utf-8")).hexdigest()}
    try:
        result = response.json()
    except ValueError:
        result = {}
    items = result.get("context_items") if isinstance(result, dict) else None
    snippets = result.get("source_snippets") if isinstance(result, dict) else None
    items = items if isinstance(items, list) else []
    snippets = snippets if isinstance(snippets, list) else []
    matched_items = [item for item in items if marker.casefold() in json.dumps(item, ensure_ascii=False).casefold()]
    matched_snippets = [item for item in snippets if marker.casefold() in json.dumps(item, ensure_ascii=False).casefold()]
    refs: list[str] = []
    for item in matched_items + matched_snippets:
        if not isinstance(item, dict):
            continue
        for key in ("record_ref", "evidence_ref", "source_ref", "ref"):
            value = item.get(key)
            if isinstance(value, str) and value and value not in refs:
                refs.append(value)
        source_refs = item.get("source_refs")
        if isinstance(source_refs, list):
            refs.extend(str(value) for value in source_refs if isinstance(value, str) and value not in refs)
    matched_payload = json.dumps(matched_items + matched_snippets, ensure_ascii=False)
    return {
        "status": "checked" if response.status_code == 200 else "http_error",
        "http_status": int(response.status_code),
        "query_sha256": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
        "context_item_count": len(items),
        "source_snippet_count": len(snippets),
        "marker_present_in_recall": marker.casefold() in matched_payload.casefold(),
        "matched_item_count": len(matched_items),
        "matched_snippet_count": len(matched_snippets),
        "matched_record_refs": refs,
        "context_hash_present": bool(result.get("context_hash")) if isinstance(result, dict) else False,
    }


async def _probe_legacy_memory_api(atlas_url: str) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=2), trust_env=False) as client:
        try:
            response = await client.get(atlas_url.rstrip("/") + "/api/memory/candidates")
        except httpx.HTTPError:
            return {"status": "request_failed", "http_status": None, "candidate_count": None}
    try:
        body = response.json()
    except ValueError:
        body = None
    return {
        "status": "available" if response.status_code == 200 and isinstance(body, list) else "unavailable",
        "http_status": int(response.status_code),
        "candidate_count": len(body) if isinstance(body, list) else None,
    }


async def _wait_for_memoryos(url: str, *, internal_token: str, timeout: float = 240) -> dict[str, Any]:
    health = await _wait_http(url.rstrip("/") + "/v1/health", timeout=min(timeout, 120))
    status_url = url.rstrip("/") + "/v1/unified/status"
    started = time.monotonic()
    semantic: dict[str, Any] = {}
    status_code: int | None = None
    import httpx

    async with httpx.AsyncClient(timeout=httpx.Timeout(2, connect=1), trust_env=False) as client:
        while time.monotonic() - started < timeout:
            try:
                response = await client.get(status_url,
                                            headers={"Authorization": "Bearer " + internal_token})
                status_code = int(response.status_code)
                if response.status_code == 200:
                    body = response.json()
                    candidate = body.get("semantic") if isinstance(body, dict) else None
                    semantic = candidate if isinstance(candidate, dict) else {}
                    state = str(semantic.get("state") or "UNKNOWN").upper()
                    if state in {"READY", "ERROR", "DISABLED"}:
                        break
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(0.5)
    state = str(semantic.get("state") or "UNKNOWN").upper()
    return {
        "healthy": True,
        "health_elapsed_seconds": health["elapsed_seconds"],
        "semantic_worker_state": state,
        "semantic_worker_ready_elapsed_seconds": round(time.monotonic() - started, 3)
            if state == "READY" else None,
        "semantic_pending_embeddings": int(semantic.get("pending_count") or 0),
        "semantic_model_id": semantic.get("model_id"),
        "semantic_device": semantic.get("device"),
        "semantic_error_present": bool(semantic.get("error")),
        "semantic_status_http_code": status_code,
        "health_status": (health.get("body") or {}).get("status") if isinstance(health.get("body"), dict) else None,
    }


async def _read_semantic_status(url: str, internal_token: str) -> dict[str, Any]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3, connect=1), trust_env=False) as client:
            response = await client.get(
                url.rstrip("/") + "/v1/unified/status",
                headers={"Authorization": "Bearer " + internal_token},
            )
            if response.status_code != 200:
                return {"http_status": int(response.status_code), "state": "UNKNOWN"}
            body = response.json()
    except (httpx.HTTPError, ValueError):
        return {"http_status": None, "state": "UNKNOWN"}
    semantic = body.get("semantic") if isinstance(body, dict) else None
    if not isinstance(semantic, dict):
        return {"http_status": 200, "state": "UNKNOWN"}
    return {
        "http_status": 200,
        "state": str(semantic.get("state") or "UNKNOWN").upper(),
        "pending_count": int(semantic.get("pending_count") or 0),
        "model_id": semantic.get("model_id"),
        "device": semantic.get("device"),
        "error_present": bool(semantic.get("error")),
    }


async def _estimate_embedding_backfill(url: str, *, internal_token: str, pending_at_ready: int,
                                       observation_seconds: float = 30) -> dict[str, Any]:
    started = time.monotonic()
    latest = {"state": "UNKNOWN", "pending_count": pending_at_ready}
    while time.monotonic() - started < observation_seconds:
        latest = await _read_semantic_status(url, internal_token)
        if latest.get("state") in {"ERROR", "UNKNOWN"} or int(latest.get("pending_count") or 0) <= 0:
            break
        await asyncio.sleep(min(1.0, max(0.0, observation_seconds - (time.monotonic() - started))))
    elapsed = max(0.001, time.monotonic() - started)
    raw_pending_after = latest.get("pending_count")
    pending_after = int(raw_pending_after) if isinstance(raw_pending_after, int) else None
    completed = max(0, int(pending_at_ready) - pending_after) if pending_after is not None else None
    throughput = completed / elapsed if completed is not None and completed > 0 else 0.0
    estimated_remaining = 0.0 if pending_after == 0 else (
        pending_after / throughput if pending_after is not None and throughput > 0 else None
    )
    return {
        "semantic_worker_state": latest.get("state"),
        "pending_embeddings_at_ready": int(pending_at_ready),
        "pending_embeddings_after_observation": pending_after,
        "observation_seconds": round(elapsed, 3),
        "completed_during_observation": completed,
        "observed_embeddings_per_second": round(throughput, 3),
        "estimated_backfill_seconds_remaining": round(estimated_remaining, 1)
            if estimated_remaining is not None else None,
        "estimate_basis": "isolated production database clone; local semantic worker; observed pending queue reduction",
    }


def _count_memoryos_evidence(db_path: Path) -> int:
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True, timeout=30)
    conn.execute("PRAGMA query_only=ON")
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_events'").fetchone()
        return int(conn.execute("SELECT COUNT(*) FROM evidence_events").fetchone()[0]) if exists else 0
    finally:
        conn.close()


async def _wait_evidence_growth(db_path: Path, baseline: int, *, timeout: float = 45) -> dict[str, Any]:
    started = time.monotonic()
    current = baseline
    while time.monotonic() - started < timeout:
        try:
            current = _count_memoryos_evidence(db_path)
        except sqlite3.Error:
            await asyncio.sleep(0.5)
            continue
        if current > baseline:
            return {"baseline": baseline, "after_chat": current,
                    "new_evidence_events": current - baseline,
                    "wait_seconds": round(time.monotonic() - started, 3)}
        await asyncio.sleep(0.5)
    return {"baseline": baseline, "after_chat": current,
            "new_evidence_events": max(0, current - baseline),
            "wait_seconds": round(time.monotonic() - started, 3),
            "timed_out": current <= baseline}


async def _wait_marker_evidence_growth(db_path: Path, marker: str, baseline: int,
                                       *, timeout: float = 45) -> dict[str, Any]:
    started = time.monotonic()
    current = baseline
    while time.monotonic() - started < timeout:
        try:
            current = _count_marker_evidence(db_path, marker)
        except sqlite3.Error:
            await asyncio.sleep(0.5)
            continue
        if current > baseline:
            return {"baseline_marker_rows": baseline, "after_chat_marker_rows": current,
                    "new_marker_evidence_rows": current - baseline,
                    "wait_seconds": round(time.monotonic() - started, 3)}
        await asyncio.sleep(0.5)
    return {"baseline_marker_rows": baseline, "after_chat_marker_rows": current,
            "new_marker_evidence_rows": max(0, current - baseline),
            "wait_seconds": round(time.monotonic() - started, 3),
            "timed_out": current <= baseline}


async def run_full_rehearsal(*, run_root: Path, artifact_dir: Path,
                             atlas_db: Path, memoryos_db: Path,
                             settings_source: Path, atlas_python: Path,
                             memoryos_python: Path, memoryos_root: Path) -> dict[str, Any]:
    root = assert_run_root_isolated(run_root)
    root.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(timezone.utc)
    atlas_data = root / "atlas-data"
    memoryos_data = root / "memoryos-data"
    hermes_home = root / "hermes-home"
    # AtlasConfig resolves the default relative DB path under ATLAS_DATA_DIR.
    atlas_db_copy = atlas_data / "data" / "atlas.db"
    memoryos_db_copy = memoryos_data / "db" / "memoryos.sqlite3"
    atlas_db_copy.parent.mkdir(parents=True, exist_ok=True)
    memoryos_db_copy.parent.mkdir(parents=True, exist_ok=True)
    for path in (atlas_data, memoryos_data, hermes_home):
        path.mkdir(parents=True, exist_ok=True)
    _bind_parent_process_to_isolated_roots(
        atlas_data=atlas_data, memoryos_data=memoryos_data,
        memoryos_db=memoryos_db_copy, hermes_home=hermes_home,
    )
    source_hashes_before = _source_hashes(
        atlas_db=atlas_db, memoryos_db=memoryos_db, settings_source=settings_source,
    )
    server_runs: list[dict[str, Any]] = []

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress",
        "started_at_utc": started_at.isoformat(),
        "production_write_allowed": False,
        "production_write_attempted_by_script": False,
        "production_files_modified": None,
        "production_files_modified_by_script": False,
        "production_file_change_attribution": "unknown_until_final_hash_comparison",
        "source_hashes_before": source_hashes_before,
        "source_hashes_unchanged": None,
        "credentials_recorded": False,
        "source_paths": {"atlas_db": str(_resolved(atlas_db)),
                         "memoryos_db": str(_resolved(memoryos_db)),
                         "settings_source": str(_resolved(settings_source)),
                         "atlas_config_source": str(_resolved(DEFAULT_ATLAS_CONFIG))},
        "isolated_roots": {"run_root": str(root), "atlas_data": str(atlas_data),
                            "memoryos_data": str(memoryos_data), "hermes_home": str(hermes_home)},
        "stages": {},
        "server_cleanup": server_runs,
    }
    _checkpoint(artifact_dir, report, "baseline")
    _set_stage(root, "sqlite_backup")
    report["stages"]["sqlite_backup"] = {
        "atlas": sqlite_backup_readonly(atlas_db, atlas_db_copy),
        "memoryos": sqlite_backup_readonly(memoryos_db, memoryos_db_copy),
    }
    _checkpoint(artifact_dir, report, "sqlite_backup")
    report["stages"]["production_snapshot_stats"] = {
        "atlas": database_summary(atlas_db_copy),
        "memoryos": database_summary(memoryos_db_copy),
    }
    _checkpoint(artifact_dir, report, "production_snapshot_stats")
    _set_stage(root, "model_settings")
    model_settings = json.loads(settings_source.read_text(encoding="utf-8"))
    model_id = str(model_settings.get("memory_model") or "").strip()
    if not model_id:
        raise RehearsalError("Atlas memory_model is not configured")
    report["stages"]["model_route"] = {"model_id": model_id,
                                        "provider_base_host": "127.0.0.1",
                                        "provider_base_port": 8045,
                                        "credentials_recorded": False}
    _checkpoint(artifact_dir, report, "model_route")

    # Read-only Atlas legacy export from the isolated Atlas DB copy.
    export_dir = root / "legacy-export"
    atlas_env = {name: value for name, value in os.environ.items()
                 if name in {"PATH", "SYSTEMROOT", "WINDIR", "USERPROFILE", "HOMEDRIVE",
                             "HOMEPATH", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "COMSPEC"}}
    atlas_env.update({"ATLAS_ROOT": str(ATLAS_ROOT), "ATLAS_DATA_DIR": str(atlas_data)})
    _set_stage(root, "legacy_export")
    export_result = _run_captured(
        [str(atlas_python), str(ATLAS_ROOT / "scripts" / "unified_memory" / "export_legacy.py"),
         "--db", str(atlas_db_copy), "--out", str(export_dir), "--subject", REHEARSAL_SUBJECT],
        cwd=ATLAS_ROOT, env=atlas_env, log_path=root / "export-legacy.log", timeout=120,
    )
    export_summary = json.loads((export_dir / "summary.json").read_text(encoding="utf-8"))
    report["stages"]["legacy_export"] = {
        "exit_code": export_result["exit_code"],
        "read_only_source_copy": True,
        "total_rows": int(export_summary.get("total_rows") or 0),
        "tables": {name: {"rows": int(value.get("rows") or 0),
                           "content_hash": value.get("content_hash")}
                   for name, value in (export_summary.get("tables") or {}).items()},
    }
    _checkpoint(artifact_dir, report, "legacy_export")
    (root / "export-legacy.log").unlink(missing_ok=True)

    service_port = _free_loopback_port()
    atlas_port = _free_loopback_port()
    service_url = _service_url(service_port)
    internal_token = secrets.token_urlsafe(32)
    marker = "F2C-" + uuid.uuid4().hex[:12].upper()
    marker_sha256 = hashlib.sha256(marker.encode("utf-8")).hexdigest()
    raw_receipt_path = Path(r"D:\Temp") / f"F2-C-synthetic-chat-{root.name}.jsonl"
    remember_prompt = (
        "请记住这一条仅用于隔离演练的合成事实：我的 F2 测试标记是 "
        f"{marker}。请简短回复已记下。"
    )
    recall_prompt = (
        "这是一个新的对话。请基于已经保存的隔离演练记忆回答："
        "我刚才设定的 F2 测试标记是什么？只回复标记，不要猜。"
    )
    isolation_env = _isolated_environment(root, atlas_data=atlas_data,
                                          memoryos_data=memoryos_data,
                                          memoryos_db=memoryos_db_copy,
                                          service_url=service_url,
                                          internal_token=internal_token)
    # Enable: Atlas lifespan auto-launches MemoryOS against the clone.
    enable_started = time.monotonic()
    _set_stage(root, "enable_and_real_chat")
    process, env, settings_path = _start_atlas(
        run_root=root, atlas_data=atlas_data, memoryos_data=memoryos_data,
        memoryos_db=memoryos_db_copy, memoryos_root=memoryos_root,
        model_id=model_id, atlas_python=atlas_python, service_port=service_port,
        atlas_port=atlas_port, enabled=True, settings_source=settings_source,
        internal_token=internal_token,
        log_path=root / "atlas-enable.log",
    )
    atlas_url = f"http://127.0.0.1:{atlas_port}"
    try:
        atlas_ready = await _wait_http(atlas_url + "/api/health", timeout=120)
        memory_ready = await _wait_for_memoryos(
            service_url, internal_token=internal_token, timeout=300,
        )
        report["stages"]["embedding_warmup_and_backfill"] = {
            "atlas_process_to_semantic_ready_seconds": round(time.monotonic() - enable_started, 3)
                if memory_ready.get("semantic_worker_state") == "READY" else None,
            **await _estimate_embedding_backfill(
                service_url, internal_token=internal_token,
                pending_at_ready=int(memory_ready.get("semantic_pending_embeddings") or 0),
            ),
        }
        _checkpoint(artifact_dir, report, "embedding_warmup_and_backfill")

        # Count copied 30-day evidence before importing test fixtures, then call
        # Gemini through the configured loopback proxy. Payloads are not saved.
        try:
            report["stages"]["recent_30_day_token_estimate"] = await estimate_recent_tokens(
                memoryos_db_copy, model_settings_path=settings_path, model_id=model_id,
            )
        except Exception as exc:
            report["stages"]["recent_30_day_token_estimate"] = {
                "status": "probe_failed", "error_type": type(exc).__name__,
                "model_id": model_id, "credentials_recorded": False,
            }
        _checkpoint(artifact_dir, report, "recent_30_day_token_estimate")

        # Legacy import writes only through this isolated MemoryOS service. TEST
        # prevents imported facts from being marked as durable prod events.
        import_result = _run_captured(
            [str(memoryos_python), str(memoryos_root / "scripts" / "unified_memory" / "import_legacy.py"),
             "--input", str(export_dir), "--service-url", service_url,
             "--subject", REHEARSAL_SUBJECT, "--event-class", "TEST"],
            cwd=memoryos_root, env=isolation_env, log_path=root / "import-legacy.log", timeout=120,
        )
        import_raw = json.loads((export_dir / "import_result.json").read_text(encoding="utf-8"))
        report["stages"]["legacy_import_copy_only"] = {
            "exit_code": import_result["exit_code"],
            "event_class": "TEST",
            "target_isolated_database": str(memoryos_db_copy),
            "production_target_used": False,
            "exported_rows": int(import_raw.get("exported_rows") or 0),
            "created": int(import_raw.get("created") or 0),
            "duplicates": int(import_raw.get("duplicates") or 0),
            "conflicts": int(import_raw.get("conflicts") or 0),
        }
        _checkpoint(artifact_dir, report, "legacy_import_copy_only")
        shutil.rmtree(export_dir)
        (root / "import-legacy.log").unlink(missing_ok=True)

        evidence_before_chat = _count_memoryos_evidence(memoryos_db_copy)
        marker_evidence_before_chat = _count_marker_evidence(memoryos_db_copy, marker)
        chat = await _create_and_send_real_chat(
            atlas_url=atlas_url, model_id=model_id, workspace=root / "workspace",
            prompt=remember_prompt, raw_receipt_path=raw_receipt_path,
        )
        chat_capture = await _wait_evidence_growth(memoryos_db_copy, evidence_before_chat)
        marker_capture = await _wait_marker_evidence_growth(
            memoryos_db_copy, marker, marker_evidence_before_chat,
        )
        report["stages"]["enable_and_real_chat"] = {
            "atlas_health_seconds": atlas_ready["elapsed_seconds"],
            "atlas_health_status": (atlas_ready.get("body") or {}).get("status")
                if isinstance(atlas_ready.get("body"), dict) else None,
            "memoryos": memory_ready,
            "chat": chat,
            "capture": chat_capture,
            "marker_sha256": marker_sha256,
            "marker_capture": marker_capture,
            "semantic_enabled_env": env.get("MEMORYOS_SEMANTIC_RECALL_ENABLED") == "1",
            "atlas_config_enabled": True,
            "temporary_settings_path": str(settings_path),
            "raw_synthetic_chat_evidence_path": str(raw_receipt_path),
        }
    finally:
        stop = _stop_atlas_process(process, atlas_port=atlas_port, memoryos_port=service_port)
        _close_log_handle(process)
        (root / "atlas-enable.log").unlink(missing_ok=True)
        server_runs.append({"phase": "enable_chat", **stop})
        _checkpoint(artifact_dir, report, "enable_chat_cleanup")

    if _port_is_listening(atlas_port) or _port_is_listening(service_port):
        raise RehearsalError("a rehearsal listener survived the enable-phase Atlas shutdown")
    _checkpoint(artifact_dir, report, "enable_and_real_chat")

    # Restart with the same enabled config and the same cloned database.
    atlas_port_2 = _free_loopback_port()
    _set_stage(root, "restart")
    process, env, settings_path = _start_atlas(
        run_root=root, atlas_data=atlas_data, memoryos_data=memoryos_data,
        memoryos_db=memoryos_db_copy, memoryos_root=memoryos_root,
        model_id=model_id, atlas_python=atlas_python, service_port=service_port,
        atlas_port=atlas_port_2, enabled=True, settings_source=settings_source,
        internal_token=internal_token,
        log_path=root / "atlas-restart.log",
    )
    try:
        restarted_health = await _wait_http(f"http://127.0.0.1:{atlas_port_2}/api/health", timeout=120)
        restarted_memory = await _wait_for_memoryos(
            service_url, internal_token=internal_token, timeout=300,
        )
        recall_check = await _verify_unified_recall(
            service_url=service_url, internal_token=internal_token, marker=marker,
            runtime_session_id="f2-c-recall-" + uuid.uuid4().hex,
        )
        post_restart_evidence_baseline = _count_memoryos_evidence(memoryos_db_copy)
        post_restart_marker_baseline = _count_marker_evidence(memoryos_db_copy, marker)
        post_restart_chat = await _create_and_send_real_chat(
            atlas_url=f"http://127.0.0.1:{atlas_port_2}", model_id=model_id,
            workspace=root / "workspace", prompt=recall_prompt,
            expected_marker=marker, raw_receipt_path=raw_receipt_path,
        )
        post_restart_capture = await _wait_evidence_growth(
            memoryos_db_copy, post_restart_evidence_baseline,
        )
        post_restart_marker_capture = await _wait_marker_evidence_growth(
            memoryos_db_copy, marker, post_restart_marker_baseline,
        )
        report["stages"]["restart"] = {
            "atlas_health_seconds": restarted_health["elapsed_seconds"],
            "atlas_health_status": (restarted_health.get("body") or {}).get("status")
                if isinstance(restarted_health.get("body"), dict) else None,
            "memoryos": restarted_memory,
            "memoryos_auto_started_again": True,
            "same_isolated_database": str(memoryos_db_copy),
            "post_restart_recall": recall_check,
            "post_restart_chat": post_restart_chat,
            "post_restart_capture": post_restart_capture,
            "post_restart_marker_capture": post_restart_marker_capture,
        }
    finally:
        stop = _stop_atlas_process(process, atlas_port=atlas_port_2, memoryos_port=service_port)
        _close_log_handle(process)
        (root / "atlas-restart.log").unlink(missing_ok=True)
        server_runs.append({"phase": "restart"})
        server_runs[-1].update(stop)
        _checkpoint(artifact_dir, report, "restart_cleanup")

    if _port_is_listening(atlas_port_2) or _port_is_listening(service_port):
        raise RehearsalError("a rehearsal listener survived the restart-phase Atlas shutdown")
    _checkpoint(artifact_dir, report, "restart")

    # Roll back the copied Atlas config only; unified is disabled while the
    # MemoryOS database remains intact and its automatic child is absent.
    atlas_port_3 = _free_loopback_port()
    _set_stage(root, "rollback")
    _write_isolated_atlas_config(
        atlas_data, enabled=False, service_url=service_url,
        memoryos_root=memoryos_root, model_id=model_id, atlas_port=atlas_port_3,
    )
    process, env, settings_path = _start_atlas(
        run_root=root, atlas_data=atlas_data, memoryos_data=memoryos_data,
        memoryos_db=memoryos_db_copy, memoryos_root=memoryos_root,
        model_id=model_id, atlas_python=atlas_python, service_port=service_port,
        atlas_port=atlas_port_3, enabled=False, settings_source=settings_source,
        internal_token=internal_token,
        log_path=root / "atlas-rollback.log",
    )
    try:
        rollback_health = await _wait_http(f"http://127.0.0.1:{atlas_port_3}/api/health", timeout=120)
        await asyncio.sleep(1)
        disabled_service_absent = not _port_is_listening(service_port)
        legacy_path = await _probe_legacy_memory_api(f"http://127.0.0.1:{atlas_port_3}")
        report["stages"]["rollback"] = {
            "atlas_health_seconds": rollback_health["elapsed_seconds"],
            "atlas_config_enabled": False,
            "atlas_legacy_db_path": str(atlas_db_copy),
            "atlas_legacy_memory_api": legacy_path,
            "memoryos_auto_started": not disabled_service_absent,
            "memoryos_listener_absent": disabled_service_absent,
            "memoryos_data_preserved": memoryos_db_copy.is_file(),
            "memoryos_evidence_count": _count_memoryos_evidence(memoryos_db_copy),
        }
    finally:
        stop = _stop_atlas_process(process, atlas_port=atlas_port_3,
                                   memoryos_port=service_port, graceful=False)
        _close_log_handle(process)
        (root / "atlas-rollback.log").unlink(missing_ok=True)
        server_runs.append({"phase": "rollback", **stop})
        _checkpoint(artifact_dir, report, "rollback_cleanup")
    _checkpoint(artifact_dir, report, "rollback")

    final_memory_summary = database_summary(memoryos_db_copy)
    source_hashes_after = _source_hashes(
        atlas_db=atlas_db, memoryos_db=memoryos_db, settings_source=settings_source,
    )
    source_hashes_unchanged = source_hashes_before == source_hashes_after
    production_files_modified = _source_files_modified(source_hashes_before, source_hashes_after)
    report["stages"]["final_checks"] = {
        "production_hashes_unchanged": source_hashes_unchanged,
        "production_hashes_before": source_hashes_before,
        "production_hashes_after": source_hashes_after,
        "memoryos_clone_summary": final_memory_summary,
        "server_cleanup": server_runs,
        "all_servers_cleaned": _server_cleanup_passed(server_runs),
        "memoryos_clone_retained_at": str(memoryos_db_copy),
    }
    report["production_files_modified"] = production_files_modified
    report["production_files_modified_by_script"] = False
    report["production_file_change_attribution"] = (
        "external_or_concurrent_writer" if production_files_modified is True
        else "none_observed" if production_files_modified is False else "unknown"
    )
    report["source_hashes_unchanged"] = source_hashes_unchanged
    report["source_hashes_after"] = source_hashes_after
    report["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["status"] = "passed" if (
        report["source_hashes_unchanged"] is True
        and report["production_files_modified"] is False
        and report["stages"]["final_checks"]["all_servers_cleaned"]
        and report["stages"].get("enable_and_real_chat", {}).get("chat", {}).get("real_model_router")
        and report["stages"].get("enable_and_real_chat", {}).get("chat", {}).get("status") == "completed"
        and report["stages"].get("enable_and_real_chat", {}).get("capture", {}).get("new_evidence_events", 0) > 0
        and report["stages"].get("enable_and_real_chat", {}).get("marker_capture", {}).get("new_marker_evidence_rows", 0) > 0
        and report["stages"].get("enable_and_real_chat", {}).get("memoryos", {}).get("semantic_worker_state") == "READY"
        and report["stages"].get("restart", {}).get("memoryos_auto_started_again")
        and report["stages"].get("restart", {}).get("memoryos", {}).get("semantic_worker_state") == "READY"
        and report["stages"].get("rollback", {}).get("memoryos_listener_absent")
        and report["stages"].get("rollback", {}).get("atlas_legacy_memory_api", {}).get("status") == "available"
        and report["stages"].get("restart", {}).get("post_restart_recall", {}).get("marker_present_in_recall")
        and bool(report["stages"].get("restart", {}).get("post_restart_recall", {}).get("matched_record_refs"))
        and report["stages"].get("restart", {}).get("post_restart_chat", {}).get("answer_matches_expected_marker")
        and report["stages"].get("restart", {}).get("post_restart_marker_capture", {}).get("new_marker_evidence_rows", 0) > 0
        and report["stages"].get("legacy_import_copy_only", {}).get("conflicts") == 0
        and (
            report["stages"].get("recent_30_day_token_estimate", {}).get("status")
                in {"counted", "no_recent_evidence"}
            or report["stages"].get("recent_30_day_token_estimate", {}).get(
                "estimated_payload_tokens_upper_bound") is not None
        )
        and report["stages"].get("embedding_warmup_and_backfill", {}).get("estimated_backfill_seconds_remaining") is not None
    ) else "incomplete"
    report["credentials_recorded"] = False
    output = artifact_dir / "F2-C-lifecycle-rehearsal.json"
    report["artifact_path"] = str(output)
    _checkpoint(artifact_dir, report, "final_checks")
    _set_stage(root, "cleanup")
    _cleanup_sensitive_run_artifacts(root)
    _write_json(output, report)
    (artifact_dir / "F2-C-lifecycle-rehearsal.partial.json").unlink(missing_ok=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-root", type=Path, required=True,
                        help="new isolated temporary root outside the Atlas checkout and production data")
    parser.add_argument("--artifact-dir", type=Path,
                        default=ATLAS_ROOT / "docs" / "plan" / "MEMORY-V1" / "eval")
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--memoryos-db", type=Path, default=DEFAULT_MEMORYOS_DB)
    parser.add_argument("--settings-source", type=Path,
                        default=ATLAS_ROOT / "data" / "user-settings.json")
    parser.add_argument("--atlas-python", type=Path, default=DEFAULT_ATLAS_PYTHON)
    parser.add_argument("--memoryos-python", type=Path, default=DEFAULT_MEMORYOS_PYTHON)
    parser.add_argument("--memoryos-root", type=Path, default=DEFAULT_MEMORYOS_ROOT)
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(run_full_rehearsal(
            run_root=args.run_root, artifact_dir=args.artifact_dir,
            atlas_db=args.atlas_db, memoryos_db=args.memoryos_db,
            settings_source=args.settings_source, atlas_python=args.atlas_python,
            memoryos_python=args.memoryos_python, memoryos_root=args.memoryos_root,
        ))
    except Exception as exc:  # redact all exception messages from the CLI surface
        failed_stage = "unknown"
        partial: dict[str, Any] = {}
        try:
            root = assert_run_root_isolated(args.run_root)
            stage_file = root / ".f2c-stage"
            if stage_file.is_file():
                failed_stage = stage_file.read_text(encoding="ascii")[:64]
            partial_path = args.artifact_dir / "F2-C-lifecycle-rehearsal.partial.json"
            if partial_path.is_file():
                try:
                    candidate = json.loads(partial_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    candidate = None
                if isinstance(candidate, dict):
                    expected_root = str(_resolved(args.run_root))
                    candidate_root = (candidate.get("isolated_roots") or {}).get("run_root")
                    if candidate_root == expected_root:
                        partial = candidate
            _cleanup_sensitive_run_artifacts(root)
        except (OSError, RehearsalError):
            pass
        hashes_before = partial.get("source_hashes_before")
        hashes_after = None
        if isinstance(hashes_before, dict):
            try:
                hashes_after = _source_hashes(
                    atlas_db=args.atlas_db, memoryos_db=args.memoryos_db,
                    settings_source=args.settings_source,
                )
            except (OSError, RehearsalError):
                hashes_after = None
        modified = _source_files_modified(hashes_before, hashes_after)
        source_unchanged = (
            hashes_before == hashes_after
            if isinstance(hashes_before, dict) and isinstance(hashes_after, dict)
            else None
        )
        result = partial or {
            "schema_version": 1,
            "production_write_allowed": False,
            "production_write_attempted_by_script": False,
            "production_files_modified_by_script": False,
            "credentials_recorded": False,
            "source_paths": {"atlas_db": str(_resolved(args.atlas_db)),
                             "memoryos_db": str(_resolved(args.memoryos_db)),
                             "settings_source": str(_resolved(args.settings_source)),
                             "atlas_config_source": str(_resolved(DEFAULT_ATLAS_CONFIG))},
            "isolated_roots": {"run_root": str(_resolved(args.run_root))},
            "stages": {},
        }
        result.update({
            "status": "blocked",
            "error_type": type(exc).__name__,
            "failed_stage": failed_stage,
            "detail": "A rehearsal stage failed; raw exception text and process logs are not copied to this artifact.",
            "production_write_allowed": False,
            "production_write_attempted_by_script": False,
            "production_files_modified": modified,
            "production_files_modified_by_script": False,
            "production_file_change_attribution": (
                "external_or_concurrent_writer" if modified is True
                else "none_observed" if modified is False else "unknown"
            ),
            "source_hashes_unchanged": source_unchanged,
            "source_hashes_after": hashes_after,
            "credentials_recorded": False,
            "artifact_path": str(args.artifact_dir / "F2-C-lifecycle-rehearsal.json"),
        })
        if isinstance(result.get("stages"), dict):
            result["stages"].setdefault("failure", {"failed_stage": failed_stage,
                                                       "error_type": type(exc).__name__})
        _write_json(args.artifact_dir / "F2-C-lifecycle-rehearsal.json", result)

    print(json.dumps({
        "status": result.get("status"),
        "production_write_allowed": result.get("production_write_allowed"),
        "production_files_modified": result.get("production_files_modified"),
        "source_hashes_unchanged": result.get("source_hashes_unchanged"),
        "credentials_recorded": result.get("credentials_recorded"),
        "recent_30_day_evidence": result.get("stages", {}).get("production_snapshot_stats", {})
            .get("memoryos", {}).get("evidence_events", {}).get("recent_30_day_count"),
        "token_estimate_status": result.get("stages", {}).get("recent_30_day_token_estimate", {}).get("status"),
        "legacy_rows": result.get("stages", {}).get("legacy_export", {}).get("total_rows"),
        "chat_status": result.get("stages", {}).get("enable_and_real_chat", {}).get("chat", {}).get("status"),
        "restart_auto_start": result.get("stages", {}).get("restart", {}).get("memoryos_auto_started_again"),
        "rollback_listener_absent": result.get("stages", {}).get("rollback", {}).get("memoryos_listener_absent"),
        "artifact_path": str(args.artifact_dir / "F2-C-lifecycle-rehearsal.json"),
    }, ensure_ascii=False))
    return 0 if result.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
