"""W6's eight focused live scenarios (provider calls never print credentials)."""
from __future__ import annotations

import asyncio
import re
import hashlib
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _manager() -> Any:
    from atlas.models import ModelManager

    class ReadOnlyModelManager(ModelManager):
        def set_api_mode_probe(self, provider_id: str, probe: dict[str, Any]) -> None:
            return None

        def credential_pool(self, provider_id: str) -> None:
            return None

    return ReadOnlyModelManager()


async def _history_repair(agent: Any) -> None:
    from atlas.kernel.model_call import complete_stream
    from atlas.kernel.repair import repair_unpaired_tool_calls

    bad_history = [
        {"role": "tool", "tool_call_id": "orphan-id", "content": "stale result"},
        {"role": "user", "content": "Continue safely. State that recovery succeeded."},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "w6-open", "type": "function",
            "function": {"name": "local_file", "arguments": "{}"},
        }]},
    ]
    repaired, receipts = repair_unpaired_tool_calls(bad_history, started_ids={"w6-open"})
    if not any(item["state"] == "orphan_result_dropped" for item in receipts):
        raise RuntimeError("orphan tool result did not get removed from provider history")
    if not any(item.get("tool_call_id") == "w6-open" and item.get("repair_state") == "unknown"
               for item in repaired if item.get("role") == "tool"):
        raise RuntimeError("unpaired tool call did not receive an unknown-outcome result")
    result = await complete_stream(agent, "deepseek-v4.1-flash", [
        {"role": "system", "content": "Continue from repaired tool history. Reply briefly."},
        *repaired,
    ], [], max_output_tokens=96, max_retries=2)
    if not result.text.strip():
        raise RuntimeError("live model did not continue from the repaired history")
    print("1 history repair: orphan removed, uncertain tool receipt paired, model continued", flush=True)


async def _agent_crash_budget() -> None:
    from atlas.agent.enrichment import DelegationService, HookBus

    service = DelegationService(host=type("Host", (), {"backends": {}})(), hooks=HookBus())
    attempts = 0
    progress: list[str] = []

    async def runner(**kwargs: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("fixture startup crash")
        return {"status": "completed", "result": "restarted-child-ok", "evidence": []}

    async def on_progress(_subtask_id: str, text: str) -> None:
        progress.append(text)

    service.atlas_runner = runner
    result = await service.delegate_task(
        "finish the recovery fixture", backend="atlas", cwd=os.getcwd(),
        on_progress=on_progress, _subtask_id="w6-crash-budget",
    )
    if (attempts != 2 or result.get("status") != "completed"
            or "重新启动" not in " ".join(progress)):
        raise RuntimeError("child crash did not consume exactly one restart budget")
    print("2 agent crash budget: one pre-progress crash restarted; child completed", flush=True)


def _timeout_and_connection_recovery() -> None:
    from atlas.models.router import _client
    from atlas.models.network_transport import ModelNetworkSettings
    import httpx

    state = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            state["count"] += 1
            if state["count"] == 1:
                time.sleep(0.15)
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from atlas.models.router import RouteSpec
        route = RouteSpec(provider="openai", api_mode="openai", model="fake",
                          base_url=f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                          wire_model="fake")
        network = ModelNetworkSettings()
        timeout = httpx.Timeout(connect=1, read=0.04, write=1, pool=1)
        client = _client(route, network, timeout)
        try:
            try:
                client.post(route.base_url, json={})
            except httpx.ReadTimeout:
                pass
            else:
                raise RuntimeError("slow fixture did not hit the configured read timeout")
        finally:
            client.__exit__()
        with _client(route, network, httpx.Timeout(connect=1, read=1, write=1, pool=1)) as retry_client:
            response = retry_client.post(route.base_url, json={})
        if response.status_code != 200 or state["count"] < 2:
            raise RuntimeError("request did not recover after the timeout")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print("3 request timeout: short read timed out, a fresh request recovered", flush=True)


async def _protocol_and_compression(temp_root: Path) -> None:
    from atlas.kernel.context import ContextManager
    from atlas.kernel.repair import normalize_tool_results

    history = [
        {"role": "user", "content": "Use the file tool, then summarize."},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "w6-file-1", "type": "function",
            "function": {"name": "local_file", "arguments": "{\"path\":\"pyproject.toml\"}"},
        }]},
        {"role": "tool", "tool_call_id": "w6-file-1", "content": "name = 'atlas'"},
        {"role": "assistant", "content": "The project is Atlas."},
    ]
    paired = normalize_tool_results(history)

    async def summarize(_old: list[dict[str, Any]], _prompt: str) -> str:
        return "Summary retains the completed local_file protocol and project name Atlas."

    manager = ContextManager({"engine": {"max_output_tokens": 128,
                                          "context_keep_messages": 2}},
                             output_dir=temp_root / "context")
    compacted = await manager.prepare(
        paired, model_window=64, summarize=summarize,
        preserved={"protocol": "local_file:w6-file-1"},
    )
    normalized = normalize_tool_results(compacted.messages)
    calls = [call for message in normalized if message.get("role") == "assistant"
             for call in message.get("tool_calls", [])]
    if len(calls) != 1 or calls[0].get("id") != "w6-file-1":
        raise RuntimeError("compaction broke the tool call/receipt protocol")
    print("4 protocol compression: paired tool call/result survived summary preparation", flush=True)


async def _command_file_cwd(temp_root: Path) -> None:
    from atlas.tools.local_execution import LocalExecutionRuntime
    from unittest.mock import patch

    runtime = LocalExecutionRuntime()
    runtime.permission_mode = "full_access"
    try:
        (temp_root / "w6-relative.txt").write_text("relative-cwd-ok", encoding="utf-8")
        read = await runtime.call_tool("local_file", {
            "action": "read", "path": "w6-relative.txt", "_atlas_workspace": str(temp_root),
        },
                                       run_id="w6-file-cwd")
        if read.get("is_error") or "relative-cwd-ok" not in json.dumps(read, ensure_ascii=False):
            raise RuntimeError("relative path did not resolve to the selected workspace")
        missing = await runtime.call_tool("local_file", {
            "action": "read", "path": "w6-no-such-file.txt", "offset": 1, "limit": 3,
            "_atlas_workspace": str(temp_root),
        }, run_id="w6-file-cwd")
        body = json.dumps(missing, ensure_ascii=False)
        if "File not found" not in body or "Line-range reads require" in body:
            raise RuntimeError("missing path produced a misleading line-range error")
        with patch.object(LocalExecutionRuntime, "_agent_cwd", return_value=Path.home()):
            home_read = await runtime.call_tool(
                "local_file", {"action": "read", "path": "w6-relative.txt"},
                run_id="w6-no-project",
            )
            descriptions = " ".join(
                str((tool.get("function") or {}).get("description") or "")
                for tool in runtime.get_tools_for_llm()
            )
        home_error = json.dumps(home_read, ensure_ascii=False)
        if (not home_read.get("is_error")
                or "No project or workspace is selected" not in home_error
                or "relative paths and commands without cwd are rejected" not in descriptions):
            raise RuntimeError("no-project relative path fell back to the user home directory")
    finally:
        await runtime.shutdown()
    print("5 command/file CWD: workspace-relative read passed; missing file was clear; home fallback rejected", flush=True)


def _model_capacity_and_availability() -> None:
    manager = _manager()
    live_model = "deepseek-v4.1-flash"
    available = manager.model_availability(live_model)
    if not available.get("available"):
        raise RuntimeError("configured live DeepSeek model is not locally available")
    if manager.model_availability("w6-unknown-model").get("reason") != "unknown_model":
        raise RuntimeError("unknown model was not rejected by the availability gate")
    capable = next((item for item in manager.list_models()
                    if (item.get("capabilities") or {}).get("context_window")), None)
    if capable is None:
        raise RuntimeError("local catalog has no model with declared context capacity")
    model = str(capable.get("id"))
    window = manager.context_window_for_model(model)
    if not window or window < 1:
        raise RuntimeError("selected model has no resolved context window")
    capped = manager.output_tokens_for_model(model, 1_000_000, 8_192)
    if not capped or capped > 1_000_000:
        raise RuntimeError("output token request was not bounded")
    from atlas.models.router import RouteSpec, _request_details
    eligible = RouteSpec(provider="anthropic", api_mode="anthropic_messages", model="claude",
                         base_url="https://example.invalid", capabilities={"context_window": 1_000_000})
    _, eligible_headers, _ = _request_details(eligible, [{"role": "user", "content": "probe"}], {
        "sdk_betas": ["context-1m-2025-08-07", "unrecognized-beta"],
    })
    ineligible = RouteSpec(provider="openai", api_mode="anthropic_messages", model="other",
                           base_url="https://example.invalid", capabilities={"context_window": 1_000_000})
    _, ineligible_headers, _ = _request_details(ineligible, [{"role": "user", "content": "probe"}], {
        "sdk_betas": ["context-1m-2025-08-07"],
    })
    if eligible_headers.get("anthropic-beta") != "context-1m-2025-08-07" \
            or "anthropic-beta" in ineligible_headers:
        raise RuntimeError("1M beta was not limited to eligible Anthropic models")
    print(f"6 model capacity: selected context window resolved ({window}); output bounded", flush=True)
    print("7 model availability: configured model accepted; unknown model rejected", flush=True)


def _session_state_validation(temp_root: Path) -> None:
    from atlas.engine.session_sync import append_session_message, restore_session_snapshot

    home = temp_root / "session-db"
    summary = "W6 invalid snapshot marker"
    manifest = {
        "schema_version": 1, "kind": "context_compaction",
        "created_at": "2026-10-23T12:00:00+00:00", "method": "summary",
        "boundary_watermark": 1, "source_message_count": 1,
        "source_first_message_id": "first", "source_last_message_id": "last",
        "summary_sha256": hashlib.sha256(summary.encode()).hexdigest(),
        "summary_chars": len(summary), "state": {"open_tool_call_ids": "invalid"},
    }
    append_session_message(home, "w6-invalid-session", "assistant", summary,
                           {"_atlas_session_snapshot": manifest, "_compressed_summary": True})
    try:
        restore_session_snapshot(home, "w6-invalid-session")
    except ValueError as exc:
        if "Invalid session snapshot" not in str(exc):
            raise
    else:
        raise RuntimeError("invalid persisted session state was accepted")
    print("8 session state boundary: invalid open tool IDs rejected", flush=True)


async def main() -> None:
    root_value = os.environ.get("ATLAS_ROOT")
    if not root_value or not Path(root_value).is_dir():
        raise RuntimeError("ATLAS_ROOT must point at the configured local Atlas test environment")
    manager = _manager()
    model = "deepseek-v4.1-flash"
    if not any(item.get("id") == model or item.get("litellm_model") == model
               for item in manager.list_models()):
        raise RuntimeError("configured deepseek-v4.1-flash route is unavailable")
    from types import SimpleNamespace
    agent = SimpleNamespace(_model_router=manager.model_router, source="foreground")
    with tempfile.TemporaryDirectory(prefix="atlas-w6-smoke-") as directory:
        temp_root = Path(directory)
        await _history_repair(agent)
        await _agent_crash_budget()
        _timeout_and_connection_recovery()
        await _protocol_and_compression(temp_root)
        await _command_file_cwd(temp_root)
        _model_capacity_and_availability()
        _session_state_validation(temp_root)
    print("W6 LIVE SMOKE PASS")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as exc:
        reason = " ".join(str(exc).split())
        reason = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+", "[REDACTED]", reason)
        reason = re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|authorization|bearer)\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]", reason,
        )
        print(f"FAIL: {type(exc).__name__}: {reason[:500]}", flush=True)
        raise SystemExit(1)
