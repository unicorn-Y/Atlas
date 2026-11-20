"""Private FakeLLM/backend half of the Electron attempt rollback probe."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from tests.fakes.fake_llm_provider import DropMidStream, FakeLLMServer, Text
from tests.test_c1_websocket_acceptance import IsolatedBackend


async def main(root: Path, vite_port: int, scenario: str) -> int:
    root.mkdir(parents=True, exist_ok=True)
    backend_root = root / "backend"
    backend_root.mkdir()
    done_path = root / "done.request"
    server = FakeLLMServer()
    is_fallback = scenario == "fallback"
    is_max_output = scenario == "max-output"
    old_text = "OLD filtered answer" if is_fallback else "OLD answer must be rolled back"
    old_audit_prefix = old_text if is_fallback else "OLD"
    new_text = "NEW fallback answer" if is_fallback else "NEW answer"
    continuation_text = "continuation completed"
    if is_fallback:
        responses = iter([
            Text(old_text, finish_reason="content_filter"),
            Text(new_text, chunk_chars=4),
        ])
    elif is_max_output:
        responses = iter([
            DropMidStream(old_text, after_chars=3),
            Text(new_text, chunk_chars=4, finish_reason="length"),
            Text(continuation_text, chunk_chars=5),
        ])
    else:
        new_text = "NEW answer survives"
        responses = iter([
            DropMidStream(old_text, after_chars=3),
            Text(new_text, chunk_chars=4),
        ])
    server._responder = lambda _request: next(responses)
    server.start()
    backend = IsolatedBackend(backend_root, server, extra_env={
        "ATLAS_API_TOKEN": "atlas-electron-probe-token",
        "HERMES_STREAM_RETRIES": "1",
        "ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS": "2",
        "ATLAS_MODEL_RETRY_BUDGET_SECONDS": "30",
        **({"CLAUDE_CODE_MAX_RETRIES": "0"} if is_fallback else {}),
    }, with_fallback_model=is_fallback, extra_config=(
        f'[server]\nallowed_origins=["http://127.0.0.1:{vite_port}"]\n'
    ))
    receipt: dict[str, object] = {"root": str(root), "api_url": backend.url, "api_port": backend.port}
    try:
        await backend.ready()
        print(json.dumps({
            "ready": True, "root": str(root), "atlas_data_dir": str(backend_root / "atlas"),
            "api_url": backend.url, "api_port": backend.port, "done_path": str(done_path),
        }), flush=True)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline and not done_path.is_file():
            await asyncio.sleep(0.1)
        if not done_path.is_file():
            receipt.update(status="timeout", done_seen=False)
        else:
            request = json.loads(done_path.read_text(encoding="utf-8"))
            conversation_id = str(request.get("conversation_id") or "")
            receipt.update(done_seen=True, conversation_id=conversation_id)
            requests = server.main_requests()
            receipt["fake_request_count"] = len(requests)
            receipt["fake_request_models"] = [str(item.get("model") or "") for item in requests]
    except Exception as exc:
        receipt.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        # IsolatedBackend.close uses process termination on Windows; report that as harness
        # cleanup rather than treating it as natural backend lifespan evidence.
        await backend.close()
        server.stop()
    if receipt.get("done_seen") and receipt.get("conversation_id"):
        try:
            from atlas.engine.state.atlas_state import SessionDB

            with SessionDB(db_path=backend_root / "atlas" / "engine" / "state.db") as db:
                transcript = db.get_messages_as_conversation(str(receipt["conversation_id"]))
                audit = db.list_session_events(str(receipt["conversation_id"]), after_seq=0, limit=1000)
            assistant = [str(row.get("content") or "") for row in transcript if row.get("role") == "assistant"]
            attempt_rows = [row for row in audit if row.get("event_type") == "model/attempt"]
            receipt["assistant_text"] = assistant
            expected_assistant_fragments = (
                [new_text, continuation_text] if is_max_output else [new_text]
            )
            receipt["discarded_old_audit"] = any(
                row["payload"].get("status") == "discarded"
                and str(row["payload"].get("partial_text") or "").startswith(old_audit_prefix)
                for row in attempt_rows
            )
            receipt["backend_exit_code"] = backend.process.returncode
            receipt["backend_cleanup"] = "IsolatedBackend.close termination (not graceful-lifespan proof)"
            receipt["status"] = "pass" if (
                receipt.get("fake_request_count") == (3 if is_max_output else 2)
                and receipt.get("fake_request_models") == (
                    ["fake-model", "fallback-model"] if is_fallback
                    else ["fake-model"] * (3 if is_max_output else 2)
                )
                and all(any(fragment in item for item in assistant)
                        for fragment in expected_assistant_fragments)
                and all(old_text not in item for item in assistant)
                and receipt["discarded_old_audit"]
            ) else "fail"
        except Exception as exc:
            receipt.update(status="audit_error", audit_error=f"{type(exc).__name__}: {exc}")
    out = root / "receipt.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"receipt": str(out), **receipt}, ensure_ascii=False), flush=True)
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    scenario = sys.argv[3] if len(sys.argv) > 3 else "retry"
    if scenario not in {"retry", "fallback", "max-output"}:
        raise SystemExit("scenario must be retry, fallback or max-output")
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]).resolve(), int(sys.argv[2]), scenario)))
