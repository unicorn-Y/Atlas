from __future__ import annotations

from .base import RunContext, RunOutcome
import json
import queue
import subprocess
import threading
import time
from typing import Any

from .common import CliAdapter, kill_process_tree, redact, redact_events, usage_from_events


class ClaudeAdapter(CliAdapter):
    name = "claude"
    executable_name = "claude"

    def build_command(self, context: RunContext) -> list[str]:
        command = self._prefix() + ["-p", "--output-format", "stream-json", "--verbose"]
        if context.model:
            command += ["--model", context.model]
        command += [context.prompt]
        return command

    def run_once(self, context: RunContext) -> RunOutcome:
        return self._run(context, self.build_command(context))

    def run_scenario(self, context: RunContext, controller) -> RunOutcome:
        """Use Claude's documented stream-json input protocol for live user turns."""
        command = self._prefix() + ["-p", "--input-format", "stream-json",
                                    "--output-format", "stream-json", "--verbose"]
        steps = controller.steps if controller is not None else []
        first_step = steps[0] if steps and isinstance(steps[0], dict) else None
        if first_step and first_step.get("action") == "plan":
            command += ["--permission-mode", "plan"]
        if context.model:
            command += ["--model", context.model]
        start = time.monotonic()
        events: list[dict[str, Any]] = []
        unsupported: list[str] = []
        lines: queue.Queue[bytes | None] = queue.Queue()
        pending: dict[int, dict[str, Any]] = {}
        sent: set[int] = set()
        try:
            process = subprocess.Popen(command, cwd=context.workspace, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            return RunOutcome(None, error=f"launch_error: {type(exc).__name__}")
        self._process = process
        assert process.stdin and process.stdout and process.stderr
        stderr_parts: list[str] = []
        def read_stdout():
            try:
                for line in iter(process.stdout.readline, b""):
                    lines.put(line.rstrip(b"\r\n"))
            finally:
                lines.put(None)
        def read_stderr():
            stderr_parts.extend(line.decode("utf-8", "replace") for line in iter(process.stderr.readline, b""))
        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        def send(text: str, step: dict[str, Any] | None = None, index: int = -1):
            item = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
            process.stdin.write((json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8"))
            process.stdin.flush()
            if step is not None:
                sent.add(index)
                if hasattr(controller, "record_delivery"):
                    controller.record_delivery(step, {"protocol": "claude-stream-json", "stdin_accepted": True})
        if first_step is not None and isinstance(first_step.get("text"), str):
            send(first_step["text"], first_step, 0)
        else:
            send(context.prompt)
        deadline = start + context.timeout_seconds
        should_close = False
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - start
            try:
                raw = lines.get(timeout=.04)
            except queue.Empty:
                raw = b""
            elapsed = time.monotonic() - start
            if raw is None:
                break
            event_type = None
            if raw:
                try:
                    event = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
                    event_type = event.get("type")
                    if controller is not None:
                        controller.emit(event)
            if controller is not None:
                due = controller.due_steps(event=str(event_type) if event_type else None,
                                           elapsed_seconds=elapsed)
                for index, step in enumerate(controller.steps):
                    if index in sent or not isinstance(step, dict) or step not in due:
                        continue
                    pending[index] = step
                for index, step in list(pending.items()):
                    action = step.get("action")
                    if action == "steer" and isinstance(step.get("text"), str):
                        # stream-json explicitly accepts user messages while processing.
                        send(step["text"], step, index)
                        pending.pop(index, None)
                    else:
                        if action not in {"prompt", "context"}:
                            # This CLI protocol has no approval, checkpoint, or rewind command.
                            unsupported.append(str(action))
                            pending.pop(index, None)
            if event_type == "result":
                # Preserve turn boundaries: one additional user turn follows each result.
                sent_new_turn = False
                queued = next(((i, step) for i, step in pending.items()
                               if step.get("action") in {"prompt", "context"}
                               and isinstance(step.get("text"), str)), None)
                if queued:
                    index, step = queued
                    send(step["text"], step, index)
                    pending.pop(index, None)
                    sent_new_turn = True
                all_done = controller is None or all(
                    not isinstance(step, dict) or index in sent or str(step.get("action")) in unsupported
                    for index, step in enumerate(controller.steps)
                )
                latest_trigger = max((float(step.get("trigger", {}).get("after_seconds", 0))
                                      for step in (controller.steps if controller is not None else [])
                                      if isinstance(step, dict) and isinstance(step.get("trigger"), dict)), default=0)
                if all_done and not sent_new_turn and elapsed >= latest_trigger:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
                    should_close = True
                    # Continue draining the native result stream until process exit.
                    if process.poll() is not None:
                        break
            if event_type == "result" and controller is None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
                should_close = True
        if process.poll() is None:
            kill_process_tree(process)
            stdout_bytes, stderr_bytes = process.communicate()
            error = "timeout" if not should_close else None
        else:
            stdout_bytes, stderr_bytes = process.communicate()
            error = None
        self._process = None
        # Events are retained structurally; the native text stream is preserved separately.
        events = redact_events(events)
        stdout = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
        if stdout_bytes:
            stdout = stdout or stdout_bytes.decode("utf-8", "replace")
        stdout, stderr = redact(stdout, "".join(stderr_parts) + stderr_bytes.decode("utf-8", "replace"))
        if controller is not None:
            for index, step in enumerate(controller.steps):
                if isinstance(step, dict) and index not in sent and str(step.get("action")) not in unsupported:
                    unsupported.append(str(step.get("action", "unknown")))
        return RunOutcome(None if error else process.returncode, stdout, stderr, events,
                          (time.monotonic() - start) * 1000, error, sorted(set(unsupported)))

    def parse_usage(self, outcome: RunOutcome):
        return usage_from_events(outcome, usage_paths=(("usage",), ("message", "usage")),
                                 tool_types=("tool_use", "tool_call"), turn_types=("result",))

    def supports(self, capability: str) -> bool:
        return capability in {"multi_round", "steer", "context", "plan", "subagents"} or super().supports(capability)
