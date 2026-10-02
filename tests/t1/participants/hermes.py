from __future__ import annotations

import json
import re
import time
from dataclasses import replace

from .base import RunContext, RunOutcome
from .common import CliAdapter, usage_from_events


class HermesAdapter(CliAdapter):
    name = "hermes"
    executable_name = "hermes"

    def build_command(self, context: RunContext) -> list[str]:
        command = self._prefix() + ["chat", "--oneshot", "--quiet", "--format", "stream-json", "--in", str(context.workspace)]
        if context.model:
            command += ["--model", context.model]
        command += ["--query", context.prompt]
        return command

    def run_once(self, context: RunContext) -> RunOutcome:
        return self._run(context, self.build_command(context))

    def run_scenario(self, context: RunContext, controller):
        start = time.monotonic()
        events = []
        stdout_parts = []
        stderr_parts = []
        unsupported = []
        session_id = None
        steps = controller.steps if controller is not None else []
        first_step = steps[0] if steps and isinstance(steps[0], dict) else None
        turns = [str(first_step.get("text", "")) if first_step and isinstance(first_step.get("text"), str) else context.prompt]
        step_map = []
        if controller is not None:
            if first_step is not None:
                step_map.append((0, 0, first_step))
            for index, step in enumerate(controller.steps[1:] if first_step is not None else controller.steps,
                                          start=1 if first_step is not None else 0):
                if not isinstance(step, dict):
                    continue
                if step.get("action") in {"prompt", "context"} and isinstance(step.get("text"), str):
                    turns.append(step["text"])
                    step_map.append((len(turns) - 1, index, step))
                else:
                    unsupported.append(str(step.get("action", "unknown")))
        deadline = start + context.timeout_seconds
        for turn_index, prompt in enumerate(turns):
            command = self._prefix() + ["chat", "--oneshot", "--quiet", "--format", "stream-json", "--in", str(context.workspace)]
            if context.model:
                command += ["--model", context.model]
            if session_id:
                command += ["--resume", session_id]
            command += ["--query", prompt]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return RunOutcome(None, "\n".join(stdout_parts), "\n".join(stderr_parts), events,
                                  (time.monotonic() - start) * 1000, "timeout", sorted(set(unsupported)))
            outcome = self._run(replace(context, timeout_seconds=remaining), command)
            stdout_parts.append(outcome.stdout)
            stderr_parts.append(outcome.stderr)
            events.extend(outcome.events)
            if outcome.error:
                return RunOutcome(outcome.exit_code, "\n".join(stdout_parts), "\n".join(stderr_parts), events,
                                  (time.monotonic() - start) * 1000, outcome.error, sorted(set(unsupported)))
            if outcome.exit_code not in (0, None):
                return RunOutcome(outcome.exit_code, "\n".join(stdout_parts), "\n".join(stderr_parts), events,
                                  (time.monotonic() - start) * 1000,
                                  f"hermes_exit:{outcome.exit_code}", sorted(set(unsupported)))
            if controller is not None:
                controller.emit({"type": "hermes_turn", "turn": turn_index + 1, "exit_code": outcome.exit_code})
                mapped = next((item for item in step_map if item[0] == turn_index), None)
                if mapped and hasattr(controller, "record_delivery"):
                    controller.record_delivery(mapped[2], {"protocol": "hermes-resume", "turn": turn_index + 1})
            for event in outcome.events:
                if event.get("session_id"):
                    session_id = str(event["session_id"])
                if event.get("type") == "result" and event.get("session_id"):
                    session_id = str(event["session_id"])
            if not session_id:
                match = re.search(r"(?i)(?:session(?:_id)?\s*[:=]\s*)([A-Za-z0-9_-]{8,})", outcome.stdout + "\n" + outcome.stderr)
                if match:
                    session_id = match.group(1)
            if turn_index + 1 < len(turns) and not session_id:
                unsupported.append("multi_round:no_native_session_id")
                break
        return RunOutcome(0, "\n".join(stdout_parts), "\n".join(stderr_parts), events,
                          (time.monotonic() - start) * 1000, unsupported=sorted(set(unsupported)))

    def parse_usage(self, outcome: RunOutcome):
        return usage_from_events(outcome, usage_paths=(("usage",), ("message", "usage")),
                                 tool_types=("tool_call", "tool_use"), turn_types=("result",))

    def supports(self, capability: str) -> bool:
        return capability in {"multi_round", "context", "subagents"} or super().supports(capability)
