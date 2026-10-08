"""Offline checks for resumable F1-B language-smoke artifacts."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
_SPEC = importlib.util.spec_from_file_location(
    "f1_language_smoke_under_test",
    _SCRIPT_DIR / "f1_language_smoke.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_SMOKE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SMOKE)


def _resume_artifact() -> dict:
    return {
        "schema_version": 1,
        "input_sha256": _SMOKE._input_digest(1),
        "limit": 1,
        "route": {
            "model_id": _SMOKE.MODEL_ID,
            "observer_model_id": _SMOKE.MODEL_ID,
            "provider_id": _SMOKE.PROVIDER_ID,
            "provider_endpoint_host": "127.0.0.1:8045",
            "credential_present": True,
            "credential_source": "Atlas ModelManager Windows Credential Manager lookup",
            "credential_value_recorded": False,
        },
        "results": [
            {
                "status": "succeeded",
                "sample_number": 1,
                "segment": 1,
                "repetition": 1,
                "source_events": [
                    {"source_event_id": "source-1", "speaker_role": "USER", "text": "输入一"},
                    {"source_event_id": "source-2", "speaker_role": "ATLAS", "text": "输入二"},
                ],
                "language_status": "passed",
                "language_mismatch_count": 0,
                "observer_accounted_input_tokens": 10,
                "observer_accounted_output_tokens": 4,
                "observation_texts": ["一条中文记录"],
                "raw_output": json.dumps({
                    "observations": [{"text": "一条中文记录", "evidence": ["source-1"]}],
                }, ensure_ascii=False),
            },
        ],
        "attempt_history": [
            {"sample_number": 1, "status": "succeeded"},
            {"sample_number": 2, "status": "failed", "error_type": "APITimeoutError"},
        ],
        "model_calls": [
            {
                "model_id": _SMOKE.MODEL_ID,
                "purpose": "memory_observe",
                "status": "failed",
                "input_tokens": None,
                "output_tokens": None,
                "error_type": "APITimeoutError",
            },
        ],
    }


def _write_resume(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_resume_skips_success_and_retains_failed_sample(tmp_path: Path) -> None:
    resume = _SMOKE._load_resume(_write_resume(tmp_path / "resume.json", _resume_artifact()), 1)

    successful = {item["sample_number"] for item in resume["results"]}
    assert _SMOKE._pending_samples(1, successful) == [2, 3]
    assert {
        (item["sample_number"], item["status"], item.get("error_type"))
        for item in resume["attempt_history"]
    } == {
        (1, "succeeded", None),
        (2, "failed", "APITimeoutError"),
    }
    assert len(resume["results"]) == len(successful) == 1


def test_resume_rejects_duplicate_successful_sample(tmp_path: Path) -> None:
    data = _resume_artifact()
    data["results"].append(dict(data["results"][0]))

    with pytest.raises(ValueError, match="repeats a successful sample"):
        _SMOKE._load_resume(_write_resume(tmp_path / "duplicate.json", data), 1)


def test_resume_rejects_changed_inputs(tmp_path: Path) -> None:
    data = _resume_artifact()
    data["input_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="different dialogue set or sample limit"):
        _SMOKE._load_resume(_write_resume(tmp_path / "wrong-input.json", data), 1)
