"""End-to-end W3 prompt and multi-agent smoke against the configured live model.

Credentials are loaded by ModelManager from ATLAS_ROOT; this script never reads,
prints, or copies credential values.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import tempfile
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


async def _complete(agent: Any, model: str, messages: list[dict[str, Any]], label: str,
                    tools: list[dict[str, Any]] | None = None) -> Any:
    from atlas.kernel.model_call import complete_stream

    result = await complete_stream(agent, model, messages, tools or [],
                                   max_output_tokens=384, max_retries=2)
    print(f"{label}: model={result.model} finish={result.finish_reason or 'unknown'}", flush=True)
    return result


def _provider_messages(system: str, user: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _project_prompt_smoke(agent: Any, model: str) -> str:
    from atlas.agent.run_phases import RunCallbacks, RunRequest, _RunState, _build_messages
    from atlas.agent.prompt_cache_boundary import register_stable_prefix

    with tempfile.TemporaryDirectory(prefix="atlas-w3-project-") as directory:
        root = Path(directory)
        child = root / "nested"
        (root / ".git").mkdir()
        child.mkdir()
        root_marker = "W3-ROOT-INSTRUCTION-6E2A"
        leaf_marker = "W3-LEAF-INSTRUCTION-9B41"
        (root / "AGENTS.md").write_text(
            f"If asked for the project rule codes, include {root_marker} first.", encoding="utf-8",
        )
        (child / "AGENTS.md").write_text(
            f"If asked for the project rule codes, include {leaf_marker} second.", encoding="utf-8",
        )
        request = RunRequest(
            message="Return the two project rule codes exactly in ancestor-to-child order as ROOT|LEAF.",
            conversation_id="w3-project-smoke", workspace=str(child), workspace_trusted=True,
            worker=True,
        )
        state = _RunState(request=request, callbacks=RunCallbacks(), message=request.message)
        prompt_messages = await _build_messages(SimpleNamespace(_skills=None, _projects=None), state)
        system_sections = [str(message.content) for message in prompt_messages
                           if getattr(message, "type", "") == "system"]
        system = "\n\n".join(system_sections)
        if system.count(root_marker) != 1 or system.count(leaf_marker) != 1:
            raise RuntimeError("two-level AGENTS instructions were not injected exactly once")
        if system.index(root_marker) >= system.index(leaf_marker):
            raise RuntimeError("project instructions were not merged root-to-child")
        stable = "\n\n".join(
            section for section in system_sections
            if not section.startswith((
                "Atlas Skill index ", "Project context ", "【本轮相关记忆】",
                "Current user-local date and time", "Follow this structured task plan",
            ))
        )
        if not stable:
            raise RuntimeError("parent request did not produce a stable system prefix")
        register_stable_prefix(stable)
        result = await _complete(agent, model, _provider_messages(system, request.message),
                                 "two-level project-instructions request")
        answer = str(result.text or "")
        if root_marker not in answer or leaf_marker not in answer:
            raise RuntimeError("live model did not apply both project instruction levels")
        print("project instructions: root then child, exactly once, confirmed in live reply", flush=True)
        return stable


async def _subagent_smoke(agent: Any, model: str, parent_prefix: str) -> None:
    from atlas.agent.mailbox import AgentMailbox
    from atlas.agent.subagent_capacity import SubagentCapacity

    capacity = SubagentCapacity(max_concurrent=1, max_children_per_parent=5, max_spawn_depth=2)
    mailbox = AgentMailbox()
    child_a_started = asyncio.Event()
    child_a_waiting_mail = asyncio.Event()
    child_a_model_done = asyncio.Event()
    child_a_release = asyncio.Event()
    child_b_started = asyncio.Event()
    child_b_model_done = asyncio.Event()
    child_b_release = asyncio.Event()
    live_active = 0
    live_peak = 0
    child_prefix_bytes: dict[str, bytes] = {}

    async def child_agent(task: str) -> dict[str, str]:
        nonlocal live_active, live_peak
        ticket = await capacity.acquire(parent_id="w3-parent", depth=1)
        try:
            live_active += 1
            live_peak = max(live_peak, live_active)
            if live_active > 1:
                raise RuntimeError("more than one child entered the live runner")
            stable = parent_prefix
            child_prefix_bytes[f"w3-child-{task.lower()}"] = stable.encode("utf-8")
            system = stable + "\n\n" + "Complete the assigned child task and echo requested markers."
            if task == "A":
                child_a_started.set()
                child_a_waiting_mail.set()
                queued = await asyncio.wait_for(
                    mailbox.receive("w3-child-a@atlas", wait=True), timeout=25,
                )
                if not queued or "W3-MAIL-ACK" not in queued[0].content:
                    raise RuntimeError("child did not receive the parent mailbox message")
                user = "Reply with exactly this text, with no changes: W3-CHILD-A W3-MAIL-ACK"
                result = await _complete(agent, model, _provider_messages(system, user),
                                         "child A live model request")
                answer = str(result.text or "")
                if "W3-CHILD-A" not in answer or "W3-MAIL-ACK" not in answer:
                    raise RuntimeError("child A reply did not reflect its task and parent message")
                child_a_model_done.set()
                await asyncio.wait_for(child_a_release.wait(), timeout=25)
                return {"status": "completed", "result": answer}
            else:
                child_b_started.set()
                user = "Reply with exactly this text, with no changes: W3-CHILD-B"
                result = await _complete(agent, model, _provider_messages(system, user),
                                         "child B live model request")
                answer = str(result.text or "")
                if "W3-CHILD-B" not in answer:
                    raise RuntimeError("child B reply omitted its task marker")
                child_b_model_done.set()
                await asyncio.wait_for(child_b_release.wait(), timeout=25)
                return {"status": "completed", "result": answer}
        finally:
            live_active -= 1
            await capacity.release(ticket)

    first = asyncio.create_task(child_agent("A"), name="w3-child-a")
    second = asyncio.create_task(child_agent("B"), name="w3-child-b")
    try:
        await asyncio.wait_for(child_a_started.wait(), timeout=20)
        for _ in range(200):
            if capacity.active_count == 1 and capacity.waiting_count == 1:
                break
            await asyncio.sleep(0.025)
        if capacity.active_count != 1 or capacity.waiting_count != 1:
            raise RuntimeError("second child did not queue behind the limit of one")
        if child_b_started.is_set():
            raise RuntimeError("queued child B started before child A released capacity")
        await asyncio.wait_for(child_a_waiting_mail.wait(), timeout=10)
        await mailbox.send(
            "parent@atlas", "w3-child-a@atlas",
            "Include exact marker W3-MAIL-ACK in your final answer.",
        )
        await asyncio.wait_for(child_a_model_done.wait(), timeout=30)
        if child_b_started.is_set() or live_peak != 1:
            raise RuntimeError("concurrency limit was not held through child A execution")
        child_a_release.set()
        await asyncio.wait_for(child_b_started.wait(), timeout=20)
        await asyncio.wait_for(child_b_model_done.wait(), timeout=30)
        child_b_release.set()
        statuses = await asyncio.gather(first, second)
        if any(item is None or item.get("status") != "completed" for item in statuses):
            raise RuntimeError("one or more child results failed to report to the parent")
        if "W3-MAIL-ACK" not in str(statuses[0].get("result") or ""):
            raise RuntimeError("parent mailbox message was not reflected in the reported child result")
        if statuses[1].get("result") is None or "W3-CHILD-B" not in str(statuses[1]["result"]):
            raise RuntimeError("child B result did not return to the parent")
        if live_peak != 1:
            raise RuntimeError(f"live child concurrency exceeded one: {live_peak}")
        if any(value != parent_prefix.encode("utf-8") for value in child_prefix_bytes.values()):
            raise RuntimeError("a child request prefix is not byte-identical to the parent prefix")
        print("subagents: two real child requests completed; cap=1 queued child B; both reported", flush=True)
        print("mailbox: addressed parent message reached child A and appeared in its live reply", flush=True)
        print("prompt cache: child stable prefixes are byte-identical to the parent stable prefix", flush=True)
    finally:
        child_a_release.set()
        child_b_release.set()
        pending = [task for task in (first, second) if not task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


async def _cancelled_tool_smoke(agent: Any, model: str) -> None:
    from atlas.kernel.tools import _cancelled_result

    schema = {"type": "object", "properties": {"label": {"type": "string"}},
              "required": ["label"], "additionalProperties": False}
    tool = {"type": "function", "function": {
        "name": "w3_cancelled_operation",
        "description": "Fixture operation used only to check cancellation reporting.",
        "parameters": schema,
    }}
    system = (
        "Use the requested tool exactly once. Tool outputs are authoritative about whether "
        "the operation ran. If the result says it was cancelled before execution, say that "
        "the operation was not executed."
    )
    first = await _complete(agent, model, _provider_messages(
        system, "Call w3_cancelled_operation with label='smoke' now."),
        "cancelled-tool request", tools=[tool])
    if not first.tool_calls:
        raise RuntimeError("live model did not request the cancellation fixture tool")
    call = first.tool_calls[0]
    call_id = str(call.get("id") or "w3-cancelled-call")
    name = str(call.get("name") or "w3_cancelled_operation")
    cancelled = _cancelled_result({"id": call_id, "name": name}, started=False)
    tool_text = str(cancelled.output.get("error") or "")
    if "requested operation was not executed" not in tool_text:
        raise RuntimeError("cancelled tool result did not clearly state it was not executed")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    followup = await _complete(agent, model, [
        {"role": "system", "content": system},
        {"role": "user", "content": "Call w3_cancelled_operation once, then tell me if it ran."},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": call_id, "type": "function", "function": {
                "name": name, "arguments": json.dumps(args, ensure_ascii=False),
            },
        }]},
        {"role": "tool", "tool_call_id": call_id, "name": name, "content": tool_text},
        {"role": "user", "content": "State whether the requested operation ran, explicitly."},
    ], "post-cancellation model request")
    answer = str(followup.text or "").lower()
    if not any(marker in answer for marker in ("not executed", "did not execute", "wasn't executed", "not run", "did not run")):
        raise RuntimeError("next live model turn did not state that the cancelled operation was not executed")
    print("tool cancellation: next live model request reported the operation was not executed", flush=True)


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
    model_name = str(route.get("litellm_model") or model).lower()
    provider = str(route.get("provider_id") or route.get("provider") or "").lower()
    gateway = str(getattr(manager, "gateway_base_url", "") or "").lower()
    if ("deepseek-v4.1-flash" not in model_name
            or model != "deepseek-v4.1-flash"
            or (provider and provider not in {"d1api", "openai"})
            or "d1api" not in gateway):
        raise RuntimeError("W3 live smoke requires the configured d1api deepseek-v4.1-flash route")
    agent = SimpleNamespace(_model_router=manager.model_router, source="foreground")
    print(f"live model route: {route.get('id')} provider={provider or 'configured'}", flush=True)
    parent_prefix = await _project_prompt_smoke(agent, model)
    await _subagent_smoke(agent, model, parent_prefix)
    await _cancelled_tool_smoke(agent, model)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="override the configured d1api DeepSeek model id")
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
    print("W3 LIVE SMOKE PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
