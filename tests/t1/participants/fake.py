from __future__ import annotations

import json
import os
import stat
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from .base import ParticipantAdapter, RunContext, RunOutcome


class FakeAdapter(ParticipantAdapter):
    """Deterministic local participant. Reference overlays are reachable only here."""
    name = "fake"

    def availability(self):
        return {"available": True, "reason": None}

    def build_command(self, context: RunContext) -> list[str]:
        return ["<fake-local-adapter>", "--task", context.task_id]

    def _emit(self, events: list[dict[str, Any]], action: str, **fields: Any) -> None:
        events.append({"type": "scenario_action", "action": action, **fields})

    def _overlay(self, context: RunContext, events: list[dict[str, Any]], source_name: str = "solution") -> None:
        source = (context.task_dir / source_name).resolve()
        if context.task_dir.resolve() not in source.parents:
            events.append({"type": "fake_overlay", "available": False, "reason": "overlay path escapes task"})
            return
        if not source.is_dir():
            events.append({"type": "fake_overlay", "available": False})
            return
        count = 0
        for source_path in source.rglob("*"):
            if not source_path.is_file():
                continue
            relative = source_path.relative_to(source)
            target = context.workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            count += 1
        events.append({"type": "fake_overlay", "available": True, "files": count})

    @staticmethod
    def _restore_working_tree(workspace: Path, snapshot: Path) -> None:
        """Restore fixture files while preserving the runner-owned git baseline."""
        def remove(path: Path):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, onerror=lambda fn, name, exc: (os.chmod(name, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC), fn(name)))
            else:
                try:
                    path.chmod(stat.S_IWRITE | stat.S_IREAD)
                except OSError:
                    pass
                path.unlink(missing_ok=True)
        for child in workspace.iterdir():
            if child.name != ".git":
                remove(child)
        for child in snapshot.iterdir():
            if child.name == ".git":
                continue
            target = workspace / child.name
            if child.is_dir() and not child.is_symlink():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)

    def _proxy_recovery(self, context: RunContext, events: list[dict[str, Any]]) -> tuple[bool, dict[str, Any] | None]:
        try:
            from fault_proxy import FaultProxy
            from fault_proxy.client import recover
            release = json.loads((context.workspace / "release.json").read_text(encoding="utf-8"))
            faults = release["faults"]
            attempts = int(release["attempts"])
            with FaultProxy(faults=faults, response=release["response"]) as proxy:
                result = recover(proxy.url, attempts=attempts, stream=True)
                requests = list(proxy.requests)
                recovered = (result.get("content") == release["response"]
                             and len(requests) == attempts
                             and [row.get("fault") for row in requests[:len(faults)]] == faults
                             and all(row.get("fault") is None for row in requests[len(faults):]))
                for row in result["history"]:
                    events.append({"type": "fault_proxy_attempt", **row})
                events.append({"type": "provider_fault_trace", "source": "local-fake-provider",
                               "requests": requests, "recovered": recovered})
                events.append({"type": "fault_proxy_summary", "attempts": len(result["history"]),
                               "requests": len(requests), "stream_done": bool(recovered)})
                if not recovered:
                    return False, None
                recovery = {"incident_id": release["incident_id"], "recovered": True,
                            "attempts": attempts, "faults": faults,
                            "response": result["content"]}
                (context.workspace / "recovery.json").write_text(
                    json.dumps(recovery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return True, recovery
        except Exception as exc:
            events.append({"type": "fault_proxy_error", "error": type(exc).__name__})
            return False, None

    def run_once(self, context: RunContext) -> RunOutcome:
        return self._run(context, None)

    def run_scenario(self, context: RunContext, controller):
        return self._run(context, controller)

    def _run(self, context: RunContext, controller) -> RunOutcome:
        start = time.monotonic()
        mode = self.config.get("fake_mode", "success")
        events: list[dict[str, Any]] = []
        stdout = ""
        stderr = ""
        unsupported: list[str] = []
        if mode == "timeout":
            return RunOutcome(None, events=events, duration_ms=(time.monotonic() - start) * 1000, error="timeout")
        if mode == "failure":
            return RunOutcome(1, stderr="fake participant configured failure", events=events,
                              duration_ms=(time.monotonic() - start) * 1000, error="fake_failure")

        scenario = context.scenario or {}
        steps = scenario.get("steps", []) if isinstance(scenario, dict) else []
        actions = [str(step.get("action", "prompt")) for step in steps if isinstance(step, dict)]
        if context.task_id == "14":
            goals = self.config.get("fake_subagent_goals", ["goal-1", "goal-2", "goal-3"])
            events.extend({"type": "fake_subagent_result", "goal_id": str(goal),
                           "status": "completed", "simulated": True} for goal in goals[:3])
        if context.task_id == "12":
            events.append({"type": "fake_compaction", "simulated": True,
                           "preserved_constraint": "scenario context retained"})
        checkpoint: Path | None = None
        checkpoint_dir: tempfile.TemporaryDirectory[str] | None = None
        approval_required = "approve" in actions
        approved = not approval_required
        overlay_done = False
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            trigger = step.get("trigger")
            if controller is not None and isinstance(trigger, dict):
                deadline_at = float(trigger.get("after_seconds", 0))
                while time.monotonic() - start < deadline_at:
                    time.sleep(min(.01, max(0, deadline_at - (time.monotonic() - start))))
                due = controller.due_steps(event=None, elapsed_seconds=time.monotonic() - start)
                if step not in due:
                    unsupported.append(f"{step.get('action')}:trigger_not_dispatched")
                    continue
            action = str(step.get("action", "prompt"))
            if action == "approve" and controller is not None and hasattr(controller, "snapshot_before_approval"):
                controller.snapshot_before_approval()
            self._emit(events, action, index=index, text=step.get("text"), name=step.get("name"))
            if controller is not None:
                controller.emit(events[-1])
                if hasattr(controller, "record_delivery"):
                    controller.record_delivery(step, {"protocol": "fake-local", "event": events[-1]})
            if action == "checkpoint":
                if checkpoint_dir:
                    checkpoint_dir.cleanup()
                checkpoint_dir = tempfile.TemporaryDirectory(prefix="atlas-t1-fake-checkpoint-")
                checkpoint = Path(checkpoint_dir.name) / "snapshot"
                if context.workspace.exists():
                    shutil.copytree(context.workspace, checkpoint)
                else:
                    checkpoint.mkdir(parents=True)
                events.append({"type": "workspace_snapshot", "action": "checkpoint", "index": index,
                               "files": sum(1 for p in checkpoint.rglob("*") if p.is_file())})
            elif action == "approve":
                approved = True
                events.append({"type": "approval_observed", "approved": True, "index": index})
                if not overlay_done:
                    self._overlay(context, events)
                    overlay_done = True
            elif action == "rewind":
                if checkpoint is None:
                    unsupported.append("rewind_without_checkpoint")
                    continue
                self._restore_working_tree(context.workspace, checkpoint)
                overlay_done = False
                events.append({"type": "workspace_snapshot", "action": "rewind", "index": index,
                               "files": sum(1 for p in context.workspace.rglob("*") if p.is_file())})
            elif action in {"prompt", "steer", "context"}:
                if approved and (action == "prompt" or action == "steer") and ("checkpoint" in actions or not approval_required):
                    stage = step.get("fake_reference")
                    if stage:
                        self._overlay(context, events, str(stage))
                        events.append({"type": "fake_workspace_mutation", "phase": "stage_a",
                                       "step_index": index, "path": str(stage)})
                        overlay_done = False
                    elif context.task_id == "16" and action == "prompt" and index == 2:
                        self._overlay(context, events, "reference-a")
                        events.append({"type": "fake_workspace_mutation", "phase": "choice_a",
                                       "step_index": index, "path": "choice_a.txt"})
                        overlay_done = False
                    elif context.task_id == "19" and action == "prompt" and index == 0:
                        rows = json.loads((context.workspace / "transactions.json").read_text(encoding="utf-8"))
                        initial = [row for row in rows if row.get("status") == "paid"]
                        (context.workspace / "summary.json").write_text(
                            json.dumps({"included_ids": [row["id"] for row in initial],
                                        "total_cents": sum(row["cents"] for row in initial)},
                                       ensure_ascii=False), encoding="utf-8")
                        events.append({"type": "fake_workspace_mutation", "phase": "initial_work",
                                       "step_index": index, "paid_rows": len(initial)})
                        overlay_done = False
                    elif context.task_id == "19" and action == "prompt" and any(
                            e.get("type") == "scenario_action" and e.get("action") == "steer" for e in events):
                        self._overlay(context, events)
                        events.append({"type": "fake_workspace_mutation", "phase": "post_steer", "step_index": index})
                        overlay_done = True
                    elif context.task_id == "19" and action == "steer":
                        self._overlay(context, events)
                        events.append({"type": "fake_workspace_mutation", "phase": "post_steer", "step_index": index})
                        overlay_done = True
                    elif context.task_id != "19":
                        self._overlay(context, events)
                        overlay_done = True
            elif action in {"plan"}:
                events.append({"type": "plan_observed", "index": index, "mutated": False})
            elif action in {"approve"}:
                pass
            elif action in {"context", "checkpoint", "rewind"}:
                pass
            else:
                unsupported.append(action)

        if mode == "forbidden":
            target = context.workspace / self.config.get("forbidden_path", ".t1-forbidden.txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fake forbidden change\n", encoding="utf-8")
            events.append({"type": "fake_forbidden_change", "path": str(target.relative_to(context.workspace))})
        elif mode == "success" and not overlay_done and approved and context.task_id != "20":
            self._overlay(context, events)
            overlay_done = True

        if context.task_id == "20":
            recovered, recovery = self._proxy_recovery(context, events)
            stdout += json.dumps(recovery, ensure_ascii=False) if recovery else ""
            if not recovered:
                unsupported.append("fault_proxy_unavailable_or_recovery_failed")
            usage = {"tool_calls": 2, "turns": 1, "input_tokens": 12, "output_tokens": 3,
                     "cached_tokens": None, "cost_usd": 0.0}
            events.append({"type": "fake_usage", **usage})
            if checkpoint_dir:
                checkpoint_dir.cleanup()
            return RunOutcome(0 if recovered else 1, stdout, stderr, events,
                              (time.monotonic() - start) * 1000,
                              None if recovered else "fault_proxy_recovery_failed", unsupported)

        if checkpoint_dir:
            checkpoint_dir.cleanup()
        usage = {"tool_calls": int(self.config.get("fake_tool_calls", 2)),
                 "turns": int(self.config.get("fake_turns", max(1, len([a for a in actions if a in {"prompt", "steer"}])))),
                 "input_tokens": self.config.get("fake_input_tokens", 120),
                 "output_tokens": self.config.get("fake_output_tokens", 48),
                 "cached_tokens": self.config.get("fake_cached_tokens", None),
                 "cost_usd": self.config.get("fake_cost_usd", 0.0)}
        events.append({"type": "fake_usage", **usage})
        if mode == "forbidden":
            return RunOutcome(0, stdout, stderr, events, (time.monotonic() - start) * 1000, unsupported=unsupported)
        return RunOutcome(0, stdout, stderr, events, (time.monotonic() - start) * 1000, unsupported=unsupported)

    def parse_usage(self, outcome: RunOutcome):
        for event in reversed(outcome.events):
            if event.get("type") == "fake_usage":
                return {key: event.get(key) for key in ("tool_calls", "turns", "input_tokens", "output_tokens", "cached_tokens", "cost_usd")}
        return {"tool_calls": None, "turns": None, "input_tokens": None,
                "output_tokens": None, "cached_tokens": None, "cost_usd": None}

    def supports(self, capability: str) -> bool:
        return capability in {"multi_round", "steer", "plan", "plan_mode", "approval", "checkpoint", "rewind", "context", "fault_proxy", "subagents", "compaction"}
