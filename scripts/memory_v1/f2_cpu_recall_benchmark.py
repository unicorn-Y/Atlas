#!/usr/bin/env python3
"""Non-blocking CPU-only 10k MemoryOS recall latency benchmark on synthetic fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ATLAS_ROOT = Path(__file__).resolve().parents[2]
MEMORYOS_ROOT = Path(r"D:\MemoryOS")
SERVICE_ROOT = MEMORYOS_ROOT / "service"
DEFAULT_SERVICE_PYTHON = SERVICE_ROOT / ".venv" / "Scripts" / "python.exe"
PROTECTED_ROOTS = (ATLAS_ROOT, MEMORYOS_ROOT, Path(r"D:\MemoryOSData"))
MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
FIXTURE_COUNT = 10_000
DEFAULT_SAMPLES = 100
CONTEXT_TEMPLATE = {
    "owner_id": "owner-local",
    "memory_subject_id": "",
    "client_id": "atlas-desktop",
    "actor_id": "atlas-main",
    "runtime_session_id": "f2-cpu-benchmark",
    "task_id": None,
    "project_id": None,
    "environment_id": "isolated-f2-cpu-performance-fixture",
    "model_deployment_id": None,
}


class BenchmarkError(RuntimeError):
    pass


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def assert_isolated_run_dir(run_dir: Path) -> Path:
    resolved = _resolved(run_dir)
    for protected in PROTECTED_ROOTS:
        root = _resolved(protected)
        if resolved == root or _is_relative_to(resolved, root):
            raise BenchmarkError("run directory overlaps a protected checkout or data root")
    if resolved.exists():
        raise BenchmarkError("run directory already exists")
    return resolved


def _fixture_row(index: int, subject: str, now: str) -> tuple[Any, ...]:
    code = f"{index + 1:05d}"
    title = f"Synthetic F2 CPU performance fixture {code}"
    summary = f"Generated retrieval benchmark record {code}; category {(index % 32):02d}."
    why_valid = f"Performance-only synthetic fixture {code}; no user or production content."
    extra = {"unified": {"facet": "FACT", "content": {"text": summary, "value": summary}}}
    return (
        f"f2-cpu-perf-{code}", "0.1", "owner-local", subject, "MEMORY", 1, "ACTIVE",
        "f2-cpu-performance-fixture", "[]", now, title, "FACT", now, now,
        None, None, None, "[]", summary, why_valid,
        json.dumps(extra, ensure_ascii=False), None, None,
    )


def build_fixture_rows(count: int, subject: str, now: str) -> list[tuple[Any, ...]]:
    if count != FIXTURE_COUNT:
        raise ValueError("the F2 CPU benchmark fixture must contain exactly 10000 records")
    return [_fixture_row(index, subject, now) for index in range(count)]


def fixture_query(index: int) -> str:
    code = f"{index % FIXTURE_COUNT + 1:05d}"
    category = index % 32
    return f"Retrieve generated performance benchmark fixture {code} from category {category:02d}."


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    import math
    position = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return round(ordered[position], 3)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _checkpoint(artifact_dir: Path, report: dict[str, Any], stage: str) -> None:
    report["checkpoint_completed_stage"] = stage
    report["checkpoint_updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(artifact_dir / "F2-B-cpu-recall.partial.json", report)


def _load_service_modules() -> tuple[Any, Any]:
    service = str(SERVICE_ROOT)
    if service not in sys.path:
        sys.path.insert(0, service)
    import embeddings
    import semantic_recall
    return embeddings, semantic_recall


def model_manifest() -> dict[str, Any]:
    os.environ["MEMORYOS_EMBEDDING_DEVICE"] = "cpu"
    os.environ["MEMORYOS_EMBEDDING_MODEL"] = MODEL_ID
    os.environ["MEMORYOS_EMBEDDING_ALLOW_DOWNLOAD"] = "0"
    embeddings, _ = _load_service_modules()
    snapshot_value = embeddings._cached_model_path()
    if not snapshot_value:
        raise BenchmarkError("local Qwen model snapshot is not available")
    snapshot = Path(snapshot_value).resolve()
    patterns = ("config.json", "*.safetensors", "*.safetensors.index.json", "tokenizer.json",
                "tokenizer_config.json", "vocab.json", "merges.txt", "special_tokens_map.json",
                "sentencepiece.bpe.model")
    files = sorted({item for pattern in patterns for item in snapshot.glob(pattern) if item.is_file()})
    weights = [item for item in files if item.name.endswith((".safetensors", ".bin"))]
    if not weights:
        raise BenchmarkError("local Qwen model weight files are not available")
    manifest = hashlib.sha256()
    total_bytes = 0
    for item in files:
        digest = hashlib.sha256()
        with item.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
        file_hash = digest.hexdigest()
        size = item.stat().st_size
        total_bytes += size
        manifest.update(item.relative_to(snapshot).as_posix().encode("utf-8"))
        manifest.update(str(size).encode("ascii"))
        manifest.update(file_hash.encode("ascii"))
    return {
        "model_id": embeddings.model_id(),
        "snapshot_path": str(snapshot),
        "manifest_sha256": manifest.hexdigest(),
        "file_count": len(files),
        "total_bytes": total_bytes,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _service_environment(run_dir: Path, db_path: Path, subject: str,
                         token: str) -> dict[str, str]:
    inherited_allowlist = {
        "PATH", "SYSTEMROOT", "WINDIR", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "COMSPEC", "HF_HOME",
        "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in inherited_allowlist}
    env.update({
        "MEMORYOS_DATA_ROOT": str(run_dir / "service-data"),
        "MEMORYOS_DB_PATH": str(db_path),
        "MEMORYOS_MEMORY_SUBJECT_ID": subject,
        "MEMORYOS_INTERNAL_TOKEN": token,
        "MEMORYOS_SEMANTIC_RECALL_ENABLED": "1",
        "MEMORYOS_EMBEDDING_MODEL": MODEL_ID,
        "MEMORYOS_EMBEDDING_DEVICE": "cpu",
        "MEMORYOS_EMBEDDING_ALLOW_DOWNLOAD": "0",
        "MEMORYOS_FORMATION_WORKER": "0",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def _safe_status(semantic: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": str(semantic.get("state") or "UNKNOWN"),
        "device": str(semantic.get("device") or "UNKNOWN"),
        "model_id": str(semantic.get("model_id") or "UNKNOWN"),
        "pending_count": int(semantic.get("pending_count") or 0),
        "error_present": bool(semantic.get("error")),
    }


def _index_counts(db_path: Path, subject: str, model_id: str,
                  semantic_recall: Any) -> dict[str, Any]:
    import sqlite3

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        active = int(conn.execute(
            "SELECT COUNT(*) FROM memories WHERE memory_subject_id=? "
            "AND record_type='MEMORY' AND status='ACTIVE'", (subject,),
        ).fetchone()[0])
        ready = int(conn.execute(
            "SELECT COUNT(*) FROM memories m JOIN memory_embeddings e "
            "ON e.record_id=m.id AND e.memory_subject_id=m.memory_subject_id "
            "AND e.record_type='MEMORY' AND e.embedding_model_id=? "
            "WHERE m.memory_subject_id=? AND m.record_type='MEMORY' AND m.status='ACTIVE' "
            "AND e.status='READY'",
            (model_id, subject),
        ).fetchone()[0])
        pending = int(conn.execute(
            "SELECT COUNT(*) FROM memory_embeddings WHERE memory_subject_id=? "
            "AND record_type='MEMORY' AND embedding_model_id=? AND status='PENDING'",
            (subject, model_id),
        ).fetchone()[0])
        native = semantic_recall.has_native_index(conn)
        native_rows = None
        if native:
            native_rows = int(conn.execute(
                "SELECT COUNT(*) FROM memory_embeddings_vec WHERE memory_subject_id=?", (subject,)
            ).fetchone()[0])
        return {
            "active_memories": active,
            "ready_embeddings": ready,
            "pending_embeddings": pending,
            "native_vector_index_available": bool(native),
            "native_vector_rows": native_rows,
        }
    finally:
        conn.close()


def _verify_content_hashes(db_path: Path, subject: str, model_id: str,
                           semantic_recall: Any) -> int:
    import sqlite3

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT m.title,m.summary,m.why_valid,e.status,e.content_hash,e.embedding_model_id "
            "FROM memories m JOIN memory_embeddings e ON e.record_id=m.id "
            "AND e.memory_subject_id=m.memory_subject_id AND e.record_type='MEMORY' "
            "WHERE m.memory_subject_id=? AND m.record_type='MEMORY' AND m.status='ACTIVE'",
            (subject,),
        ).fetchall()
        valid = 0
        for row in rows:
            text = semantic_recall.memory_text(dict(row))
            if (row["status"] == "READY" and row["embedding_model_id"] == model_id
                    and row["content_hash"] == semantic_recall.content_hash(text)):
                valid += 1
        return valid
    finally:
        conn.close()


def _seed_fixture(db_path: Path, subject: str, count: int,
                  semantic_recall: Any) -> dict[str, int]:
    import sqlite3
    from datetime import datetime

    rows = build_fixture_rows(count, subject, datetime.now(timezone.utc).isoformat())
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "INSERT INTO memories (id,schema_version,owner_id,memory_subject_id,record_type,"
            "revision,status,origin,source_refs_json,recorded_at,title,memory_type,created_at,"
            "updated_at,valid_from,valid_to,project_id,related_episode_ids_json,summary,why_valid,"
            "extra_json,supersedes_id,superseded_by_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        queued = semantic_recall.enqueue_missing_embeddings(conn, subject)
        conn.commit()
        return {"fixture_records_inserted": len(rows), "embedding_jobs_queued": int(queued)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _stop_service(process: subprocess.Popen[Any], port: int) -> dict[str, Any]:
    if process.poll() is None and os.name == "nt":
        try:
            process.send_signal(getattr(signal, "CTRL_BREAK_EVENT"))
        except (OSError, ValueError):
            process.terminate()
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)
    return {"service_exit_code": process.returncode, "listener_after_cleanup": _port_listening(port)}


def run_benchmark(*, run_dir: Path, artifact_dir: Path, service_python: Path,
                  startup_timeout: float, index_timeout: float, samples: int) -> dict[str, Any]:
    run_root = assert_isolated_run_dir(run_dir)
    if samples < 20:
        raise BenchmarkError("at least 20 recall samples are required for a stable p95")
    if _resolved(Path(sys.executable)) != _resolved(service_python):
        raise BenchmarkError("run this benchmark with the MemoryOS service virtualenv Python")
    run_root.mkdir(parents=True, exist_ok=False)
    os.environ["MEMORYOS_EMBEDDING_DEVICE"] = "cpu"
    os.environ["MEMORYOS_EMBEDDING_MODEL"] = MODEL_ID
    os.environ["MEMORYOS_EMBEDDING_ALLOW_DOWNLOAD"] = "0"
    _, semantic_recall = _load_service_modules()
    manifest = model_manifest()
    subject = "f2-cpu-" + uuid.uuid4().hex[:12]
    token = secrets.token_urlsafe(32)
    port = _free_port()
    db_path = run_root / "service-data" / "db" / "memoryos.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = run_root / "memoryos-service.log"
    env = _service_environment(run_root, db_path, subject, token)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / ("F2-B-cpu-recall-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_data_read": False,
        "production_data_written": False,
        "isolated_run_root": str(run_root),
        "isolated_database_path": str(db_path),
        "synthetic_fixture_only": True,
        "fixture_is_efficacy_evidence": False,
        "fixture_count_target": FIXTURE_COUNT,
        "requested_embedding_device": "cpu",
        "allow_download": False,
        "model": manifest,
        "sample_count_target": samples,
        "stages": {},
        "artifact_path": str(artifact_path),
    }
    _checkpoint(artifact_dir, report, "model_manifest")
    process: subprocess.Popen[Any] | None = None
    service_url = f"http://127.0.0.1:{port}"
    server_cleanup: dict[str, Any] | None = None
    failed_stage = "service_startup"
    try:
        import httpx

        with log_path.open("wb") as log_handle:
            process = subprocess.Popen(
                [str(service_python), "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
                 "--port", str(port), "--log-level", "warning"],
                cwd=str(SERVICE_ROOT), env=env, stdin=subprocess.DEVNULL,
                stdout=log_handle, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        started = time.perf_counter()
        deadline = time.monotonic() + startup_timeout
        health_ok = False
        with httpx.Client(timeout=10) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise BenchmarkError("isolated MemoryOS service exited during startup")
                try:
                    response = client.get(service_url + "/v1/health")
                    if response.status_code == 200:
                        health_ok = True
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
            if not health_ok:
                raise BenchmarkError("isolated MemoryOS health endpoint timed out")
            report["stages"]["service_health"] = {
                "status_code": response.status_code,
                "startup_health_seconds": round(time.perf_counter() - started, 3),
                "service_pid": process.pid,
                "loopback_only": True,
            }
            _checkpoint(artifact_dir, report, "service_health")

            headers = {"Authorization": "Bearer " + token}
            warm_started = time.perf_counter()
            semantic_status: dict[str, Any] = {"state": "UNKNOWN"}
            while time.monotonic() - warm_started < startup_timeout:
                response = client.get(service_url + "/v1/unified/status", headers=headers)
                if response.status_code != 200:
                    time.sleep(1)
                    continue
                raw = response.json().get("semantic") or {}
                semantic_status = _safe_status(raw)
                if semantic_status["state"] == "ERROR":
                    raise BenchmarkError("local CPU Qwen semantic worker failed to warm up")
                if semantic_status["state"] == "READY":
                    break
                time.sleep(1)
            else:
                raise BenchmarkError("local CPU Qwen semantic worker warmup timed out")
            if semantic_status.get("device") != "cpu" or semantic_status.get("model_id") != MODEL_ID:
                raise BenchmarkError("semantic worker did not report the required CPU Qwen model")
            report["stages"]["embedding_warmup"] = {
                "elapsed_seconds": round(time.monotonic() - warm_started, 3),
                "semantic_status": semantic_status,
                "confirmed_cpu": True,
                "model_manifest_sha256": manifest["manifest_sha256"],
            }
            _checkpoint(artifact_dir, report, "embedding_warmup")

            failed_stage = "fixture_seed"
            seed_started = time.perf_counter()
            seed_result = _seed_fixture(db_path, subject, FIXTURE_COUNT, semantic_recall)
            report["stages"]["fixture_seed"] = {
                **seed_result,
                "elapsed_seconds": round(time.perf_counter() - seed_started, 3),
                "record_content": "synthetic-only",
                "efficacy_evidence": False,
            }
            _checkpoint(artifact_dir, report, "fixture_seed")

            failed_stage = "real_embedding_backfill"
            indexing_started = time.perf_counter()
            latest_counts: dict[str, Any] = {}
            last_checkpoint = 0.0
            while time.monotonic() - indexing_started < index_timeout:
                latest_counts = _index_counts(db_path, subject, MODEL_ID, semantic_recall)
                if (latest_counts["active_memories"] == FIXTURE_COUNT
                        and latest_counts["ready_embeddings"] == FIXTURE_COUNT
                        and latest_counts["pending_embeddings"] == 0
                ):
                    break
                if latest_counts["active_memories"] > FIXTURE_COUNT:
                    raise BenchmarkError("isolated fixture database exceeded the 10000-record target")
                now = time.monotonic()
                if now - last_checkpoint >= 15:
                    report["stages"]["real_embedding_backfill_progress"] = latest_counts
                    report["stages"]["real_embedding_backfill_progress"]["elapsed_seconds"] = round(now - indexing_started, 1)
                    _checkpoint(artifact_dir, report, "real_embedding_backfill_progress")
                    last_checkpoint = now
                time.sleep(1)
            else:
                report["stages"]["real_embedding_backfill"] = {
                    "status": "timeout",
                    "elapsed_seconds": round(time.monotonic() - indexing_started, 3),
                    "index_counts": latest_counts,
                }
                raise BenchmarkError("10k local Qwen CPU backfill did not reach complete indexing")
            exact_ready = _verify_content_hashes(db_path, subject, MODEL_ID, semantic_recall)
            if (exact_ready != FIXTURE_COUNT
                    or not latest_counts["native_vector_index_available"]
                    or latest_counts["native_vector_rows"] != FIXTURE_COUNT):
                report["stages"]["real_embedding_backfill"] = {
                    "status": "incomplete",
                    "elapsed_seconds": round(time.monotonic() - indexing_started, 3),
                    "index_counts": latest_counts,
                    "content_hash_matched_ready_embeddings": exact_ready,
                }
                raise BenchmarkError("10k ready Qwen vectors or native index verification failed")
            report["stages"]["real_embedding_backfill"] = {
                "status": "completed",
                "elapsed_seconds": round(time.monotonic() - indexing_started, 3),
                "index_counts": latest_counts,
                "content_hash_matched_ready_embeddings": exact_ready,
                "actual_local_model_embeddings": True,
                "model_id": MODEL_ID,
                "device": "cpu",
            }
            _checkpoint(artifact_dir, report, "real_embedding_backfill")

            failed_stage = "real_recall_latency"
            latency_samples: list[dict[str, Any]] = []
            for index in range(samples):
                body = {
                    "context": {**CONTEXT_TEMPLATE, "memory_subject_id": subject,
                                "runtime_session_id": f"f2-cpu-latency-{index + 1:04d}"},
                    "query": fixture_query(index * 97),
                }
                request_started = time.perf_counter()
                response = client.post(service_url + "/v1/unified/recall", headers=headers,
                                       json=body, timeout=120)
                elapsed_ms = (time.perf_counter() - request_started) * 1000
                if response.status_code != 200:
                    raise BenchmarkError("isolated recall request failed")
                payload = response.json()
                semantic_state = ((payload.get("completeness") or {}).get("channels") or {}).get(
                    "semantic_state", "UNKNOWN")
                latency_samples.append({
                    "sample": index + 1,
                    "http_status": response.status_code,
                    "elapsed_ms": round(elapsed_ms, 3),
                    "context_item_count": len(payload.get("context_items") or []),
                    "semantic_state": semantic_state,
                })
            latency_values = [row["elapsed_ms"] for row in latency_samples]
            semantic_ready_samples = sum(row["semantic_state"] == "READY" for row in latency_samples)
            report["stages"]["real_recall_latency"] = {
                "status": "completed" if semantic_ready_samples == samples else "incomplete",
                "sample_count": samples,
                "semantic_ready_sample_count": semantic_ready_samples,
                "http_recall_ms": {
                    "p50": percentile(latency_values, 0.50),
                    "p95": percentile(latency_values, 0.95),
                    "max": round(max(latency_values), 3),
                    "samples_ms": latency_values,
                },
                "sample_details": latency_samples,
                "is_performance_only": True,
                "p95_is_non_blocking": True,
            }
            _checkpoint(artifact_dir, report, "real_recall_latency")
            report["status"] = "completed_nonblocking" if semantic_ready_samples == samples else "incomplete"
    except Exception as exc:
        report["status"] = "blocked"
        report["error_type"] = type(exc).__name__
        report["failed_stage"] = failed_stage
        report["detail"] = "CPU benchmark stopped; raw exception text and service log are omitted."
        raise
    finally:
        server_cleanup = _stop_service(process, port) if process is not None else {
            "service_exit_code": None, "listener_after_cleanup": _port_listening(port),
        }
        report["server_cleanup"] = server_cleanup
        report["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["failed_stage"] = None if report.get("status") == "completed_nonblocking" else failed_stage
        report["production_data_written"] = False
        report["service_log_retained"] = False
        log_path.unlink(missing_ok=True)
        _checkpoint(artifact_dir, report, "server_cleanup")

    clean = bool(server_cleanup and server_cleanup["service_exit_code"] is not None
                 and not server_cleanup["listener_after_cleanup"])
    report["server_cleanup_passed"] = clean
    if report.get("status") == "completed_nonblocking" and not clean:
        report["status"] = "incomplete"
        report["failed_stage"] = "server_cleanup"
    _write_json(artifact_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True,
                        help="new isolated run directory outside both checkouts and production data")
    parser.add_argument("--artifact-dir", type=Path,
                        default=ATLAS_ROOT / "docs" / "plan" / "MEMORY-V1" / "eval")
    parser.add_argument("--service-python", type=Path, default=DEFAULT_SERVICE_PYTHON)
    parser.add_argument("--startup-timeout", type=float, default=900)
    parser.add_argument("--index-timeout", type=float, default=21600)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    args = parser.parse_args(argv)
    result: dict[str, Any]
    artifact_dir = args.artifact_dir
    try:
        result = run_benchmark(
            run_dir=args.run_dir, artifact_dir=artifact_dir,
            service_python=args.service_python, startup_timeout=args.startup_timeout,
            index_timeout=args.index_timeout, samples=args.samples,
        )
    except Exception as exc:
        partial: dict[str, Any] = {}
        partial_path = artifact_dir / "F2-B-cpu-recall.partial.json"
        try:
            candidate = json.loads(partial_path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict) and candidate.get("isolated_run_root") == str(_resolved(args.run_dir)):
                partial = candidate
        except (OSError, ValueError):
            pass
        result = partial or {
            "schema_version": 1,
            "isolated_run_root": str(_resolved(args.run_dir)),
            "production_data_read": False,
            "production_data_written": False,
            "synthetic_fixture_only": True,
            "fixture_is_efficacy_evidence": False,
            "stages": {},
        }
        result.update({
            "status": "blocked",
            "error_type": type(exc).__name__,
            "production_data_written": False,
            "failed_stage": result.get("failed_stage", result.get("checkpoint_completed_stage", "preflight")),
            "detail": "CPU benchmark preparation/execution stopped; raw exception and service log omitted.",
        })
        _write_json(artifact_dir / "F2-B-cpu-recall-blocked.json", result)
    print(json.dumps({
        "status": result.get("status"),
        "fixture_count": result.get("fixture_count_target"),
        "device": result.get("stages", {}).get("embedding_warmup", {}).get("semantic_status", {}).get("device"),
        "model_manifest_sha256": result.get("model", {}).get("manifest_sha256"),
        "recall_p95_ms": result.get("stages", {}).get("real_recall_latency", {}).get("http_recall_ms", {}).get("p95"),
        "artifact_path": result.get("artifact_path"),
        "production_data_written": result.get("production_data_written"),
    }, ensure_ascii=False))
    return 0 if result.get("status") == "completed_nonblocking" else 2


if __name__ == "__main__":
    raise SystemExit(main())
