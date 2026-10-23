"""Real DeepSeek validation of W2 model/tool handoffs and local tool contracts.

Run with ATLAS_ROOT pointing at the private Atlas configuration. Secrets are only
read through ModelManager and are never copied, printed, or written to this repo.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _manager() -> Any:
    from atlas.models import ModelManager

    class ReadOnlyModelManager(ModelManager):
        def set_api_mode_probe(self, provider_id: str, probe: dict[str, Any]) -> None:
            return None

        def credential_pool(self, provider_id: str) -> None:
            return None

    return ReadOnlyModelManager()


async def _complete(agent: Any, model: str, messages: list[dict[str, Any]],
                    tools: list[dict[str, Any]], label: str) -> Any:
    from atlas.kernel.model_call import complete_stream

    result = await complete_stream(agent, model, messages, tools,
                                   max_output_tokens=512, max_retries=2)
    names = [str(call.get("name") or "") for call in result.tool_calls]
    print(f"{label}: provider={result.provider} tool_calls={names}", flush=True)
    return result


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": f"Fixture tool {name}.", "parameters": arguments,
    }}


def _args(call: dict[str, Any]) -> dict[str, Any]:
    value = call.get("args")
    if isinstance(value, dict):
        return value
    return {}


async def _model_tool_paths(agent: Any, model: str) -> None:
    from atlas.kernel.tools import ToolScheduler, validate_tool_arguments

    parallel_tools = [
        _call("w2_slow", {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}),
        _call("w2_fast", {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}),
    ]
    response = await _complete(agent, model, [
        {"role": "system", "content": "You must issue the two available tool calls together, one for each tool, then no prose."},
        {"role": "user", "content": "Call w2_slow and w2_fast now. Use label='smoke'."},
    ], parallel_tools, "parallel tool request")
    if {call.get("name") for call in response.tool_calls} != {"w2_slow", "w2_fast"}:
        raise RuntimeError("live model did not call both parallel fixture tools")
    async def dispatch(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "w2_slow":
            await asyncio.sleep(5)
        else:
            await asyncio.sleep(0.03)
        return {"data": {"tool": name, "id": call_id}}

    scheduler = ToolScheduler(dispatch, max_concurrency=3)
    calls = [{"id": str(call.get("id") or index), "function": {
        "name": call["name"], "arguments": __import__("json").dumps(_args(call)),
    }} for index, call in enumerate(response.tool_calls)]
    task = asyncio.create_task(scheduler.run(calls))
    await asyncio.sleep(0.15)
    task.cancel()
    settled = await asyncio.gather(task, return_exceptions=True)
    # Caller cancellation follows the same coordinator path as a user interrupt;
    # each invocation gets a terminal cancellation result and preserves order.
    results = settled[0] if settled and isinstance(settled[0], list) else []
    if len(results) != len(calls) or any(item.receipt.state == "running" for item in results):
        raise RuntimeError("parallel cancellation left a call without a terminal result")
    print("parallel cancellation: caller interrupted the live model's two-tool batch", flush=True)

    execution_schema = {"type": "object", "properties": {"count": {"type": "integer"}},
                        "required": ["count"], "additionalProperties": False}
    advertised_schema = {"type": "object", "properties": {"count": {"type": "string"}},
                         "required": ["count"], "additionalProperties": False}
    repair_tool = [_call("w2_repair", advertised_schema)]
    first = await _complete(agent, model, [
        {"role": "system", "content": "Call w2_repair with count set to the string 'wrong'."},
        {"role": "user", "content": "Invoke w2_repair with count='wrong'."},
    ], repair_tool, "schema violation request")
    if not first.tool_calls:
        raise RuntimeError("live model returned no schema fixture tool call")
    call = first.tool_calls[0]
    bad_args = _args(call)
    error = validate_tool_arguments("w2_repair", bad_args, execution_schema)
    if error is None or "retry" not in error.lower():
        raise RuntimeError("schema validation did not yield actionable retry feedback")
    history = [
        {"role": "system", "content": "Correct the previous tool call using its schema error."},
        {"role": "user", "content": "Call w2_repair with count=2."},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": str(call.get("id") or "w2-repair"), "type": "function",
            "function": {"name": "w2_repair", "arguments": __import__("json").dumps(bad_args)},
        }]},
        {"role": "tool", "tool_call_id": str(call.get("id") or "w2-repair"),
         "name": "w2_repair", "content": error},
    ]
    fixed = await _complete(agent, model, history, [_call("w2_repair", execution_schema)], "schema retry request")
    if not fixed.tool_calls or validate_tool_arguments("w2_repair", _args(fixed.tool_calls[0]), execution_schema):
        raise RuntimeError("model did not correct its arguments after validation feedback")
    print("schema retry: invalid invocation returned model-facing error, correction accepted", flush=True)

    # The message remains queued throughout the slow tool and is exposed for the
    # immediately following model request, after the tool receipt has completed.
    steer_tool = [_call("w2_wait", {"type": "object", "properties": {}, "additionalProperties": False})]
    wait_call = await _complete(agent, model, [
        {"role": "system", "content": "Call w2_wait once and make no other response."},
        {"role": "user", "content": "Call w2_wait now."},
    ], steer_tool, "steering tool request")
    if not wait_call.tool_calls:
        raise RuntimeError("live model did not issue the steering fixture tool")
    visible: list[str] = []
    steer_queue: asyncio.Queue[str] = asyncio.Queue()
    finished = asyncio.Event()

    async def slow_tool() -> None:
        await asyncio.sleep(0.3)
        finished.set()

    active_tool = asyncio.create_task(slow_tool())
    await steer_queue.put("After the tool finishes, report the marker W2-STEER-OK.")
    if steer_queue.empty() or visible:
        raise RuntimeError("steer became visible while a tool was still running")
    await active_tool
    if not finished.is_set():
        raise RuntimeError("fixture tool failed to finish")
    visible.append(await steer_queue.get())
    answer = await _complete(agent, model, [
        {"role": "user", "content": visible[0]},
    ], [], "post-tool queued message")
    if "W2-STEER-OK" not in answer.text:
        raise RuntimeError("model did not see the queued message after the tool finished")
    print("queued steering: injected after tool completion and observed by live model", flush=True)


async def _command_and_environment(root: Path) -> None:
    from atlas.kernel.exec import ExecManager
    from atlas.tools.local_execution import LocalExecutionRuntime

    runtime = LocalExecutionRuntime()
    runtime.permission_mode = "full_access"
    events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def dispatch(_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return await runtime.call_tool("local_process", args, run_id="w2-live")

    old_key = os.environ.get("OPENAI_API_KEY"); old_brave = os.environ.get("BRAVE_API_KEY")
    os.environ["OPENAI_API_KEY"] = "sentinel-never-print"; os.environ["BRAVE_API_KEY"] = "brave-sentinel"
    try:
        with tempfile.TemporaryDirectory(prefix="atlas-w2-live-", dir=root) as directory:
            manager = ExecManager(dispatch, output_dir=directory, run_id="w2-live",
                                  local_runtime=runtime, event_queue=events)
            result = await manager.execute("terminal", {
                "command": "python -c \"import time; time.sleep(20); print('W2-COMMAND-DONE')\"",
                "cwd": str(root), "timeout": 45,
            })
            if not result.get("data", {}).get("backgrounded"):
                raise RuntimeError("20-second command did not auto-background")
            execution_id = str(result["data"]["execution_id"])
            print("long command: auto-backgrounded at 15 seconds", flush=True)
            while True:
                result = await manager.poll(execution_id)
                if result.get("data", {}).get("state") != "running":
                    break
                await asyncio.sleep(0.3)
            if result["data"].get("state") != "completed" or "W2-COMMAND-DONE" not in result["data"].get("output", ""):
                raise RuntimeError("background command failed to complete or return output")
            print("long command: output polled and process completed", flush=True)
            await manager.shutdown()

        env_result = await runtime.call_tool("local_process", {
            "action": "start", "command": "python -c \"import os; print('present=' + str('OPENAI_API_KEY' in os.environ).lower() + ' brave=' + str('BRAVE_API_KEY' in os.environ).lower())\"",
            "cwd": str(root), "shell": "auto", "detached": False,
        }, run_id="w2-live")
        if env_result.get("is_error"):
            raise RuntimeError("environment fixture command failed")
        await asyncio.sleep(0.4)
        execution_id = str((env_result.get("data") or {}).get("execution_id") or "")
        status = await runtime.call_tool("local_process", {"action": "status", "execution_id": execution_id}, run_id="w2-live")
        output = await runtime.call_tool("local_process", {"action": "read", "execution_id": execution_id,
                                      "stream": "stdout", "offset": 0, "limit": 1000}, run_id="w2-live")
        text = str((output.get("data") or {}).get("text") or "")
        if "present=false" not in text:
            raise RuntimeError("subprocess inherited the model API key")
        if "brave=true" not in text:
            raise RuntimeError("subprocess lost a non-model API key (BRAVE_API_KEY) it should inherit")
        await runtime.shutdown()
        print("child environment: model API key absent, BRAVE_API_KEY kept", flush=True)
    finally:
        if old_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = old_key
        if old_brave is None:
            os.environ.pop("BRAVE_API_KEY", None)
        else:
            os.environ["BRAVE_API_KEY"] = old_brave


async def _file_edits(root: Path) -> None:
    from atlas.kernel.edit import EditManager

    with tempfile.TemporaryDirectory(prefix="atlas-w2-edit-", dir=root) as directory:
        path = Path(directory) / "legacy.txt"
        path.write_bytes("第一行\r\n第二行\r\n".encode("gbk"))
        second = Path(directory) / "second.txt"
        second.write_text("old\n", encoding="utf-8")
        manager = EditManager(directory)
        manager.read_file("legacy.txt", encoding="gbk")
        manager.read_file("second.txt")
        result = manager.call_tool("edit", {"path": "legacy.txt", "old_string": "第二行", "new_string": "替换行"})
        if result.get("is_error") or b"\r\n" not in path.read_bytes() or "替换行" not in path.read_bytes().decode("gbk"):
            raise RuntimeError("GBK/CRLF edit did not preserve source encoding and line endings")
        before = path.read_bytes()
        patch = ("*** Begin Patch\n*** Update File: legacy.txt\n@@\n-替换行\n+改动\n"
                 "*** Update File: second.txt\n@@\n-old\n+new\n*** End Patch")
        original_write = manager._atomic_write

        def fail_second(target: Path, raw: bytes, previous: Any) -> None:
            if target.name == "second.txt":
                raise OSError("fixture write failure")
            original_write(target, raw, previous)

        manager._atomic_write = fail_second
        failed = manager.call_tool("apply_patch", {"patch": patch})
        if (not failed.get("is_error") or "all files rolled back" not in failed["data"]["error"]
                or path.read_bytes() != before or second.read_text(encoding="utf-8") != "old\n"):
            raise RuntimeError("failed multi-file patch did not roll back its earlier write")
    print("file edit: GBK/CRLF preserved and failed multi-file patch rolled back", flush=True)


async def _run(model_override: str | None) -> None:
    root_value = os.environ.get("ATLAS_ROOT")
    if not root_value:
        raise RuntimeError("ATLAS_ROOT is required")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError("ATLAS_ROOT does not exist")
    manager = _manager()
    model = model_override or manager.current_model
    route = next((item for item in manager.list_models()
                  if item.get("id") == model or item.get("litellm_model") == model), None)
    if route is None:
        raise RuntimeError(f"live model route not found: {model}")
    if "deepseek" not in str(route.get("litellm_model") or model).lower():
        raise RuntimeError("W2 live smoke must run against configured deepseek-v4.1-flash")
    agent = SimpleNamespace(_model_router=manager.model_router, source="foreground")
    print(f"live model route: {route.get('id')}", flush=True)
    await _model_tool_paths(agent, model)
    await _command_and_environment(root)
    await _file_edits(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="override the configured DeepSeek model id")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.model))
    except BaseException as exc:
        reason = " ".join(str(exc).split())
        reason = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+", "[REDACTED]", reason)
        reason = re.sub(r"(?i)(api[_-]?key|access[_-]?token|authorization|bearer)\s*[:=]\s*[^\s,;]+",
                        r"\1=[REDACTED]", reason)
        print(f"FAIL: {type(exc).__name__}: {reason[:500]}", flush=True)
        return 1
    print("W2 LIVE SMOKE PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
