"""Start a private FakeLLM/API backend for a bounded renderer rollback probe."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

from tests.fakes.fake_llm_provider import DropMidStream, FakeLLMServer, Text
from tests.test_c1_websocket_acceptance import IsolatedBackend


DEADLINE_SECONDS = 120.0


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="atlas-dsh-attempt-ui-")).resolve()
    ready_path = root / "ready.json"
    done_path = root / "done.request"
    receipt_path = root / "receipt.json"
    deadline = time.monotonic() + DEADLINE_SECONDS
    backend: IsolatedBackend | None = None
    server: FakeLLMServer | None = None
    cleanup_mode = "not_started"
    done_seen = False
    startup_error: str | None = None

    try:
        server = FakeLLMServer()
        responses = iter([
            DropMidStream("OLD answer must be rolled back", after_chars=3),
            Text("NEW answer survives", chunk_chars=4),
        ])
        server._responder = lambda _request: next(responses)
        server.start()
        backend = IsolatedBackend(root, server, extra_env={
            "ATLAS_API_TOKEN": "",
            "HERMES_STREAM_RETRIES": "1",
            "ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS": "2",
            "ATLAS_MODEL_RETRY_BUDGET_SECONDS": "30",
        }, extra_config=(
            '[server]\nallowed_origins=["http://127.0.0.1:5176"]\n'
        ))
        await asyncio.wait_for(backend.ready(), timeout=min(40.0, DEADLINE_SECONDS))
        _write_json(ready_path, {
            "api_base_url": backend.url,
            "api_port": backend.port,
            "vite_port": 5176,
            "deadline_seconds": DEADLINE_SECONDS,
            "done_request": str(done_path),
            "root": str(root),
        })
        print(json.dumps({
            "ready": str(ready_path), "api_base_url": backend.url,
            "api_port": backend.port, "root": str(root),
        }), flush=True)

        while time.monotonic() < deadline:
            if done_path.is_file():
                done_seen = True
                break
            await asyncio.sleep(0.2)
        if not done_seen:
            startup_error = "absolute deadline expired before done.request"
    except Exception as exc:
        startup_error = f"{type(exc).__name__}: {exc}"
    finally:
        if backend is not None:
            cleanup_mode = "forced_by_IsolatedBackend.close"
            try:
                await backend.close()
            except Exception as exc:
                cleanup_mode = f"close_error:{type(exc).__name__}"
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass

    receipt = {
        "status": "browser_completed" if done_seen and startup_error is None else "incomplete",
        "done_seen": done_seen,
        "fake_model_request_count": len(server.main_requests()) if server is not None else 0,
        "backend_pid": backend.process.pid if backend is not None else None,
        "backend_exit_code": backend.process.returncode if backend is not None else None,
        "backend_cleanup_mode": cleanup_mode,
        "error": startup_error,
        "root": str(root),
    }
    _write_json(receipt_path, receipt)
    print(json.dumps({"receipt": str(receipt_path), **receipt}, ensure_ascii=False), flush=True)
    return 0 if done_seen and startup_error is None else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
