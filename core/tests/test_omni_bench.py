"""Unit checks for benchmark accounting and filesystem safety only.

These fixtures are not benchmark runs and are never emitted as runtime evidence.
"""

from __future__ import annotations

import sqlite3
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import omni_bench

pytestmark = pytest.mark.unit


def test_dsh_usage_accumulates_each_step_and_cache_write() -> None:
    usage, complete = omni_bench._aggregate_dsh_step_usage([
        {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 3, "cacheWriteTokens": 4},
        {"inputTokens": 5, "outputTokens": 1, "cacheReadTokens": 6, "cacheWriteTokens": 7},
    ])

    assert complete is True
    assert usage == {
        "inputTokens": 15, "outputTokens": 3,
        "cacheReadTokens": 9, "cacheWriteTokens": 11,
    }
    sample = omni_bench.Sample(
        "dsh", "task", True, 1, input_tokens=15, output_tokens=3,
        cached_input_tokens=9, cache_write_tokens=11, usage_complete=complete,
    )
    assert sample.prompt_tokens == 35


def test_missing_dsh_step_usage_or_bucket_remains_unknown() -> None:
    partial, complete = omni_bench._aggregate_dsh_step_usage([
        {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 3, "cacheWriteTokens": 4},
        None,
    ])
    assert complete is False
    assert partial["inputTokens"] == 10

    missing_bucket, complete = omni_bench._aggregate_dsh_step_usage([
        {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 3},
    ])
    assert complete is False
    assert missing_bucket["cacheWriteTokens"] is None

    sample = omni_bench.Sample(
        "dsh", "task", True, 1, input_tokens=10, cached_input_tokens=3,
        usage_complete=complete,
    )
    assert sample.prompt_tokens is None


def test_dsh_parser_sums_step_end_not_turn_end() -> None:
    stream = "\n".join([
        '{"type":"session","sessionId":"session-a"}',
        '{"type":"status","phase":"step_start"}',
        '{"type":"status","phase":"step_end","usage":{"inputTokens":8,"outputTokens":1,"cacheReadTokens":2,"cacheWriteTokens":3}}',
        '{"type":"status","phase":"step_start"}',
        '{"type":"status","phase":"step_end","usage":{"inputTokens":4,"outputTokens":2,"cacheReadTokens":5,"cacheWriteTokens":6}}',
        '{"type":"status","phase":"turn_end","reason":{"kind":"completed"}}',
        '{"type":"final","text":"OK"}',
    ])

    parsed = omni_bench._parse_dsh_stream(stream)
    assert parsed["terminal"] == "completed"
    assert parsed["final_text"] == "OK"
    assert parsed["session_ids"] == ["session-a"]
    assert parsed["steps"] == 2
    assert parsed["usage_complete"] is True
    assert parsed["usage"]["inputTokens"] == 12
    assert parsed["usage"]["cacheReadTokens"] == 7
    assert parsed["usage"]["cacheWriteTokens"] == 9


def test_tool_task_requires_a_successful_matching_tool_result() -> None:
    calls = [{
        "id": "call-1", "name": "python",
        "arguments": {"command": "python -c \"print(6*7)\""},
    }]
    results = [{"id": "call-1", "status": "completed", "result": "42\n"}]
    assert omni_bench._validate_task_result(
        omni_bench.TASKS[6], "42", calls, results,
    )[0] is True
    assert omni_bench._validate_task_result(
        omni_bench.TASKS[6], "41", calls, results,
    )[0] is False
    assert omni_bench._validate_task_result(
        omni_bench.TASKS[6], "42", [], results,
    )[0] is False


def test_hook_isolation_refuses_to_overwrite_any_existing_file(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "data" / "hooks.toml"
    target.parent.mkdir(parents=True)
    target.write_text("sentinel", encoding="utf-8")
    monkeypatch.setattr(
        omni_bench, "_third_party_hook_overrides", lambda: {"codex-hook": False},
    )

    with pytest.raises(FileExistsError):
        omni_bench._apply_hook_isolation(True, tmp_path)

    assert target.read_text(encoding="utf-8") == "sentinel"


def test_usage_query_refuses_a_database_outside_the_active_isolated_root(
    tmp_path: Path, monkeypatch,
) -> None:
    active = tmp_path / "active"
    foreign = tmp_path / "foreign" / "atlas.db"
    foreign.parent.mkdir()
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE usage_records (run_id TEXT, input_tokens INT, output_tokens INT, cached_input_tokens INT)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("ATLAS_DATA_DIR", str(active))

    assert omni_bench._atlas_usage("bench-run", foreign) is None


def test_usage_query_follows_each_explicit_isolated_root(tmp_path: Path, monkeypatch) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    for index, root in enumerate(roots, start=1):
        db = root / "data" / "atlas.db"
        db.parent.mkdir(parents=True)
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE usage_records "
            "(run_id TEXT, input_tokens INT, output_tokens INT, cached_input_tokens INT)"
        )
        conn.execute(
            "INSERT INTO usage_records VALUES (?, ?, ?, ?)",
            ("bench-run", index * 10, index, index * 2),
        )
        conn.commit()
        conn.close()
        monkeypatch.setenv("ATLAS_DATA_DIR", str(root))
        assert omni_bench._atlas_usage("bench-run", db) == {
            "input_tokens": index * 10,
            "output_tokens": index,
            "cached_input_tokens": index * 2,
        }


def test_backend_writes_private_hooks_before_spawning_and_records_graceful_exit(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(omni_bench.tempfile, "TemporaryDirectory", lambda **_: SimpleNamespace(
        name=str(tmp_path), cleanup=lambda: None,
    ))
    monkeypatch.setattr(omni_bench, "_third_party_hook_overrides", lambda: {"private-hook": False})
    monkeypatch.setattr(omni_bench, "_atlas_ready", lambda _port: True)
    monkeypatch.setattr(omni_bench.IsolatedAtlasBackend, "_verify_hook_overrides", lambda self: None)

    class Child:
        returncode = 0

        def poll(self):
            return None if not hasattr(self, "exited") else self.returncode

        def send_signal(self, _signal):
            raise AssertionError("normal shutdown must use the private control file")

        def wait(self, timeout=None):
            assert (tmp_path / "shutdown.request").is_file()
            self.exited = True
            kwargs["stdout"].write(b"INFO Application shutdown complete\n")
            kwargs["stdout"].flush()
            self.returncode = 0
            return self.returncode

    kwargs = {}

    def spawn(*_args, **popen_kwargs):
        kwargs.update(popen_kwargs)
        assert (tmp_path / "data" / "hooks.toml").is_file()
        return Child()

    monkeypatch.setattr(omni_bench.subprocess, "Popen", spawn)
    backend = omni_bench.IsolatedAtlasBackend(39171, isolate_hooks=True)
    assert backend.hook_override == tmp_path / "data" / "hooks.toml"
    backend.close()

    assert backend.graceful_exit is True
    assert backend.forced_termination is False
    assert backend.exit_code == 0


def test_nonzero_controlled_exit_is_not_reported_as_graceful(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(omni_bench.tempfile, "TemporaryDirectory", lambda **_: SimpleNamespace(
        name=str(tmp_path), cleanup=lambda: None,
    ))
    monkeypatch.setattr(omni_bench, "_atlas_ready", lambda _port: True)
    monkeypatch.setattr(omni_bench.IsolatedAtlasBackend, "_verify_hook_overrides", lambda self: None)

    class Child:
        returncode = 1

        def poll(self):
            return None if not hasattr(self, "exited") else self.returncode

        def send_signal(self, _signal):
            raise OSError("not deliverable")

        def terminate(self):
            self.exited = True

        def wait(self, timeout=None):
            self.exited = True
            return self.returncode

    monkeypatch.setattr(omni_bench.subprocess, "Popen", lambda *_a, **_kw: Child())
    backend = omni_bench.IsolatedAtlasBackend(39172)
    backend.close()

    assert backend.exit_code == 1
    assert backend.graceful_exit is False
    assert backend.forced_termination is False


def test_backend_escalates_timeout_through_terminate_then_kill(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(omni_bench.tempfile, "TemporaryDirectory", lambda **_: SimpleNamespace(
        name=str(tmp_path), cleanup=lambda: None,
    ))
    monkeypatch.setattr(omni_bench, "_atlas_ready", lambda _port: True)
    monkeypatch.setattr(omni_bench.IsolatedAtlasBackend, "_verify_hook_overrides", lambda self: None)

    class Child:
        returncode = None

        def __init__(self):
            self.actions = []

        def poll(self):
            return self.returncode

        def send_signal(self, _signal):
            self.actions.append("signal")

        def terminate(self):
            self.actions.append("terminate")

        def kill(self):
            self.actions.append("kill")
            self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                raise omni_bench.subprocess.TimeoutExpired("wait", timeout)
            return self.returncode

    child = Child()
    monkeypatch.setattr(omni_bench.subprocess, "Popen", lambda *_a, **_kw: child)
    backend = omni_bench.IsolatedAtlasBackend(39173)

    backend.close()

    assert child.actions == ["terminate", "kill"]
    assert backend.exit_code == -9
    assert backend.graceful_exit is False
    assert backend.forced_termination is True


def test_backend_log_summary_keeps_lifecycle_and_error_kind_not_raw_error_text(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "atlas-server.log"
    log_path.write_text(
        "INFO Application startup complete\n"
        "ERROR RuntimeError: private prompt, bearer-token=top-secret-value\n",
        encoding="utf-8",
    )
    backend = omni_bench.IsolatedAtlasBackend.__new__(omni_bench.IsolatedAtlasBackend)
    backend.log_path = log_path
    backend._log_stream = None

    summary = backend._safe_log_tail()

    assert "startup=complete" in summary
    assert "errors=1" in summary
    assert "RuntimeError" in summary
    assert "private prompt" not in summary
    assert "top-secret-value" not in summary
