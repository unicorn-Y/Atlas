import json
from pathlib import Path

import pytest

from scripts.memory_v1 import f2_cpu_recall_benchmark as benchmark


def test_run_directory_must_be_new_and_outside_protected_roots(tmp_path: Path) -> None:
    run_dir = tmp_path / "isolated-run"
    assert benchmark.assert_isolated_run_dir(run_dir) == run_dir.resolve()
    run_dir.mkdir()
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.assert_isolated_run_dir(run_dir)

    protected_child = benchmark.ATLAS_ROOT / "benchmark-child-for-test"
    with pytest.raises(benchmark.BenchmarkError):
        benchmark.assert_isolated_run_dir(protected_child)


def test_fixture_corpus_has_exactly_ten_thousand_synthetic_rows() -> None:
    rows = benchmark.build_fixture_rows(
        benchmark.FIXTURE_COUNT, "f2-cpu-test-subject", "2026-10-09T00:00:00+00:00",
    )
    assert len(rows) == 10_000
    assert len({row[0] for row in rows}) == 10_000
    assert rows[0][0] == "f2-cpu-perf-00001"
    assert "synthetic" in rows[0][19].lower()
    assert rows[0][3] == "f2-cpu-test-subject"
    assert "private user text" not in json.dumps(rows[0]).lower()


def test_fixture_builder_rejects_a_different_target_size() -> None:
    with pytest.raises(ValueError):
        benchmark.build_fixture_rows(9999, "subject", "now")


def test_query_fixture_is_deterministic_and_uses_only_synthetic_ids() -> None:
    assert benchmark.fixture_query(12) == benchmark.fixture_query(12)
    assert "00013" in benchmark.fixture_query(12)
    assert "performance benchmark fixture" in benchmark.fixture_query(12)


def test_percentile_uses_nearest_rank_and_rejects_empty_samples() -> None:
    assert benchmark.percentile([8, 1, 4, 7, 2], 0.50) == 4
    assert benchmark.percentile(list(range(1, 101)), 0.95) == 95
    with pytest.raises(ValueError):
        benchmark.percentile([], 0.95)


def test_service_environment_explicitly_forces_offline_cpu_and_clone_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORYOS_EMBEDDING_DEVICE", "cuda")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.invalid")
    run_dir = tmp_path / "run"
    db_path = run_dir / "service-data" / "db" / "memoryos.sqlite3"
    env = benchmark._service_environment(run_dir, db_path, "fixture-subject", "one-time-token")
    assert env["MEMORYOS_EMBEDDING_DEVICE"] == "cpu"
    assert env["MEMORYOS_EMBEDDING_ALLOW_DOWNLOAD"] == "0"
    assert env["MEMORYOS_DB_PATH"] == str(db_path)
    assert env["MEMORYOS_DATA_ROOT"] == str(run_dir / "service-data")
    assert env["HF_HUB_OFFLINE"] == "1"
    assert "HTTP_PROXY" not in env
    assert env["MEMORYOS_INTERNAL_TOKEN"] == "one-time-token"


def test_safe_status_keeps_only_allowlisted_semantic_fields() -> None:
    status = benchmark._safe_status({
        "state": "READY", "device": "cpu", "model_id": benchmark.MODEL_ID,
        "pending_count": 0, "error": "private synthetic detail", "secret": "never copy",
    })
    assert status == {
        "state": "READY", "device": "cpu", "model_id": benchmark.MODEL_ID,
        "pending_count": 0, "error_present": True,
    }
    assert "private synthetic detail" not in json.dumps(status)
    assert "never copy" not in json.dumps(status)
