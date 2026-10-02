from __future__ import annotations

import json
import os
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from .base import RunContext, RunOutcome
from .common import CliAdapter, empty_usage, redact, redact_events


class AtlasAdapter(CliAdapter):
    name = "atlas"
    executable_name = "atlas"

    def _base_url(self) -> str:
        return str(self.config.get("base_url") or os.environ.get("ATLAS_T1_URL") or "http://127.0.0.1:8765").rstrip("/")

    def availability(self):
        try:
            from websockets.sync.client import connect as _connect  # noqa: F401
        except ImportError:
            return {"available": False, "reason": "Python package websockets is unavailable"}
        parsed = urlparse(self._base_url())
        try:
            with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or (443 if parsed.scheme == "https" else 80)), timeout=0.25):
                pass
        except OSError:
            return {"available": False, "reason": f"Atlas backend is not reachable at {self._base_url()}"}
        return {"available": True, "reason": None, "url": self._base_url()}

    def build_command(self, context: RunContext) -> list[str]:
        return ["websocket", self._base_url() + "/ws/chat", "<run.start; prompt redacted>"]

    def run_once(self, context: RunContext) -> RunOutcome:
        return self._run_scenario(context, None)

    def run_scenario(self, context: RunContext, controller) -> RunOutcome:
        return self._run_scenario(context, controller)

    def _run_scenario(self, context: RunContext, controller) -> RunOutcome:
        from websockets.sync.client import connect
        start = time.monotonic()
        run_id = "t1-" + uuid.uuid4().hex
        initial_run_id = run_id
        conversation_id = "t1-" + uuid.uuid4().hex
        steps = (controller.steps if controller is not None else [])
        first_step = steps[0] if steps and isinstance(steps[0], dict) else None
        first_action = first_step.get("action") if first_step else None
        first_content = str(first_step.get("text", "")) if first_step else context.prompt
        has_plan = first_action == "plan"
        base = self._base_url()
        uri = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws/chat"
        token = os.environ.get("ATLAS_API_TOKEN")
        extra_headers = {"X-Atlas-Api-Token": token} if token else None
        def start_run(ws, content: str, current_id: str, *, plan_mode: bool = False):
            payload = {"type": "run.start", "run_id": current_id, "conversation_id": conversation_id,
                       "content": content, "workspace": str(context.workspace),
                       "mode": "plan" if plan_mode else "act"}
            if context.model:
                payload["model"] = context.model
            ws.send(json.dumps(payload, ensure_ascii=False))
        events: list[dict[str, Any]] = []
        stdout: list[str] = []
        unsupported: list[str] = []
        pending_delivery: dict[str, dict[str, Any]] = {}
        pending_steps: dict[int, dict[str, Any]] = {}
        sent_steps: set[int] = set()
        prompt_queue: list[tuple[int, dict[str, Any]]] = []
        initial_step_recorded = False
        if first_step is not None:
            sent_steps.add(0)
        deadline = start + context.timeout_seconds
        try:
            with connect(uri, open_timeout=min(5, context.timeout_seconds), close_timeout=1,
                         additional_headers=extra_headers, max_size=8 * 1024 * 1024) as ws:
                start_run(ws, first_content, run_id, plan_mode=has_plan)
                while time.monotonic() < deadline:
                    elapsed = time.monotonic() - start
                    # Poll elapsed-time triggers before blocking for the next server
                    # event, so an active run receives a due steer before completion.
                    if controller is not None:
                        due = controller.due_steps(event=None, elapsed_seconds=elapsed)
                        for index, step in enumerate(steps):
                            if index not in sent_steps and isinstance(step, dict) and step in due:
                                pending_steps[index] = step
                        for index, step in list(pending_steps.items()):
                            action = step.get("action")
                            if action == "steer":
                                event_id = "t1-steer-" + uuid.uuid4().hex
                                ws.send(json.dumps({"type": "run.steer", "run_id": run_id,
                                                    "event_id": event_id, "content": str(step.get("text", ""))}))
                                pending_delivery[event_id] = step
                                sent_steps.add(index)
                                pending_steps.pop(index, None)
                            elif action in {"prompt", "context"}:
                                prompt_queue.append((index, step))
                                pending_steps.pop(index, None)
                            elif action not in {"approve"}:
                                unsupported.append(str(action))
                                sent_steps.add(index)
                                pending_steps.pop(index, None)
                    event_name = None
                    try:
                        record = json.loads(ws.recv(timeout=min(.01, max(.005, deadline - time.monotonic()))))
                    except TimeoutError:
                        record = None
                    except Exception as exc:
                        return RunOutcome(None, "\n".join(stdout), "", events,
                                          (time.monotonic() - start) * 1000, f"websocket_error:{type(exc).__name__}", unsupported)
                    if isinstance(record, dict):
                        events.append(record)
                        stdout.append(json.dumps(record, ensure_ascii=False))
                        event_name = record.get("event") if record.get("type") == "agent_event" else record.get("type")
                        data = record.get("data") if isinstance(record.get("data"), dict) else {}
                        if controller is not None:
                            controller.emit(record)
                            if event_name == "run.started":
                                started_step = pending_delivery.pop(run_id, None)
                                if started_step is not None and hasattr(controller, "record_delivery"):
                                    controller.record_delivery(started_step, {"protocol": "atlas-ws", "run_id": run_id})
                                elif run_id == initial_run_id and first_step is not None and not initial_step_recorded and hasattr(controller, "record_delivery"):
                                    controller.record_delivery(first_step, {"protocol": "atlas-ws", "mode": "plan" if has_plan else "act", "run_id": run_id})
                                    initial_step_recorded = True
                        if event_name in {"run.steered", "approval.responded"}:
                            evidence_id = str(data.get("event_id", ""))
                            step = pending_delivery.pop(evidence_id, None)
                            if step and controller is not None and hasattr(controller, "record_delivery"):
                                controller.record_delivery(step, {"protocol": "atlas-ws", "event": record})
                        if event_name in {"run.status", "run.phase"} and (
                                data.get("status") == "running" or data.get("phase") == "execution"):
                            ack_id = "plan:" + run_id
                            step = pending_delivery.pop(ack_id, None)
                            if step and controller is not None and hasattr(controller, "record_delivery"):
                                controller.record_delivery(step, {"protocol": "atlas-ws", "event": record})
                        if event_name in {"run.completed", "run.failed", "run.cancelled"}:
                            if event_name != "run.completed":
                                err = data.get("detail") or data.get("error") or str(event_name)
                                safe_events = redact_events(events)
                                safe_stdout, safe_stderr = redact("\n".join(json.dumps(event, ensure_ascii=False) for event in safe_events), "")
                                return RunOutcome(1, safe_stdout, safe_stderr, safe_events,
                                                  (time.monotonic() - start) * 1000, str(err), sorted(set(unsupported)))
                            run_id = "t1-" + uuid.uuid4().hex
                            if prompt_queue:
                                index, step = prompt_queue.pop(0)
                                sent_steps.add(index)
                                start_run(ws, str(step.get("text", "")), run_id)
                                pending_delivery[run_id] = step
                                continue
                            if controller is not None:
                                for index, step in enumerate(steps):
                                    if index not in sent_steps and index not in pending_steps:
                                        unsupported.append(str(step.get("action", "unknown")))
                            safe_events = redact_events(events)
                            safe_stdout, safe_stderr = redact("\n".join(json.dumps(event, ensure_ascii=False) for event in safe_events), "")
                            return RunOutcome(0, safe_stdout, safe_stderr, safe_events,
                                              (time.monotonic() - start) * 1000,
                                              unsupported=sorted(set(unsupported)))
                    if controller is not None:
                        due = controller.due_steps(event=str(event_name) if event_name else None,
                                                   elapsed_seconds=elapsed)
                        for index, step in enumerate(steps):
                            if index not in sent_steps and isinstance(step, dict) and step in due:
                                pending_steps[index] = step
                        for index, step in list(pending_steps.items()):
                            action, text = step.get("action"), step.get("text", "")
                            if action == "steer":
                                event_id = "t1-steer-" + uuid.uuid4().hex
                                ws.send(json.dumps({"type": "run.steer", "run_id": run_id,
                                                    "event_id": event_id, "content": str(text)}))
                                pending_delivery[event_id] = step
                                sent_steps.add(index)
                                pending_steps.pop(index, None)
                            elif action == "approve":
                                if event_name not in {"run.plan.proposed", "approval.required"}:
                                    continue
                                if hasattr(controller, "snapshot_before_approval"):
                                    controller.snapshot_before_approval()
                                if event_name == "run.plan.proposed":
                                    ack_id = "plan:" + run_id
                                    ws.send(json.dumps({"type": "run.plan.approve", "run_id": run_id,
                                                        "event_id": ack_id, "edits": str(text)}))
                                else:
                                    ack_id = str(data.get("event_id", ""))
                                    ws.send(json.dumps({"type": "approval.response", "event_id": ack_id,
                                                        "choice": "allow"}))
                                pending_delivery[ack_id] = step
                                sent_steps.add(index)
                                pending_steps.pop(index, None)
                            elif action in {"prompt", "context"}:
                                prompt_queue.append((index, step))
                                pending_steps.pop(index, None)
                            else:
                                unsupported.append(str(action))
                                sent_steps.add(index)
                                pending_steps.pop(index, None)
                return RunOutcome(None, "\n".join(stdout), "", events,
                                  (time.monotonic() - start) * 1000, "timeout", sorted(set(unsupported)))
        except OSError as exc:
            return RunOutcome(None, "", str(exc), events, (time.monotonic() - start) * 1000,
                              "atlas_ws_unavailable")

    def parse_usage(self, outcome: RunOutcome):
        # Atlas emits one run.usage per model call and a cumulative run.completed
        # aggregate. Prefer aggregates so the same tokens are never counted twice.
        result = empty_usage()
        events = outcome.events
        aggregates = [e.get("data", {}).get("usage") for e in events
                      if e.get("event") == "run.completed" and isinstance(e.get("data"), dict)
                      and isinstance(e["data"].get("usage"), dict)]
        records = aggregates or [e.get("data") for e in events
                                 if e.get("event") == "run.usage" and isinstance(e.get("data"), dict)]
        if records:
            for output_key, names in {
                "input_tokens": ("input_tokens", "prompt_tokens"),
                "output_tokens": ("output_tokens", "completion_tokens"),
                "cached_tokens": ("cached_input_tokens", "cached_tokens", "cache_read_input_tokens"),
            }.items():
                vals = []
                for record in records:
                    value = next((record[name] for name in names if isinstance(record.get(name), (int, float))), None)
                    if value is None and isinstance(record.get("input_tokens_details"), dict):
                        value = record["input_tokens_details"].get("cached_tokens")
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        vals.append(value)
                if vals:
                    result[output_key] = sum(vals)
        if any(e.get("event") == "run.started" for e in events):
            result["turns"] = sum(e.get("event") == "run.started" for e in events)
        if any(e.get("event") in {"tool.started", "tool_start", "tool.started"} for e in events):
            result["tool_calls"] = sum(e.get("event") in {"tool.started", "tool_start"} for e in events)
        costs = [record.get("cost_usd", record.get("total_cost_usd")) for record in records]
        costs = [v for v in costs if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if costs:
            result["cost_usd"] = sum(costs)
        return result

    def supports(self, capability: str) -> bool:
        return capability in {"multi_round", "steer", "plan", "plan_mode", "approval",
                              "context", "compaction", "subagents"}
