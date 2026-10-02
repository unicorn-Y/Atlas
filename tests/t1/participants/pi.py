from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import uuid
from typing import Any

from .base import RunContext, RunOutcome
from .common import CliAdapter, empty_usage, kill_process_tree, redact, redact_events


class PiAdapter(CliAdapter):
    name = "pi"
    executable_name = "pi"

    def build_command(self, context: RunContext) -> list[str]:
        command = self._prefix() + ["--mode", "rpc", "--no-session"]
        if context.model:
            command += ["--model", context.model]
        return command

    def run_once(self, context: RunContext) -> RunOutcome:
        if not context.scenario:
            # A single prompt through RPC still uses the same native protocol.
            return self._run_scenario(context, None)
        return self._run_scenario(context, None)

    def run_scenario(self, context: RunContext, controller) -> RunOutcome:
        return self._run_scenario(context, controller)

    def _run_scenario(self, context: RunContext, controller) -> RunOutcome:
        start = time.monotonic()
        cmd = self.build_command(context)
        events: list[dict[str, Any]] = []
        stderr_parts: list[str] = []
        records: queue.Queue[bytes | None] = queue.Queue()
        unsupported: list[str] = []
        try:
            process = subprocess.Popen(cmd, cwd=context.workspace, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            return RunOutcome(None, error=f"launch_error: {type(exc).__name__}", duration_ms=0)
        self._process = process
        assert process.stdin and process.stdout and process.stderr

        def read_stdout():
            try:
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    records.put(line.rstrip(b"\r\n"))
            finally:
                records.put(None)

        def read_stderr():
            for line in iter(process.stderr.readline, b""):
                stderr_parts.append(line.decode("utf-8", "replace"))

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        pending_responses: dict[str, dict[str, Any]] = {}
        pending_steps: list[tuple[int, dict[str, Any]]] = []
        sent_steps: set[int] = set()
        settled = False
        stats_requested = False
        first_step = next((step for step in (controller.steps if controller is not None else [])
                           if isinstance(step, dict)), None)
        command_id = 0
        done = False
        failed: str | None = None
        current_event = None

        def send(kind: str, text: str | None = None, *, step: dict[str, Any] | None = None):
            nonlocal command_id
            command_id += 1
            rid = f"t1-{command_id}"
            packet: dict[str, Any] = {"id": rid, "type": kind}
            if text is not None:
                packet["message"] = text
            if kind == "prompt" and step is not None and step.get("action") == "prompt" and events:
                packet["streamingBehavior"] = "followUp"
            process.stdin.write((json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8"))
            process.stdin.flush()
            pending_responses[rid] = {"kind": kind, "step": step}
            return rid

        def deliver(step: dict[str, Any], *, streaming: bool, index: int):
            nonlocal settled
            if index in sent_steps:
                return
            action = str(step.get("action", "prompt"))
            msg = step.get("text")
            if action in {"prompt", "context"}:
                kind = "prompt"
            elif action == "steer":
                kind = "steer"
            else:
                unsupported.append(action)
                sent_steps.add(index)
                return
            if not isinstance(msg, str):
                unsupported.append(f"{action}:missing_text")
                sent_steps.add(index)
                return
            if action == "prompt" and streaming:
                kind = "follow_up"
            send(kind, msg, step=step)
            sent_steps.add(index)
            settled = False

        # Start the task prompt over the real RPC protocol.
        if first_step is not None and first_step.get("action") in {"prompt", "context"}:
            send("prompt", str(first_step.get("text", "")), step=first_step)
            sent_steps.add(next(i for i, item in enumerate(controller.steps) if item is first_step))
        else:
            send("prompt", context.prompt)
        deadline = start + context.timeout_seconds
        while time.monotonic() < deadline and not done:
            elapsed = time.monotonic() - start
            try:
                raw = records.get(timeout=0.04)
            except queue.Empty:
                raw = b""
            if raw is None:
                done = True
                break
            if raw:
                try:
                    record = json.loads(raw.decode("utf-8", "replace"))
                except (ValueError, UnicodeDecodeError):
                    continue
                events.append(record)
                current_event = str(record.get("type") or "")
                if controller is not None:
                    controller.emit(record)
                if record.get("type") == "response":
                    rid = record.get("id")
                    pending = pending_responses.pop(rid, None)
                    if pending and pending.get("step") is not None and record.get("success"):
                        step = pending["step"]
                        if hasattr(controller, "record_delivery"):
                            controller.record_delivery(step, {"response": record, "protocol": "pi-rpc"})
                if record.get("type") == "agent_settled":
                    settled = True
            if controller is not None:
                due = controller.due_steps(event=current_event, elapsed_seconds=elapsed)
                for index, step in enumerate(controller.steps):
                    if isinstance(step, dict) and index not in sent_steps and step in due:
                        pending_steps.append((index, step))
                for index, item in list(pending_steps):
                    if index in sent_steps or (not item.get("trigger") and not settled):
                        continue
                    # Pi RPC has no approval/checkpoint/rewind command.
                    if item.get("action") in {"approve", "plan", "checkpoint", "rewind"}:
                        unsupported.append(str(item["action"]))
                        sent_steps.add(index)
                        pending_steps.remove(item)
                        continue
                    deliver(item, streaming=not settled, index=index)
                    pending_steps.remove((index, item))
            if settled and not stats_requested:
                all_steps_done = controller is None or all(
                    not isinstance(step, dict) or index in sent_steps
                    for index, step in enumerate(controller.steps)
                )
                if all_steps_done:
                    send("get_session_stats")
                    stats_requested = True
            elif settled and stats_requested and not pending_responses:
                try:
                    process.stdin.close()
                except OSError:
                    pass
                done = True
        if not done and time.monotonic() >= deadline:
            failed = "timeout"
            kill_process_tree(process)
        else:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        self._process = None
        events = redact_events(events)
        stdout = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
        stdout, stderr = redact(stdout, "".join(stderr_parts))
        if failed:
            return RunOutcome(None, stdout, stderr, events, (time.monotonic() - start) * 1000,
                              failed, unsupported)
        if controller is not None:
            for index, step in enumerate(controller.steps):
                if isinstance(step, dict) and index not in sent_steps:
                    unsupported.append(str(step.get("action", "prompt")))
        exit_code = process.returncode
        return RunOutcome(exit_code, stdout, stderr, events,
                          (time.monotonic() - start) * 1000, unsupported=sorted(set(unsupported)))

    def parse_usage(self, outcome: RunOutcome):
        result = empty_usage()
        for event in reversed(outcome.events):
            if event.get("type") == "response" and event.get("command") == "get_session_stats" and event.get("success"):
                data = event.get("data", {})
                tokens = data.get("tokens", {})
                result.update({"tool_calls": data.get("toolCalls"), "turns": data.get("assistantMessages"),
                               "input_tokens": tokens.get("input"), "output_tokens": tokens.get("output"),
                               "cached_tokens": tokens.get("cacheRead"), "cost_usd": data.get("cost")})
                return result
        return result

    def supports(self, capability: str) -> bool:
        return capability in {"multi_round", "steer", "context", "compaction"} or super().supports(capability)
