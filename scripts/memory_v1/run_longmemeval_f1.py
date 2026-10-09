#!/usr/bin/env python3
"""F1-D LongMemEval runner using Atlas Observer, MemoryOS HTTP and run_phases.

Dry-run is the default. A live run requires ``--run-real``, an explicitly
coordinated MemoryOS port, and an isolated Observer daily-token budget large
enough for the selected fixed histories. The full 120-question mode is guarded
by ``--full-evaluation`` and is never started implicitly.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from .gemini_runtime import (
        MODEL_ID as F1_MODEL_ID,
        PROVIDER_ID as F1_PROVIDER_ID,
        bootstrap_model_manager,
        clear_gateway_fallback_config,
        clear_inherited_gateway_credentials,
        read_isolated_model_settings,
        write_isolated_user_settings,
    )
except ImportError:  # direct script invocation
    from gemini_runtime import (
        MODEL_ID as F1_MODEL_ID,
        PROVIDER_ID as F1_PROVIDER_ID,
        bootstrap_model_manager,
        clear_gateway_fallback_config,
        clear_inherited_gateway_credentials,
        read_isolated_model_settings,
        write_isolated_user_settings,
    )

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
CANONICAL_CATEGORIES = (
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
)
EXPECTED_S_SHA256 = "08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894"
EXPECTED_OFFICIAL_COMMIT = "9e0b455f4ef0e2ab8f2e582289761153549043fc"
EXPECTED_EVALUATOR_BLOB = "4732f3772b04a2b9069121ade304e6320494abc2"
OFFICIAL_ORIGIN = "https://github.com/xiaowu0162/LongMemEval.git"
OBSERVER_INPUT_OVERHEAD_TOKEN_UPPER = 4_096
OBSERVER_MAX_OUTPUT_TOKENS = 4_000
DEFAULT_SOURCE = Path(r"D:\Temp\F1-D-longmemeval-data-2ec2a55\longmemeval_s")
DEFAULT_SUBSET = ROOT / "docs/plan/MEMORY-V1/eval/longmemeval_subset.json"
DEFAULT_VALIDATION = ROOT / "docs/plan/MEMORY-V1/eval/F1-D-source-validation.json"
DEFAULT_OFFICIAL_ROOT = Path(
    r"D:\Temp\F1-D-official-longmemeval-9e0b455"
)
PRODUCTION_CONFIG = ROOT / "config/atlas.toml"
PRODUCTION_SETTINGS = Path(r"D:\Atlas\data\user-settings.json")
TEMP_ROOT = Path(r"D:\Temp")
MAX_SERVICE_PORT = 65535
QUESTION_HERMES_AUX_TIMEOUT_SECONDS = 120
PRODUCTION_DATA_ROOTS = (
    Path(r"D:\Atlas\data").resolve(),
    Path(r"D:\MemoryOSData").resolve(),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_source_datetime(value: str) -> datetime:
    """Normalize LongMemEval's timezone-free wall clock into the benchmark UTC frame."""
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+\([A-Za-z]{3}\)\s+(\d{1,2}):(\d{2})", text)
    if match:
        year, month, day, hour, minute = (int(part) for part in match.groups())
        value_dt = datetime(year, month, day, hour, minute, tzinfo=UTC)
        return value_dt
    try:
        value_dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unsupported LongMemEval source datetime format: {text!r}") from exc
    return value_dt.replace(tzinfo=UTC) if value_dt.tzinfo is None else value_dt.astimezone(UTC)


def select_questions(
    subset_rows: list[dict[str, Any]],
    canonical_by_id: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Select only fixed qids, binding each to its full canonical LongMemEval_S row."""
    ids = [str(row.get("question_id") or "") for row in subset_rows]
    if len(ids) != 120 or len(set(ids)) != 120:
        raise ValueError("the fixed subset must contain 120 unique question IDs")
    subset_by_category: dict[str, list[dict[str, Any]]] = {category: [] for category in CANONICAL_CATEGORIES}
    for row in subset_rows:
        category = str(row.get("question_type") or "")
        if category not in subset_by_category:
            raise ValueError(f"unknown fixed subset category: {category}")
        subset_by_category[category].append(row)
    if any(len(rows) != 20 for rows in subset_by_category.values()):
        raise ValueError("the fixed subset must contain exactly 20 questions in each category")

    if limit == 1:
        requested = [subset_rows[0]]
    elif limit == 12:
        requested = [row for category in CANONICAL_CATEGORIES for row in subset_by_category[category][:2]]
    elif limit == 120:
        requested = list(subset_rows)
    else:
        raise ValueError("limit must be 1, 12, or 120")

    selected: list[dict[str, Any]] = []
    for fixed in requested:
        qid = str(fixed["question_id"])
        source = canonical_by_id.get(qid)
        if source is None:
            raise ValueError(f"fixed question ID is absent from canonical S: {qid}")
        if fixed.get("question_type") != source.get("question_type") or fixed.get("question") != source.get("question"):
            raise ValueError(f"fixed question category/text is incompatible with canonical S: {qid}")
        if "answer" in fixed and fixed.get("answer") != source.get("answer"):
            raise ValueError(f"fixed question gold answer differs from canonical S: {qid}")
        selected.append(source)
    return selected


def _checked_child(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise RuntimeError(f"refusing non-child artifact path: {resolved}")
    if resolved == PRODUCTION_DATA_ROOTS[0] or resolved == PRODUCTION_DATA_ROOTS[1]:
        raise RuntimeError(f"refusing production data path: {resolved}")
    if any(prod in resolved.parents for prod in PRODUCTION_DATA_ROOTS):
        raise RuntimeError(f"refusing path under production data root: {resolved}")
    return resolved


def _write_question_hermes_config(hermes_home: Path) -> Path:
    """Pin auxiliary timeouts and disable provider fallbacks for one isolated question."""
    hermes_home = _checked_child(hermes_home, TEMP_ROOT)
    hermes_home.mkdir(parents=True, exist_ok=True)
    config_path = hermes_home / "config.yaml"
    if config_path.exists():
        raise FileExistsError(f"refusing to overwrite question-isolated Hermes config: {config_path}")
    timeout = QUESTION_HERMES_AUX_TIMEOUT_SECONDS
    config_path.write_text(
        "fallback_providers: []\n"
        "fallback_model: []\n"
        "auxiliary:\n"
        "  memory_observe:\n"
        f"    timeout: {timeout}\n"
        "    fallback_chain: []\n"
        "  memory_reflect:\n"
        f"    timeout: {timeout}\n"
        "    fallback_chain: []\n",
        encoding="utf-8",
    )
    return config_path


class _RouteInfoTrace(dict[str, str]):
    """Record each Hermes route lane using only its public provider/model labels."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts: list[dict[str, str]] = []
        self._provider = ""

    def __setitem__(self, key: str, value: str) -> None:
        super().__setitem__(key, value)
        if key == "provider":
            self._provider = str(value)
        elif key == "model":
            self.attempts.append({"provider": self._provider, "model": str(value)})


def _safe_route_attempts(trace: _RouteInfoTrace, model_route: dict[str, Any]) -> list[dict[str, Any]]:
    expected_provider = str(model_route.get("provider_id") or "")
    expected_model = str(model_route.get("model_id") or "")
    endpoint_host = str(model_route.get("provider_endpoint_host") or "")
    return [
        {
            "provider": attempt["provider"],
            "model": attempt["model"],
            "endpoint_host": endpoint_host if (
                attempt["provider"] == expected_provider and attempt["model"] == expected_model
            ) else None,
        }
        for attempt in trace.attempts
    ]


def _verify_question_hermes_config(config_path: Path) -> dict[str, Any]:
    """Confirm Hermes resolves the question-local file and effective fallback/timeout policy."""
    from agent.auxiliary_client import _effective_aux_timeout, _get_auxiliary_task_config
    from hermes_cli.config import get_config_path, load_config_readonly
    from hermes_cli.fallback_config import get_fallback_chain

    resolved_path = Path(get_config_path()).resolve()
    if resolved_path != config_path.resolve():
        raise RuntimeError("Hermes did not resolve the question-isolated HERMES_HOME config")
    config = load_config_readonly()
    timeout = QUESTION_HERMES_AUX_TIMEOUT_SECONDS
    for task in ("memory_observe", "memory_reflect"):
        if _effective_aux_timeout(task, None) != timeout:
            raise RuntimeError(f"Hermes {task} timeout does not match the isolated {timeout}s policy")
        if _get_auxiliary_task_config(task).get("fallback_chain") != []:
            raise RuntimeError(f"Hermes {task} fallback chain is not empty")
    if get_fallback_chain(config) != [] or config.get("fallback_model") != []:
        raise RuntimeError("Hermes global fallback chain is not empty")
    return {
        "config_path": str(config_path),
        "config_sha256": sha256_file(config_path),
        "auxiliary_timeouts_seconds": {
            "memory_observe": timeout,
            "memory_reflect": timeout,
        },
        "auxiliary_fallback_chains_empty": True,
        "global_fallback_chain_empty": True,
    }


def _assert_file_hash(path: Path, expected: str, description: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{description} SHA256 mismatch: expected {expected}, got {actual}")
    return actual


def verify_official_evaluator(repo: Path) -> tuple[Path, str, str]:
    if not (repo / ".git").exists():
        raise FileNotFoundError(f"pinned official LongMemEval checkout not found: {repo}")
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    origin = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        check=True, capture_output=True, text=True,
    ).stdout.strip().rstrip("/")
    expected_origin = OFFICIAL_ORIGIN.rstrip("/")
    if origin.lower() != expected_origin.lower():
        raise RuntimeError(f"official repository origin mismatch: expected {OFFICIAL_ORIGIN}, got {origin}")
    blob = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"HEAD:src/evaluation/evaluate_qa.py"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if commit != EXPECTED_OFFICIAL_COMMIT or blob != EXPECTED_EVALUATOR_BLOB:
        raise RuntimeError(f"official evaluator checkout mismatch: commit={commit}, blob={blob}")
    dirty = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise RuntimeError("official evaluator checkout has local modifications")
    script = repo / "src/evaluation/evaluate_qa.py"
    if not script.is_file():
        raise FileNotFoundError(script)
    return script, commit, blob


def _load_official_module(script: Path):
    spec = importlib.util.spec_from_file_location("longmemeval_official_evaluate_qa", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load official evaluator: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "get_anscheck_prompt", None)):
        raise RuntimeError("pinned evaluator is missing get_anscheck_prompt")
    return module


def _set_isolated_process_env(run_root: Path) -> None:
    cache = run_root / "cache"
    paths = {
        "TEMP": TEMP_ROOT,
        "TMP": TEMP_ROOT,
        "TMPDIR": TEMP_ROOT,
        "ATLAS_ROOT": ROOT,
        "ATLAS_DATA_DIR": run_root / "atlas-data",
        "HERMES_HOME": run_root / "hermes-home",
        "MEMORYOS_DATA_ROOT": run_root / "memoryos-data",
        "MEMORYOS_DB_PATH": run_root / "memoryos-data" / "db" / "memoryos.sqlite3",
        "HF_HOME": cache / "huggingface",
        "HF_HUB_CACHE": cache / "huggingface" / "hub",
        "TRANSFORMERS_CACHE": cache / "huggingface" / "transformers",
        "TORCH_HOME": cache / "torch",
        "TIKTOKEN_CACHE_DIR": cache / "tiktoken",
        "XDG_CACHE_HOME": cache / "xdg",
    }
    for name, value in paths.items():
        os.environ[name] = str(value)
        if name not in {"TEMP", "TMP", "TMPDIR"}:
            Path(value).mkdir(parents=True, exist_ok=True)
    clear_inherited_gateway_credentials()
    os.environ["ATLAS_UNIFIED_EVENT_CLASS"] = "TEST"
    os.environ["MEMORYOS_SEMANTIC_RECALL_ENABLED"] = "1"
    os.environ["MEMORYOS_HYBRID_RECALL_SHADOW"] = "0"
    # Atlas Observer creates DERIVED records through the synchronous /observe API.
    # Do not start MemoryOS's unrelated legacy raw-evidence extraction worker.
    os.environ["MEMORYOS_FORMATION_WORKER"] = "0"
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"


def _configured_budget(config_data: dict[str, Any], explicit: int | None) -> int:
    if explicit is not None:
        if explicit < 1:
            raise ValueError("Observer daily budget override must be positive")
        return explicit
    value = (
        config_data.get("memory", {})
        .get("v1", {})
        .get("observer_daily_token_budget", 50_000)
    )
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 50_000


def _observer_budget_requirement(item: dict[str, Any]) -> int:
    """Conservative per-question reservation cap; model-independent and includes one retry."""
    content = int(item["content_tokens_char_div_3_5"])
    calls = int(item["observer_calls_char_div_3_5"])
    if content < 0 or calls < 0:
        raise ValueError("LongMemEval source token/call estimates cannot be negative")
    return 2 * content + calls * (
        2 * OBSERVER_INPUT_OVERHEAD_TOKEN_UPPER
        + 2 * OBSERVER_MAX_OUTPUT_TOKENS
        + 256
    )


def _observer_budget_estimate(rows: list[dict[str, Any]]) -> int:
    """Maximum per-question Observer reservation needed for isolated subjects."""
    return max((_observer_budget_requirement(item) for item in rows), default=0)


def _load_preflight(
    source: Path,
    subset_path: Path,
    validation_path: Path,
    official_root: Path,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], Path, str, str]:
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if validation.get("status") != "PASSED":
        raise RuntimeError("canonical source validation report is not PASSED")
    if validation.get("source", {}).get("sha256") != EXPECTED_S_SHA256:
        raise RuntimeError("validation report does not pin the required full S SHA256")
    _assert_file_hash(source, EXPECTED_S_SHA256, "LongMemEval_S")
    _assert_file_hash(subset_path, validation["subset"]["sha256"], "fixed 120-question subset")
    data = json.loads(source.read_text(encoding="utf-8"))
    subset = json.loads(subset_path.read_text(encoding="utf-8"))
    by_id = {str(row["question_id"]): row for row in data if isinstance(row, dict) and row.get("question_id")}
    selected = select_questions(subset["questions"], by_id, limit=limit)
    for row in selected:
        sessions = row.get("haystack_sessions")
        session_ids = row.get("haystack_session_ids")
        dates = row.get("haystack_dates")
        if not isinstance(sessions, list) or not isinstance(session_ids, list) or not isinstance(dates, list):
            raise ValueError(f"canonical S has incomplete full-history fields: {row['question_id']}")
        if not (len(sessions) == len(session_ids) == len(dates)):
            raise ValueError(f"full histories, source IDs and dates are misaligned: {row['question_id']}")
        for session in sessions:
            if not isinstance(session, list):
                raise ValueError(f"canonical S session is not a turn array: {row['question_id']}")
            for turn in session:
                if not isinstance(turn, dict) or str(turn.get("role") or "").lower() not in {"user", "assistant"}:
                    raise ValueError(f"unsupported dialogue turn shape/role: {row['question_id']}")
                if not isinstance(turn.get("content"), str):
                    raise ValueError(f"non-string dialogue content: {row['question_id']}")
        parse_source_datetime(str(row.get("question_date") or ""))
        for stamp in dates:
            parse_source_datetime(str(stamp or ""))
    evaluator_script, commit, blob = verify_official_evaluator(official_root)
    return selected, validation, subset, evaluator_script, commit, blob


def _prepare_atlas_config(
    raw_source_config: dict[str, Any],
    settings: dict[str, Any],
    *,
    service_url: str,
    internal_token: str,
    subject_binding: str,
    observer_budget: int,
    outbox_path: Path | None = None,
):
    raw = copy.deepcopy(raw_source_config)
    memory = raw.setdefault("memory", {})
    unified = memory.setdefault("unified", {})
    unified.update({
        "enabled": True,
        "service_url": service_url,
        "internal_token": internal_token,
        "subject_binding": subject_binding,
        "outbox_path": str(outbox_path or (Path(os.environ["ATLAS_DATA_DIR"]) / "outbox" / "unified_outbox.sqlite3")),
    })
    memory.setdefault("v1", {})["observer_daily_token_budget"] = observer_budget

    from atlas import config as atlas_config
    from atlas.config import AtlasConfig

    cfg = AtlasConfig(raw)
    atlas_config._config = cfg
    atlas_config.get_config = lambda: cfg
    atlas_config.load_user_settings = lambda path=None: settings

    import atlas.agent as atlas_agent
    import atlas.memory as atlas_memory
    import atlas.models as atlas_models

    atlas_agent.get_config = lambda: cfg
    atlas_memory.get_config = lambda: cfg
    atlas_models.get_config = lambda: cfg
    atlas_models.load_user_settings = lambda path=None: settings
    try:
        import atlas.models.manager as model_manager_module

        model_manager_module.get_config = lambda: cfg
        model_manager_module.load_user_settings = lambda path=None: settings
    except ImportError:
        pass
    return cfg


def _question_subject_id(question_id: str) -> str:
    return f"f1d-{question_id}"


def _reported_usage(value: Any) -> tuple[int | None, int | None, dict[str, Any]]:
    def take(*names: str) -> int | None:
        for name in names:
            item = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
            if isinstance(item, (int, float)) and item >= 0:
                return int(item)
        return None

    safe = {}
    for key in (
        "input_tokens", "prompt_tokens", "output_tokens", "completion_tokens",
        "total_tokens", "cached_input_tokens", "provider_reported_cost_usd", "cost_usd",
    ):
        item = value.get(key) if isinstance(value, dict) else getattr(value, key, None)
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[key] = item
    return take("input_tokens", "prompt_tokens"), take("output_tokens", "completion_tokens"), safe


def _summarize_latency_ms(values: list[float]) -> dict[str, int | float | None]:
    ordered = sorted(max(0.0, float(value)) for value in values)
    if not ordered:
        return {"count": 0, "total_ms": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    p50_index = (len(ordered) - 1) // 2
    p95_index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return {
        "count": len(ordered),
        "total_ms": round(sum(ordered), 3),
        "mean_ms": round(sum(ordered) / len(ordered), 3),
        "p50_ms": round(ordered[p50_index], 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(ordered[-1], 3),
    }


def _write_jsonl(path: Path, item: dict[str, Any], *, durable: bool = False) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        if durable:
            stream.flush()
            os.fsync(stream.fileno())


def _write_json_checkpoint(path: Path, item: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(item, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _load_resume_results(run_root: Path, selected_question_ids: list[str]) -> dict[str, dict[str, Any]]:
    selected = set(selected_question_ids)
    result_path = run_root / "raw_output.jsonl"
    completed: dict[str, dict[str, Any]] = {}
    if result_path.is_file():
        with result_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"resume journal is malformed at line {line_number}; refusing to re-import any question"
                    ) from exc
                if not isinstance(item, dict) or not str(item.get("question_id") or ""):
                    raise RuntimeError(f"resume journal line {line_number} has no question_id")
                qid = str(item["question_id"])
                if qid not in selected:
                    raise RuntimeError(f"resume journal contains an unselected question {qid}")
                if qid in completed:
                    raise RuntimeError(f"resume journal duplicates completed question {qid}")
                completed[qid] = item

    for qid in selected_question_ids:
        question_root = run_root / f"question-{qid}"
        checkpoint = question_root / "result.json"
        if checkpoint.is_file():
            try:
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"question {qid} result checkpoint is unreadable; refusing re-import") from exc
            if not isinstance(saved, dict) or str(saved.get("question_id") or "") != qid:
                raise RuntimeError(f"question {qid} result checkpoint has the wrong identity")
            journaled = completed.get(qid)
            if journaled is not None and journaled != saved:
                raise RuntimeError(f"question {qid} result checkpoint differs from the root journal")
            if journaled is None:
                _write_jsonl(result_path, saved, durable=True)
                completed[qid] = saved
        elif qid in completed:
            raise RuntimeError(f"question {qid} root journal exists without its durable result checkpoint")
        elif question_root.exists():
            detail = "; failure evidence is preserved" if (question_root / "failure.json").exists() else ""
            raise RuntimeError(
                f"question {qid} has an incomplete runtime root{detail}; refusing to re-import its history"
            )
    return completed


def _load_resume_source_results(
    run_root: Path, selected_question_ids: list[str],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Read completed checkpoints from an older attempt; unfinished IDs get a fresh root."""
    selected = set(selected_question_ids)
    journal: dict[str, dict[str, Any]] = {}
    result_path = run_root / "raw_output.jsonl"
    if result_path.is_file():
        with result_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"prior attempt journal is malformed at line {line_number}") from exc
                if not isinstance(item, dict) or not str(item.get("question_id") or ""):
                    raise RuntimeError(f"prior attempt journal line {line_number} has no question_id")
                qid = str(item["question_id"])
                if qid not in selected:
                    raise RuntimeError(f"prior attempt contains unselected question {qid}")
                if qid in journal:
                    raise RuntimeError(f"prior attempt journal duplicates question {qid}")
                journal[qid] = item

    failed_ids: set[str] = set()
    failure_path = run_root / "failures.jsonl"
    if failure_path.is_file():
        with failure_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"prior failure journal is malformed at line {line_number}") from exc
                if not isinstance(item, dict) or not str(item.get("question_id") or ""):
                    raise RuntimeError(f"prior failure journal line {line_number} has no question_id")
                qid = str(item["question_id"])
                if qid not in selected:
                    raise RuntimeError(f"prior failure journal contains unselected question {qid}")
                if qid in failed_ids:
                    raise RuntimeError(f"prior failure journal duplicates question {qid}")
                failed_ids.add(qid)

    completed: dict[str, dict[str, Any]] = {}
    unfinished: list[str] = []
    for qid in selected_question_ids:
        question_root = run_root / f"question-{qid}"
        checkpoint = question_root / "result.json"
        if checkpoint.is_file():
            try:
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"prior question {qid} result checkpoint is unreadable") from exc
            if not isinstance(saved, dict) or str(saved.get("question_id") or "") != qid:
                raise RuntimeError(f"prior question {qid} result checkpoint has the wrong identity")
            if qid in journal and journal[qid] != saved:
                raise RuntimeError(f"prior question {qid} result checkpoint differs from its journal")
            if qid in failed_ids:
                raise RuntimeError(f"prior question {qid} has both a complete checkpoint and a failure record")
            completed[qid] = saved
        elif qid in journal or qid in failed_ids or question_root.exists():
            unfinished.append(qid)
    return completed, unfinished


def _resume_identity(summary: dict[str, Any]) -> dict[str, Any]:
    configuration = summary.get("read_only_configuration_source", {})
    route = summary.get("model_router", {})
    budget = summary.get("observer_budget_preflight", {})
    return {
        "question_ids": summary.get("selected_question_ids"),
        "source_sha256": summary.get("source_sha256"),
        "subset_sha256": summary.get("subset_sha256"),
        "official_commit": summary.get("official_commit"),
        "official_evaluator_blob": summary.get("official_evaluator_blob"),
        "model_id": route.get("model_id"),
        "observer_model_id": route.get("observer_model_id"),
        "provider_id": route.get("provider_id"),
        "provider_endpoint_host": route.get("provider_endpoint_host"),
        "credential_present": route.get("credential_present"),
        "config_sha256": configuration.get("config_sha256"),
        "settings_sha256": configuration.get("settings_sha256"),
        "isolated_settings_sha256": configuration.get("isolated_settings_sha256"),
        "observer_budget": budget.get("effective_value"),
        "service_host_port": summary.get("service_host_port"),
        "service_interpreter": summary.get("memoryos_service_interpreter"),
    }


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", message)
    message = re.sub(
        r"(?i)((?:api[-_ ]?key|token|authorization)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(r"https?://[^\s/@]+:[^\s/@]+@", "[REDACTED]@", message)
    message = re.sub(r"\b[A-Za-z0-9_-]{40,}\b", "[REDACTED]", message)
    return message[:500] or type(exc).__name__


def _session_sources(outbox: Any, session_id: str) -> list[dict[str, Any]]:
    rows = outbox._conn.execute(
        "SELECT payload_json FROM outbox_events WHERE state='ACKED'"
    ).fetchall()
    sources: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        observation = payload.get("observation", payload)
        locator = observation.get("locator", {}) or {}
        locator_value = str(locator.get("value") or "")
        content = observation.get("content", {}) or {}
        if session_id in locator_value or content.get("session_id") == session_id:
            if "text" not in observation:
                observation["text"] = str(content.get("text") or "")
            sources.append(observation)
    return sources


async def _wait_semantic_ready(facade: Any, timeout_s: float = 1800.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = await facade.status()
        semantic = last.get("semantic") if isinstance(last, dict) else None
        if isinstance(semantic, dict) and semantic.get("state") == "ERROR":
            raise RuntimeError("MemoryOS semantic worker entered ERROR state")
        if (
            isinstance(semantic, dict)
            and semantic.get("state") == "READY"
            and int(semantic.get("pending_count", 0) or 0) == 0
        ):
            return last
        await asyncio.sleep(2.0)
    semantic = last.get("semantic") if isinstance(last, dict) else {}
    raise TimeoutError(
        "MemoryOS semantic worker did not reach READY with zero pending source records; "
        f"state={semantic.get('state') if isinstance(semantic, dict) else 'missing'}, "
        f"pending={semantic.get('pending_count') if isinstance(semantic, dict) else 'missing'}"
    )


async def _run_one_question(
    row: dict[str, Any],
    *,
    index: int,
    run_root: Path,
    port: int,
    service_python: Path,
    model_manager: Any,
    raw_config: dict[str, Any],
    settings: dict[str, Any],
    observer_budget: int,
    official_module: Any,
    official_commit: str,
    evaluator_blob: str,
) -> dict[str, Any]:
    question_started = time.perf_counter()
    question_started_at = datetime.now(UTC).isoformat()
    phase_timings_ms: dict[str, float] = {}
    qid = str(row["question_id"])
    question_root = _checked_child(run_root / f"question-{qid}", TEMP_ROOT)
    question_root.mkdir(parents=True, exist_ok=False)
    atlas_data_root = question_root / "atlas-data"
    hermes_home = question_root / "hermes-home"
    atlas_data_root.mkdir(parents=True, exist_ok=True)
    hermes_home.mkdir(parents=True, exist_ok=True)
    os.environ["ATLAS_DATA_DIR"] = str(atlas_data_root)
    os.environ["HERMES_HOME"] = str(hermes_home)
    _write_question_hermes_config(hermes_home)
    hermes_config_check = _verify_question_hermes_config(hermes_home / "config.yaml")
    os.environ["MEMORYOS_DATA_ROOT"] = str(question_root / "memoryos")
    os.environ["MEMORYOS_DB_PATH"] = str(question_root / "memoryos" / "db" / "memoryos.sqlite3")

    import atlas.config as atlas_config

    atlas_config.DATA_ROOT = atlas_data_root
    atlas_config.USER_SETTINGS_PATH = atlas_data_root / "data" / "user-settings.json"

    from atlas.agent import AgentOrchestrator, run_phases
    from atlas.engine.session_sync import append_session_message
    from atlas.memory import MemoryStore
    from atlas.memory.capture import CaptureService, reset_capture_service
    from atlas.memory.observer import MemoryObserver
    from atlas.memory.observer_drain import MemoryObserverDrain
    from atlas.memory.unified_facade import UnifiedMemoryFacade
    from real_memory import RealMemoryService, TEST_INTERNAL_TOKEN

    atlas_outbox = question_root / "outbox" / "unified_outbox.sqlite3"
    memoryos_root = question_root / "memoryos"
    memoryos_root.mkdir(parents=True, exist_ok=True)

    subject_id = _question_subject_id(qid)
    service = RealMemoryService(
        memoryos_root, subject_id=subject_id, subject_aliases="",
        service_python=service_python,
    )
    service.port = port
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
        service_start = time.perf_counter()
        service.start()
        phase_timings_ms["memoryos_service_start_ms"] = (time.perf_counter() - service_start) * 1000
    except BaseException:
        service.stop()
        raise

    facade = None
    capture = None
    try:
        cfg = _prepare_atlas_config(
            raw_config, settings,
            service_url=f"http://127.0.0.1:{port}",
            internal_token=TEST_INTERNAL_TOKEN,
            subject_binding=subject_id,
            observer_budget=observer_budget,
            outbox_path=atlas_outbox,
        )
        import atlas.agent as atlas_agent
        import atlas.memory as atlas_memory
        import atlas.models as atlas_models

        for module_name in ("atlas.devices", "atlas.runtime.external_import"):
            module = sys.modules.get(module_name)
            if module is not None and hasattr(module, "DATA_ROOT"):
                module.DATA_ROOT = atlas_data_root

        atlas_config._config = cfg
        atlas_config.get_config = lambda: cfg
        atlas_config.load_user_settings = lambda path=None: settings
        atlas_agent.get_config = lambda: cfg
        atlas_memory.get_config = lambda: cfg
        atlas_models.get_config = lambda: cfg
        atlas_models.load_user_settings = lambda path=None: settings

        facade = UnifiedMemoryFacade(config=cfg)
        capture = CaptureService(
            facade=facade, config=cfg, outbox_path=atlas_outbox, event_class="TEST",
        )
        outbox = capture._ensure_outbox()
        observer = MemoryObserver(model_manager, cfg, outbox=outbox)
        drain = MemoryObserverDrain(observer, facade)
    except BaseException:
        if facade is not None:
            await facade.aclose()
        if capture is not None:
            capture.close()
        service.stop()
        reset_capture_service()
        raise

    observer_batches: list[dict[str, Any]] = []
    observer_router_calls: list[dict[str, Any]] = []
    model_router_call_timings: list[dict[str, Any]] = []
    http_acks: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    seen_batch_ids: set[str] = set()

    def record_batch(batch: Any) -> None:
        if batch is None or str(batch.batch_id) in seen_batch_ids:
            return
        seen_batch_ids.add(str(batch.batch_id))
        observer_batches.append({
            "batch_id": batch.batch_id,
            "model_id": batch.model_id,
            "input_tokens": batch.input_tokens,
            "output_tokens": batch.output_tokens,
            "raw_output": batch.raw_output,
            "observations": batch.payload.get("observations", []) if isinstance(batch.payload, dict) else [],
        })
        _write_jsonl(question_root / "observer_batches.jsonl", {
            "question_id": qid,
            "batch_id": batch.batch_id,
            "model_id": batch.model_id,
            "input_tokens": batch.input_tokens,
            "output_tokens": batch.output_tokens,
            "raw_output": batch.raw_output,
            "observations": batch.payload.get("observations", []) if isinstance(batch.payload, dict) else [],
        })

    original_complete = observer._complete_with_retry

    async def recording_complete(model_id: str, messages: list[dict[str, Any]], **kwargs: Any):
        result = await original_complete(model_id, messages, **kwargs)
        input_tokens, output_tokens, usage = _reported_usage(getattr(result, "usage", None))
        observer_router_calls.append({
            "model_id": model_id,
            "purpose": "memory_observe",
            "provider_reported_input_tokens": input_tokens,
            "provider_reported_output_tokens": output_tokens,
            "provider_usage": usage,
            "response_text": getattr(result, "text", ""),
        })
        _write_jsonl(question_root / "model_calls.jsonl", {
            "question_id": qid,
            "purpose": "memory_observe",
            "model_id": model_id,
            "provider_reported_input_tokens": input_tokens,
            "provider_reported_output_tokens": output_tokens,
            "provider_usage": usage,
            "response_text": getattr(result, "text", ""),
        })
        return result

    observer._complete_with_retry = recording_complete
    original_ack = observer.ack_batch

    async def recording_ack(batch_id: str):
        next_batch = await original_ack(batch_id)
        record_batch(next_batch)
        return next_batch

    observer.ack_batch = recording_ack
    original_observe = facade.observe_batch

    async def recording_observe(payload: dict[str, Any]):
        result = await original_observe(payload)
        receipts = result.get("receipts", []) if isinstance(result, dict) else []
        http_acks.append({
            "accepted": result.get("accepted") if isinstance(result, dict) else None,
            "receipt_refs": [str(item.get("record_ref") or "") for item in receipts if isinstance(item, dict)],
            "source_event_ids": [str(item.get("source_event_id") or "") for item in receipts if isinstance(item, dict)],
        })
        return result

    facade.observe_batch = recording_observe

    model_router = model_manager.model_router
    original_router_complete = model_router.complete_for
    call_timing_path = question_root / "model_call_timing.jsonl"

    async def recording_router_complete(model_id: str, purpose: str, messages: list[dict[str, Any]], **kwargs: Any):
        started = time.perf_counter()
        try:
            result = await original_router_complete(model_id, purpose, messages, **kwargs)
        except BaseException as exc:
            call = {
                "question_id": qid,
                "model_id": str(model_id),
                "purpose": str(purpose),
                "status": "failed",
                "error_type": type(exc).__name__,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
            model_router_call_timings.append(call)
            _write_jsonl(call_timing_path, call)
            raise
        input_tokens, output_tokens, usage = _reported_usage(getattr(result, "usage", None))
        call = {
            "question_id": qid,
            "model_id": str(model_id),
            "purpose": str(purpose),
            "status": "completed",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "provider_reported_input_tokens": input_tokens,
            "provider_reported_output_tokens": output_tokens,
            "provider_reported_cost_usd": usage.get("provider_reported_cost_usd"),
        }
        model_router_call_timings.append(call)
        _write_jsonl(call_timing_path, call)
        return result

    model_router.complete_for = recording_router_complete

    transcript_path = question_root / "source_dialogue.jsonl"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    total_turns = 0
    total_source_sessions = len(row["haystack_sessions"])
    try:
        source_observe_started = time.perf_counter()
        with transcript_path.open("w", encoding="utf-8") as transcript:
            for session_index, (upstream_session_id, source_date, turns) in enumerate(zip(
                row["haystack_session_ids"], row["haystack_dates"], row["haystack_sessions"],
            )):
                local_session_id = (
                    f"f1d-{qid}-{session_index:03d}-"
                    f"{hashlib.sha256(str(upstream_session_id).encode('utf-8')).hexdigest()[:12]}"
                )
                occurred_at = parse_source_datetime(str(source_date)).isoformat()
                for turn_index, turn in enumerate(turns):
                    content = turn["content"]
                    role = str(turn["role"]).lower()
                    message_id = f"{local_session_id}-t{turn_index:04d}"
                    if role == "user":
                        captured = capture.capture_user_message(
                            local_session_id, message_id, content,
                            occurred_at=occurred_at, source_timezone="UTC",
                        )
                    elif role == "assistant":
                        captured = capture.capture_assistant_message(
                            local_session_id, message_id, content,
                            occurred_at=occurred_at, source_timezone="UTC",
                        )
                    else:  # preflight rejects this; keep the guard at the capture boundary too.
                        raise ValueError(f"unsupported source role in {qid}")
                    source_event_id = str((captured or {}).get("source_event_id") or "")
                    if not source_event_id:
                        raise RuntimeError(f"Atlas CaptureService rejected a source turn in {qid}")
                    record = {
                        "question_id": qid,
                        "upstream_session_id": str(upstream_session_id),
                        "session_index": session_index,
                        "source_date_raw": str(source_date),
                        "source_date_utc_frame": occurred_at,
                        "turn_index": turn_index,
                        "role": role,
                        "content": content,
                        "source_event_id": source_event_id,
                        "locator": (captured or {}).get("locator"),
                    }
                    transcript.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    source_refs.append({
                        "source_event_id": source_event_id,
                        "upstream_session_id": str(upstream_session_id),
                        "local_session_id": local_session_id,
                        "turn_index": turn_index,
                        "role": role,
                    })
                    total_turns += 1

                flush_result = await capture.flush(limit=5000)
                acked_sources = _session_sources(outbox, local_session_id)
                expected_ids = {item["source_event_id"] for item in source_refs if item["local_session_id"] == local_session_id}
                acked_ids = {str(item.get("source_event_id") or "") for item in acked_sources}
                if expected_ids - acked_ids:
                    raise RuntimeError(f"CaptureService HTTP ACK missing {len(expected_ids - acked_ids)} source events")
                batch = await observer.add_messages(
                    local_session_id, acked_sources, session_ended=True,
                    context=facade.default_context(runtime_session_id=local_session_id),
                )
                record_batch(batch)
                await drain.drain_once()
                if observer.pending_sessions():
                    raise RuntimeError("Observer left a durable source session pending after drain")

        phase_timings_ms["source_capture_and_observe_ms"] = (time.perf_counter() - source_observe_started) * 1000
        semantic_ready_started = time.perf_counter()
        service_status = await _wait_semantic_ready(facade)
        phase_timings_ms["semantic_ready_ms"] = (time.perf_counter() - semantic_ready_started) * 1000
        question_date_raw = str(row.get("question_date") or "")
        date_reference_instruction = (
            "The benchmark metadata says this exact user question was asked at "
            f"{question_date_raw}. The source does not specify a timezone; use its "
            "displayed date/time only as the reference for relative-date reasoning. "
            "The user question text is the original source text."
        )
        conversation_id = f"f1d-longmemeval-{qid}"
        question = str(row["question"])
        workspace = question_root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            append_session_message, atlas_config.DATA_ROOT / "engine", conversation_id,
            "user", question, {"question_id": qid, "benchmark_question_date": question_date_raw},
        )
        memory_store = MemoryStore(unified=facade)
        atlas_db_path = Path(memory_store._db_path)
        memoryos_db_path = memoryos_root / "db" / "memoryos.sqlite3"
        storage_paths = {
            "runtime_root": question_root,
            "atlas_data_root": atlas_data_root,
            "atlas_memory_db": atlas_db_path,
            "atlas_engine_root": atlas_config.DATA_ROOT / "engine",
            "atlas_observer_outbox": atlas_outbox,
            "hermes_home": hermes_home,
            "memoryos_data_root": service.data_root,
            "memoryos_db": memoryos_db_path,
            "source_dialogue": transcript_path,
        }
        for key, storage_path in storage_paths.items():
            if key != "runtime_root":
                _checked_child(storage_path, question_root)
        agent = AgentOrchestrator(model_manager, memory_store)
        # The answer gets Atlas-retrieved context; it cannot access transcripts or files.
        agent._model_facing_tools = lambda: []
        context_capture: list[dict[str, Any]] = []
        original_phase_context = run_phases._phase_context

        async def recording_phase_context(run_agent: Any, state: Any):
            async for event in original_phase_context(run_agent, state):
                yield event
            context = state.context if isinstance(state.context, dict) else {}
            context_capture.append({
                "gate_passed": context.get("gate_passed"),
                "token_estimate": context.get("token_estimate"),
                "profile_block": context.get("profile_block", ""),
                "relevant_memory_block": context.get("relevant_memory_block", ""),
                "assembled_refs": context.get("assembled_refs", []),
                "assembled_ref_map": context.get("assembled_ref_map", {}),
                "memories": context.get("memories", []),
                "knowledge_trace": context.get("knowledge_trace", {}),
            })

        run_phases._phase_context = recording_phase_context
        answer_chunks: list[str] = []
        run_events: list[dict[str, Any]] = []
        run_usage: list[dict[str, Any]] = []
        answer_model: str | None = None
        try:
            from atlas.agent.run_phases import RunCallbacks, RunRequest, execute_run

            request = RunRequest(
                message=question,
                conversation_id=conversation_id,
                read_only=True,
                permission_mode="read_only",
                tool_allow=[],
                tool_deny=["*"],
                workspace=str(workspace),
                workspace_trusted=False,
                allowed_paths=[str(question_root)],
                active_skill_instructions=[{
                    "name": "LongMemEval reference date",
                    "content": date_reference_instruction,
                }],
            )
            answer_started = time.perf_counter()
            async for event in execute_run(agent, request, RunCallbacks()):
                safe_event = {key: value for key, value in event.items() if key in {"type", "model", "category", "detail"}}
                if event.get("type") == "chunk":
                    chunk = str(event.get("content") or "")
                    answer_chunks.append(chunk)
                    safe_event["chunk"] = chunk
                if event.get("type") == "run_usage" and isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                    safe_usage = {
                        key: usage.get(key)
                        for key in (
                            "request_id", "purpose", "model", "provider", "wire_model",
                            "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
                            "provider_reported_cost_usd", "cost_usd",
                        )
                        if key in usage
                    }
                    run_usage.append(safe_usage)
                    safe_event["usage"] = safe_usage
                    _write_jsonl(question_root / "model_calls.jsonl", {
                        "question_id": qid,
                        "purpose": str(safe_usage.get("purpose") or "answer"),
                        "model_id": safe_usage.get("model") or event.get("model"),
                        "usage": safe_usage,
                    })
                run_events.append(safe_event)
                if event.get("type") == "done":
                    answer_model = str(event.get("model") or "") or None
                if event.get("type") == "error":
                    raise RuntimeError(f"run_phases returned an error event ({event.get('category')})")
        finally:
            run_phases._phase_context = original_phase_context
        phase_timings_ms["answer_run_phases_ms"] = (time.perf_counter() - answer_started) * 1000

        answer_text = "".join(answer_chunks).strip()
        if not answer_text:
            raise RuntimeError("run_phases completed without an answer chunk")
        judge_prompt = official_module.get_anscheck_prompt(
            str(row["question_type"]), question, str(row["answer"]), answer_text,
            abstention=qid.endswith("_abs"),
        )
        judge_started = time.perf_counter()
        judge_result = await model_manager.model_router.complete_for(
            model_manager.current_model,
            "chat",
            [{"role": "user", "content": judge_prompt}],
            temperature=0,
            max_tokens=10,
        )
        phase_timings_ms["official_judge_ms"] = (time.perf_counter() - judge_started) * 1000
        judge_input, judge_output, judge_usage = _reported_usage(getattr(judge_result, "usage", None))
        judge_text = str(getattr(judge_result, "text", "") or "").strip()
        official_label = "yes" in judge_text.lower()
        _write_jsonl(question_root / "model_calls.jsonl", {
            "question_id": qid,
            "purpose": "official_longmemeval_judge",
            "model_id": model_manager.current_model,
            "provider_reported_input_tokens": judge_input,
            "provider_reported_output_tokens": judge_output,
            "provider_usage": judge_usage,
            "response_text": judge_text,
        })

        recall = context_capture[-1] if context_capture else {}
        actual_refs: list[str] = []
        for memory in recall.get("memories", []) if isinstance(recall.get("memories"), list) else []:
            if isinstance(memory, dict) and memory.get("record_ref"):
                actual_refs.append(str(memory["record_ref"]))
        evidence: list[dict[str, Any]] = []
        for record_ref in dict.fromkeys(actual_refs):
            try:
                evidence.append({"record_ref": record_ref, "evidence": await facade.client().evidence(record_ref)})
            except Exception as exc:  # preserve the reference and failure without logging credentials
                evidence.append({"record_ref": record_ref, "evidence_error_type": type(exc).__name__})

        phase_timings_ms["question_total_ms"] = (time.perf_counter() - question_started) * 1000

        result = {
            "question_id": qid,
            "question_type": row["question_type"],
            "question": question,
            "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
            "question_date_raw": question_date_raw,
            "question_date_context_addition": date_reference_instruction,
            "question_text_matches_source_verbatim": True,
            "subject_id": subject_id,
            "timing": {
                "started_at_utc": question_started_at,
                "phase_elapsed_ms": {key: round(value, 3) for key, value in phase_timings_ms.items()},
                "model_router_call_latency_ms": _summarize_latency_ms([
                    float(item["elapsed_ms"]) for item in model_router_call_timings
                ]),
                "model_router_calls": model_router_call_timings,
            },
            "runtime_root": str(question_root),
            "chat_tool_access": "disabled; answer uses Atlas retrieval/context only",
            "runtime_isolation": {
                "validated": True,
                "all_storage_paths_under_question_root": True,
                "paths": {key: str(value) for key, value in storage_paths.items()},
                "subject_database_is_unique_per_question": True,
                "hermes_auxiliary_policy": hermes_config_check,
            },
            "source_history": {
                "source_sha256": EXPECTED_S_SHA256,
                "session_count": total_source_sessions,
                "turn_count": total_turns,
                "transcript_artifact": str(transcript_path),
                "all_canonical_haystack_sessions_used": True,
                "source_date_frame": "Timezone-free dataset wall clock stored in UTC frame; no geographic timezone inferred.",
            },
            "capture_source_refs": source_refs,
            "observer": {
                "model_ids": sorted({str(item.get("model_id") or "") for item in observer_batches}),
                "router_calls": observer_router_calls,
                "batches": observer_batches,
                "http_acknowledgements": http_acks,
                "language_mismatch_count": observer.language_mismatch_count,
            },
            "semantic_status_before_answer": service_status.get("semantic", {}),
            "recall": recall,
            "recall_evidence": evidence,
            "answer": {
                "text": answer_text,
                "model_id": answer_model,
                "run_usage": run_usage,
                "events": run_events,
            },
            "official_judge": {
                "repository_commit": official_commit,
                "evaluate_qa_blob": evaluator_blob,
                "prompt_sha256": hashlib.sha256(judge_prompt.encode("utf-8")).hexdigest(),
                "prompt": judge_prompt,
                "model_id": model_manager.current_model,
                "provider_reported_input_tokens": judge_input,
                "provider_reported_output_tokens": judge_output,
                "provider_usage": judge_usage,
                "response": judge_text,
                "label": official_label,
            },
            "provider_reported_cost_usd": {
                "observer": [
                    item["provider_usage"].get("provider_reported_cost_usd")
                    for item in observer_router_calls
                    if item["provider_usage"].get("provider_reported_cost_usd") is not None
                ],
                "answer": [
                    item.get("provider_reported_cost_usd")
                    for item in run_usage
                    if item.get("provider_reported_cost_usd") is not None
                ],
                "judge": judge_usage.get("provider_reported_cost_usd"),
            },
            "token_totals": {
                "observer_budget_accounted_input_tokens": sum(
                    int(item.get("input_tokens") or 0) for item in observer_batches
                ),
                "observer_budget_accounted_output_tokens": sum(
                    int(item.get("output_tokens") or 0) for item in observer_batches
                ),
                "observer_provider_reported_input_tokens": sum(
                    int(item["provider_reported_input_tokens"])
                    for item in observer_router_calls
                    if item.get("provider_reported_input_tokens") is not None
                ),
                "observer_provider_reported_output_tokens": sum(
                    int(item["provider_reported_output_tokens"])
                    for item in observer_router_calls
                    if item.get("provider_reported_output_tokens") is not None
                ),
                "observer_provider_reported_complete": all(
                    item.get("provider_reported_input_tokens") is not None
                    and item.get("provider_reported_output_tokens") is not None
                    for item in observer_router_calls
                ),
                "answer_provider_reported_input_tokens": sum(
                    int(item.get("input_tokens") or 0) for item in run_usage
                ),
                "answer_provider_reported_output_tokens": sum(
                    int(item.get("output_tokens") or 0) for item in run_usage
                ),
                "judge_provider_reported_input_tokens": judge_input,
                "judge_provider_reported_output_tokens": judge_output,
            },
            "runtime_artifacts": {
                "observer_batches": str(question_root / "observer_batches.jsonl"),
                "model_calls": str(question_root / "model_calls.jsonl"),
                "model_call_timing": str(call_timing_path),
                "source_dialogue": str(transcript_path),
            },
        }
        return result
    finally:
        model_router.complete_for = original_router_complete
        try:
            await facade.aclose()
        finally:
            capture.close()
            service.stop()
            reset_capture_service()


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--subset", type=Path, default=DEFAULT_SUBSET)
    parser.add_argument("--validation", type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument("--official-root", type=Path, default=DEFAULT_OFFICIAL_ROOT)
    parser.add_argument("--limit", type=int, choices=(1, 12, 120), default=12)
    parser.add_argument("--full-evaluation", action="store_true", help="Required together with --limit 120 after root merge signal")
    parser.add_argument("--run-real", action="store_true", help="Start isolated MemoryOS and use configured Atlas ModelRouter")
    parser.add_argument("--service-port", type=int, default=None, help="Pre-coordinated 127.0.0.1 port; required for --run-real")
    parser.add_argument("--service-python", type=Path,
                        default=Path(r"D:\MemoryOS\service\.venv\Scripts\python.exe"),
                        help="MemoryOS service interpreter; defaults to the shared service venv")
    parser.add_argument("--run-root", type=Path, default=None, help="New isolated D:\\Temp\\F1-D-* run directory")
    parser.add_argument("--resume-from", type=Path, default=None,
                        help="Start a new isolated attempt, import only completed question checkpoints, and preserve the prior root")
    parser.add_argument("--observer-daily-token-budget", type=int, default=None,
                        help="Explicit test-only budget override; leaves reserve/retry checks enabled")
    return parser


def _validate_run_args(args: argparse.Namespace) -> None:
    if args.limit == 120 and not args.full_evaluation:
        raise ValueError("120-question runs require --full-evaluation after the root merge signal")
    if args.full_evaluation and args.limit != 120:
        raise ValueError("--full-evaluation is only valid for --limit 120")
    if args.run_real and args.service_port is None:
        raise ValueError("--run-real requires the pre-coordinated --service-port")
    if args.run_real and not args.service_python.resolve().is_file():
        raise FileNotFoundError("configured MemoryOS service interpreter does not exist")
    if args.resume_from is not None and (not args.run_real or args.run_root is None):
        raise ValueError("--resume-from requires --run-real and a new explicit --run-root")
    if args.service_port is not None and not (1024 <= args.service_port <= MAX_SERVICE_PORT):
        raise ValueError("service port must be between 1024 and 65535")


async def _run(args: argparse.Namespace) -> int:
    _validate_run_args(args)
    run_started = time.perf_counter()
    run_started_at = datetime.now(UTC).isoformat()

    selected, validation, subset, official_script, commit, blob = _load_preflight(
        args.source.resolve(), args.subset.resolve(), args.validation.resolve(),
        args.official_root.resolve(), args.limit,
    )
    selected_categories = Counter(str(row["question_type"]) for row in selected)
    if args.limit == 12 and selected_categories != Counter({category: 2 for category in CANONICAL_CATEGORIES}):
        raise RuntimeError(f"12-question smoke is not category balanced: {dict(selected_categories)}")

    if not PRODUCTION_CONFIG.is_file():
        raise FileNotFoundError("read-only Atlas config is unavailable")
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    raw_config = tomllib.loads(PRODUCTION_CONFIG.read_text(encoding="utf-8"))
    clear_gateway_fallback_config(raw_config)
    selected_stats = {
        str(item["question_id"]): item
        for item in validation.get("question_stats", [])
    }
    question_budget_requirements = {
        str(row["question_id"]): _observer_budget_estimate(
            [selected_stats[str(row["question_id"])]],
        )
        for row in selected
    }
    required_budget = max(question_budget_requirements.values(), default=0)
    budget = _configured_budget(raw_config, args.observer_daily_token_budget)
    raw_budget_value = (
        raw_config.get("memory", {}).get("v1", {})
        .get("observer_daily_token_budget")
    )
    run_root = args.run_root or TEMP_ROOT / f"F1-D-real-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_root = _checked_child(run_root, TEMP_ROOT)
    if not run_root.name.startswith("F1-D-"):
        raise RuntimeError("run root must use a unique F1-D- prefix under D:\\Temp")
    if run_root.exists():
        raise FileExistsError(f"run root already exists; refusing to reuse artifacts: {run_root}")
    prior_root = None
    prior_summary = None
    if args.resume_from is not None:
        prior_root = _checked_child(args.resume_from, TEMP_ROOT)
        if not prior_root.is_dir() or not (prior_root / "preflight.json").is_file():
            raise FileNotFoundError("--resume-from must point to an earlier F1-D run with preflight evidence")
        prior_summary = json.loads((prior_root / "preflight.json").read_text(encoding="utf-8"))
    planned_runtime_paths = {
        str(row["question_id"]): {
            "runtime_root": str(run_root / f"question-{row['question_id']}"),
            "atlas_data_root": str(run_root / f"question-{row['question_id']}" / "atlas-data"),
            "memoryos_data_root": str(run_root / f"question-{row['question_id']}" / "memoryos"),
            "hermes_home": str(run_root / f"question-{row['question_id']}" / "hermes-home"),
            "subject_id": f"f1d-{row['question_id']}",
            "source_dialogue": str(run_root / f"question-{row['question_id']}" / "source_dialogue.jsonl"),
        }
        for row in selected
    }
    summary = {
        "status": "READY_DRY_RUN" if not args.run_real else "PREFLIGHT_PASSED",
        "selected_question_ids": [str(row["question_id"]) for row in selected],
        "selected_categories": dict(selected_categories),
        "selected_full_s_sessions": sum(len(row["haystack_sessions"]) for row in selected),
        "selected_turns": sum(sum(len(session) for session in row["haystack_sessions"]) for row in selected),
        "planned_run_root": str(run_root),
        "resumed_from": str(prior_root) if prior_root else None,
        "planned_question_runtime_paths": planned_runtime_paths,
        "source_sha256": validation["source"]["sha256"],
        "subset_sha256": validation["subset"]["sha256"],
        "official_commit": commit,
        "official_repository_origin": OFFICIAL_ORIGIN,
        "official_evaluator_source_path": str(official_script),
        "official_evaluator_blob": blob,
        "answer_is_not_in_observer_or_chat_input": True,
        "gold_data_boundary": {
            "observer_and_capture": "canonical source role/content/occurred_at/source IDs only; no question or answer",
            "answer_chat": "original question plus Atlas assembled recall and recorded date-only metadata",
            "question_text": "source verbatim",
            "gold_answer": "used only after the answer, inside the independent official judge prompt",
            "chat_tools": "disabled so the model cannot read transcript/data files or bypass Atlas retrieval",
        },
        "observer_budget_preflight": {
            "raw_config_value": raw_budget_value,
            "defaulted_original_value": _configured_budget(raw_config, None),
            "explicit_isolated_override": args.observer_daily_token_budget,
            "effective_value": budget,
            "conservative_required_estimate": required_budget,
            "per_question_conservative_requirements": question_budget_requirements,
            "sufficient": budget >= required_budget,
            "runtime_enforcement": "per-request and durable outbox reservations remain enabled; each question uses its own outbox",
        },
        "cost_policy": {
            "model_id": F1_MODEL_ID,
            "pricing_status": "unknown until the provider reports actual per-call cost; unknown remains null",
            "legacy_deepseek_estimates": "SUPERSEDED_BY_USER20261009",
            "legacy_cost_stop_rule": "SUPERSEDED_BY_USER20261009",
            "actual_provider_usage_recorded": "per-call tokens and provider-reported cost when supplied",
        },
        "service_host_port": f"127.0.0.1:{args.service_port}" if args.service_port else None,
        "memoryos_service_interpreter": str(args.service_python.resolve()),
        "memoryos_embedding_device_requested": os.environ.get("MEMORYOS_EMBEDDING_DEVICE", "auto"),
    }
    if not args.run_real:
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if not PRODUCTION_SETTINGS.is_file():
        raise FileNotFoundError("read-only Atlas user settings are unavailable")
    run_root.mkdir(parents=True, exist_ok=False)
    _set_isolated_process_env(run_root)
    (run_root / "atlas-data").mkdir(parents=True, exist_ok=True)
    (run_root / "hermes-home").mkdir(parents=True, exist_ok=True)

    settings = read_isolated_model_settings(PRODUCTION_SETTINGS)
    isolated_settings_path = write_isolated_user_settings(run_root / "atlas-data", settings)
    if budget < required_budget:
        raise RuntimeError(
            f"Observer daily token budget {budget} is below conservative estimate {required_budget}; "
            "no service or model request has started. Use an explicitly approved isolated-run budget."
        )

    # Build ModelManager only after every runtime/cache path points to D:\\Temp.
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    first_cfg = _prepare_atlas_config(
        raw_config, settings,
        service_url=f"http://127.0.0.1:{args.service_port}",
        internal_token="test-internal-token",
        subject_binding=_question_subject_id(str(selected[0]["question_id"])),
        observer_budget=budget,
    )
    model_manager, model_route = bootstrap_model_manager(
        first_cfg, settings, isolated_settings_path,
    )
    summary["model_router"] = model_route
    summary["read_only_configuration_source"] = {
        "config_sha256": sha256_file(PRODUCTION_CONFIG),
        "settings_sha256": sha256_file(PRODUCTION_SETTINGS),
        "isolated_settings_path": str(isolated_settings_path),
        "isolated_settings_sha256": sha256_file(isolated_settings_path),
        "isolated_settings_fields": sorted(settings),
        "loaded_after_isolation_env": True,
        "settings_mutations_rejected": True,
        "secret_provider": "Windows Credential Manager via Atlas ModelManager",
    }
    imported_results: dict[str, dict[str, Any]] = {}
    incomplete_prior_ids: list[str] = []
    if prior_root is not None and prior_summary is not None:
        if _resume_identity(prior_summary) != _resume_identity(summary):
            raise RuntimeError("--resume-from run identity changed; completed checkpoints were not imported")
        imported_results, incomplete_prior_ids = _load_resume_source_results(
            prior_root, summary["selected_question_ids"],
        )
        summary["imported_completed_question_ids"] = list(imported_results)
        summary["retried_incomplete_prior_question_ids"] = incomplete_prior_ids
    summary["status"] = "RUNNING"
    (run_root / "preflight.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )

    official_module = _load_official_module(official_script)
    (run_root / "raw_output.jsonl").touch()
    for qid, result in imported_results.items():
        checkpoint_root = run_root / f"question-{qid}"
        checkpoint_root.mkdir(parents=True, exist_ok=False)
        _write_json_checkpoint(checkpoint_root / "result.json", result)
        _write_jsonl(run_root / "raw_output.jsonl", result, durable=True)
    completed_results = _load_resume_results(run_root, summary["selected_question_ids"])
    for index, row in enumerate(selected, start=1):
        qid = str(row["question_id"])
        if qid in completed_results:
            print(f"question {index}/{len(selected)}: {qid} already complete; checkpoint reused", flush=True)
            continue
        print(f"question {index}/{len(selected)}: {qid} ({row['question_type']})", flush=True)
        try:
            result = await _run_one_question(
                row,
                index=index,
                run_root=run_root,
                port=args.service_port,
                service_python=args.service_python.resolve(),
                model_manager=model_manager,
                raw_config=raw_config,
                settings=settings,
                observer_budget=budget,
                official_module=official_module,
                official_commit=commit,
                evaluator_blob=blob,
            )
        except Exception as exc:
            failure = {
                "question_id": qid,
                "question_type": str(row["question_type"]),
                "status": "FAILED_ATTEMPT",
                "error_type": type(exc).__name__,
                "error": _safe_error_message(exc),
                "attempt_root": str(run_root / f"question-{qid}"),
                "completed_question_ids": list(completed_results),
            }
            question_root = run_root / f"question-{qid}"
            if question_root.is_dir():
                _write_json_checkpoint(question_root / "failure.json", failure)
            _write_jsonl(run_root / "failures.jsonl", failure, durable=True)
            summary["status"] = "FAILED_QUESTION"
            summary["failed_question"] = failure
            summary["completed_question_ids"] = list(completed_results)
            summary["attempt_started_at_utc"] = run_started_at
            summary["attempt_elapsed_ms"] = round((time.perf_counter() - run_started) * 1000, 3)
            _write_json_checkpoint(run_root / "summary.json", summary)
            raise
        question_root = run_root / f"question-{qid}"
        _write_json_checkpoint(question_root / "result.json", result)
        _write_jsonl(run_root / "raw_output.jsonl", result, durable=True)
        completed_results[qid] = result

    results = [completed_results[qid] for qid in summary["selected_question_ids"]]

    category_results = {
        category: {
            "correct": sum(
                bool(item["official_judge"]["label"])
                for item in results if item["question_type"] == category
            ),
            "total": sum(item["question_type"] == category for item in results),
        }
        for category in CANONICAL_CATEGORIES
    }
    token_fields = (
        "observer_budget_accounted_input_tokens",
        "observer_budget_accounted_output_tokens",
        "observer_provider_reported_input_tokens",
        "observer_provider_reported_output_tokens",
        "answer_provider_reported_input_tokens",
        "answer_provider_reported_output_tokens",
        "judge_provider_reported_input_tokens",
        "judge_provider_reported_output_tokens",
    )
    token_totals = {
        field: sum(int(item["token_totals"].get(field) or 0) for item in results)
        for field in token_fields
    }
    token_totals["provider_reported_input_tokens"] = sum(
        token_totals[field] for field in (
            "observer_provider_reported_input_tokens",
            "answer_provider_reported_input_tokens",
            "judge_provider_reported_input_tokens",
        )
    )
    token_totals["provider_reported_output_tokens"] = sum(
        token_totals[field] for field in (
            "observer_provider_reported_output_tokens",
            "answer_provider_reported_output_tokens",
            "judge_provider_reported_output_tokens",
        )
    )
    token_totals["observer_provider_usage_complete"] = all(
        item["token_totals"]["observer_provider_reported_complete"] for item in results
    )
    model_router_calls = [
        call
        for item in results
        for call in item.get("timing", {}).get("model_router_calls", [])
    ]
    model_router_calls_by_purpose = Counter(
        f"{call.get('purpose', 'unknown')}:{call.get('status', 'unknown')}"
        for call in model_router_calls
    )
    phase_names = sorted({
        name
        for item in results
        for name in item.get("timing", {}).get("phase_elapsed_ms", {})
    })
    runtime_measurements = {
        "attempt_started_at_utc": run_started_at,
        "attempt_elapsed_ms": round((time.perf_counter() - run_started) * 1000, 3),
        "question_elapsed_ms": _summarize_latency_ms([
            float(item["timing"]["phase_elapsed_ms"]["question_total_ms"])
            for item in results
            if isinstance(item.get("timing", {}).get("phase_elapsed_ms", {}).get("question_total_ms"), (int, float))
        ]),
        "phase_elapsed_ms_total": {
            name: round(sum(
                float(item.get("timing", {}).get("phase_elapsed_ms", {}).get(name) or 0)
                for item in results
            ), 3)
            for name in phase_names
        },
        "model_router_call_latency_ms": _summarize_latency_ms([
            float(call["elapsed_ms"])
            for call in model_router_calls
            if isinstance(call.get("elapsed_ms"), (int, float))
        ]),
        "model_router_calls_by_purpose_and_status": dict(model_router_calls_by_purpose),
    }
    provider_costs: list[float] = []
    cost_call_count = 0
    cost_complete = True
    for item in results:
        cost_groups = item["provider_reported_cost_usd"]
        calls = (
            list(cost_groups["observer"])
            + list(cost_groups["answer"])
            + [cost_groups["judge"]]
        )
        expected_calls = (
            len(item["observer"]["router_calls"])
            + len(item["answer"]["run_usage"])
            + 1
        )
        cost_call_count += expected_calls
        known_for_question = 0
        for value in calls:
            if isinstance(value, (int, float)):
                provider_costs.append(float(value))
                known_for_question += 1
        cost_complete = cost_complete and known_for_question == expected_calls
    summary.update({
        "status": "COMPLETED",
        "run_root": str(run_root),
        "result_file": str(run_root / "raw_output.jsonl"),
        "question_count": len(results),
        "correct": sum(bool(item["official_judge"]["label"]) for item in results),
        "category_results": category_results,
        "answer_model_ids": sorted({str(item["answer"]["model_id"]) for item in results if item["answer"]["model_id"]}),
        "observer_model_ids": sorted({model for item in results for model in item["observer"]["model_ids"]}),
        "token_totals": token_totals,
        "runtime_measurements": runtime_measurements,
        "provider_reported_cost": {
            "complete_for_all_calls": cost_complete,
            "calls_with_known_cost": len(provider_costs),
            "calls_total": cost_call_count,
            "known_partial_sum_usd": sum(provider_costs) if provider_costs else None,
            "complete_sum_usd": sum(provider_costs) if cost_complete else None,
        },
        "configured_gateway_all_in_cost_usd": None,
    })
    (run_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main() -> int:
    args = _make_parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        # Never print settings, environment values or provider request objects.
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__, "message": _safe_error_message(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
