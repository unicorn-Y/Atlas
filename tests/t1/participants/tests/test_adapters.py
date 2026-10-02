from __future__ import annotations

import json
import io
import os
import queue
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
import time
from unittest.mock import MagicMock, patch

T1_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(T1_ROOT))

from participants import RunContext, RunOutcome, get_adapter
from participants.base import sanitize_command


class Controller:
    def __init__(self, steps):
        self.steps = steps
        self.events = []
        self.deliveries = []
        self.snapshots = 0
        self.dispatched = set()

    def emit(self, event):
        self.events.append(event)

    def due_steps(self, event=None, elapsed_seconds=None):
        due = []
        for index, step in enumerate(self.steps):
            if index in self.dispatched:
                continue
            trigger = step.get("trigger") or {}
            if trigger.get("event") and trigger.get("event") != event:
                continue
            if trigger.get("after_seconds") is not None and elapsed_seconds is not None and elapsed_seconds < trigger["after_seconds"]:
                continue
            self.dispatched.add(index)
            due.append(step)
        return due

    def record_delivery(self, step, evidence):
        self.deliveries.append((step, evidence))

    def snapshot_before_approval(self):
        self.snapshots += 1


class MockAtlasSocket:
    def __init__(self, mode="rounds"):
        self.mode = mode
        self.incoming = []
        self.sent = []
        self.started_at = time.monotonic()
        self.live_run_id = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def send(self, message):
        packet = json.loads(message)
        self.sent.append(packet)
        if packet["type"] == "run.start":
            self.live_run_id = packet["run_id"]
            self.incoming.append({"type": "agent_event", "event": "run.started",
                                  "data": {"run_id": packet["run_id"]}})
            if self.mode == "rounds":
                self.incoming.append({"type": "agent_event", "event": "run.completed",
                                      "data": {"run_id": packet["run_id"], "usage": {
                                          "input_tokens": 10, "output_tokens": 2,
                                          "cached_input_tokens": 1, "cost_usd": .01}}})
            elif self.mode == "plan":
                self.incoming.append({"type": "agent_event", "event": "run.plan.proposed",
                                      "data": {"run_id": packet["run_id"], "plan": "safe"}})
            elif self.mode == "steer":
                pass
        elif packet["type"] == "run.plan.approve":
            self.incoming.append({"type": "agent_event", "event": "run.status",
                                  "data": {"run_id": packet["run_id"], "status": "running"}})
            self.incoming.append({"type": "agent_event", "event": "run.completed",
                                  "data": {"run_id": packet["run_id"], "usage": {}}})
        elif packet["type"] == "run.steer":
            self.incoming.append({"type": "agent_event", "event": "run.steered",
                                  "data": {"event_id": packet["event_id"]}})
            self.incoming.append({"type": "agent_event", "event": "run.completed",
                                  "data": {"run_id": packet["run_id"], "usage": {}}})

    def recv(self, timeout=None):
        if self.incoming:
            return json.dumps(self.incoming.pop(0))
        if self.mode == "steer" and time.monotonic() - self.started_at >= .03:
            self.mode = "steer-complete"
            return json.dumps({"type": "agent_event", "event": "run.completed",
                               "data": {"run_id": self.live_run_id, "usage": {}}})
        time.sleep(timeout or .005)
        raise TimeoutError()


class QueuedReader:
    def __init__(self, values=()):
        self.values = queue.Queue()
        for value in values:
            self.values.put(value if isinstance(value, bytes) else json.dumps(value).encode("utf-8") + b"\n")
        self.values.put(b"")

    def readline(self):
        return self.values.get()


class CaptureStdin:
    def __init__(self):
        self.payloads = []

    def write(self, value):
        self.payloads.append(json.loads(value.decode("utf-8")))
        return len(value)

    def flush(self):
        pass

    def close(self):
        pass


class MockPiProcess:
    def __init__(self):
        self.stdin = CaptureStdin()
        self.stdout = QueuedReader([
            {"id": "t1-1", "type": "response", "command": "prompt", "success": True,
             "data": {"disposition": "started"}},
            {"type": "agent_settled"},
            {"id": "t1-2", "type": "response", "command": "prompt", "success": True,
             "data": {"disposition": "started"}},
            {"type": "agent_settled"},
            {"id": "t1-3", "type": "response", "command": "get_session_stats", "success": True,
             "data": {"userMessages": 2, "assistantMessages": 2, "toolCalls": 3,
                      "tokens": {"input": 21, "output": 8, "cacheRead": 5}, "cost": .07}},
        ])
        self.stderr = io.BytesIO()
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class StreamingReader:
    def __init__(self):
        self.values = queue.Queue()

    def push(self, record):
        self.values.put(json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n")

    def readline(self):
        return self.values.get()


class MockClaudeProcess:
    def __init__(self, complete_after=1):
        self.stdout = StreamingReader()
        self.stderr = io.BytesIO()
        self.returncode = None
        self.pid = 987654
        self.complete_after = complete_after
        self.stdin = self.Input(self)

    class Input:
        def __init__(self, process):
            self.process = process
            self.messages = []

        def write(self, value):
            record = json.loads(value.decode("utf-8"))
            self.messages.append(record)
            self.process.stdout.push({"type": "assistant", "message": {"role": "assistant"}})
            if len(self.messages) >= self.process.complete_after:
                self.process.stdout.push({"type": "result", "subtype": "success",
                                          "usage": {"input_tokens": 9, "output_tokens": 4}})
            return len(value)

        def flush(self):
            pass

        def close(self):
            self.process.returncode = 0
            self.process.stdout.values.put(b"")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self.returncode or 0
        return self.returncode

    def communicate(self):
        return b"", b""

    def kill(self):
        self.returncode = -9


class ParticipantAdapterTests(unittest.TestCase):
    def context(self, task="01", scenario=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        workspace = root / "workspace"
        workspace.mkdir()
        task_dir = root / "task"
        (task_dir / "solution").mkdir(parents=True)
        (task_dir / "solution" / "answer.txt").write_text("reference", encoding="utf-8")
        if task == "20":
            release = {"incident_id": "T1-PROVIDER-20", "faults": ["429", "500", "disconnect"],
                       "attempts": 4, "response": "recovered"}
            (workspace / "release.json").write_text(json.dumps(release), encoding="utf-8")
            fixture = task_dir / "fixture"
            fixture.mkdir(parents=True)
            (fixture / "release.json").write_text(json.dumps(release), encoding="utf-8")
        return RunContext(task, workspace, task_dir, "solve task", timeout_seconds=.1, scenario=scenario)

    def test_commands_are_build_only_and_capabilities_are_truthful(self):
        ctx = self.context()
        codex = get_adapter("codex")
        command = codex.build_command(ctx)
        self.assertIn("--json", command)
        self.assertFalse(codex.supports("steer"))
        pi = get_adapter("pi")
        self.assertIn("rpc", pi.build_command(ctx))
        self.assertTrue(pi.supports("steer"))
        self.assertFalse(pi.supports("rewind"))
        atlas = get_adapter("atlas")
        self.assertIn("/ws/chat", atlas.build_command(ctx)[1])

    def test_opencode_availability_probes_help_in_temporary_user_profile(self):
        adapter = get_adapter("opencode")
        captured = {}
        def help_only(command, **kwargs):
            captured["command"] = command
            captured.update(kwargs)
            return subprocess.CompletedProcess(command, 0, b"usage", b"")
        with patch("participants.opencode.subprocess.run", side_effect=help_only):
            status = adapter.availability()
        self.assertTrue(status["available"])
        self.assertEqual(captured["command"][-2:], ["run", "--help"])
        self.assertEqual(captured["env"]["HOME"], captured["cwd"])
        self.assertNotEqual(captured["env"]["USERPROFILE"], os.environ.get("USERPROFILE"))

    def test_real_fault_proxy_bindings_require_opt_in_and_are_per_run_only(self):
        self.assertFalse(get_adapter("codex").supports("fault_proxy"))
        url = "http://127.0.0.1:43127/v1"
        codex = get_adapter("codex", {
            "command": ["codex", "-c", "model_providers.t1={base_url='{fault_proxy_url}',wire_api='responses'}"],
            "fault_proxy_binding": {"kind": "command", "placeholder": "{fault_proxy_url}"},
            "fault_proxy_url": url,
        })
        self.assertFalse(codex.supports("fault_proxy"))
        ctx = self.context()
        command = codex.build_command(ctx)
        self.assertIn("{fault_proxy_url}", " ".join(command))

        hermes = get_adapter("hermes", {
            "fault_proxy_binding": {"kind": "env", "name": "OPENAI_BASE_URL"},
            "fault_proxy_url": url,
        })
        self.assertTrue(hermes.supports("fault_proxy"))
        fake_process = MagicMock()
        fake_process.communicate.return_value = (b"{}\n", b"")
        fake_process.returncode = 0
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://existing.invalid/v1"}), \
                patch("participants.common.subprocess.Popen", return_value=fake_process) as popen:
            outcome = hermes.run_once(self.context("20"))
            self.assertEqual(os.environ["OPENAI_BASE_URL"], "https://existing.invalid/v1")
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(popen.call_args.kwargs["env"]["OPENAI_BASE_URL"], url)
        scenario_ctx = self.context("11", {"steps": [{"action": "prompt", "text": "local only"}]})
        fake_process = MagicMock()
        fake_process.communicate.return_value = (b"{}\n", b"")
        fake_process.returncode = 0
        with patch("participants.common.subprocess.Popen", return_value=fake_process) as popen:
            outcome = hermes.run_scenario(scenario_ctx, Controller(scenario_ctx.scenario["steps"]))
        self.assertEqual(outcome.exit_code, 0)
        self.assertIsNone(popen.call_args.kwargs["env"])
        self.assertFalse(get_adapter("hermes", {
            "fault_proxy_binding": {"kind": "env", "name": "OPENAI_BASE_URL"},
            "fault_proxy_url": "https://example.com/v1",
        }).supports("fault_proxy"))

    def test_usage_unknowns_stay_null(self):
        outcome = RunOutcome(0, stdout='{"type":"turn.completed","usage":{"input_tokens":9,"output_tokens":4,"cached_input_tokens":3}}',
                            events=[{"type":"turn.completed", "usage": {"input_tokens": 9, "output_tokens": 4, "cached_input_tokens": 3}}])
        usage = get_adapter("codex").parse_usage(outcome)
        self.assertEqual(usage["input_tokens"], 9)
        self.assertEqual(usage["cached_tokens"], 3)
        self.assertIsNone(usage["cost_usd"])

    def test_native_usage_prefers_cumulative_result_and_preserves_unknowns(self):
        events = [
            {"type": "assistant_message", "usage": {"input_tokens": 5, "output_tokens": 1}},
            {"type": "result", "usage": {"input_tokens": 8, "output_tokens": 2,
                                              "input_tokens_details": {"cached_tokens": 3},
                                              "cost_usd": .04}},
        ]
        usage = get_adapter("claude").parse_usage(RunOutcome(0, events=events))
        self.assertEqual(usage["input_tokens"], 8)
        self.assertEqual(usage["output_tokens"], 2)
        self.assertEqual(usage["cached_tokens"], 3)
        self.assertEqual(usage["cost_usd"], .04)
        unknown = get_adapter("atlas").parse_usage(RunOutcome(0, events=[]))
        self.assertTrue(all(unknown[key] is None for key in unknown))
        codex_events = [
            {"type": "assistant_message", "usage": {"input_tokens": 99, "output_tokens": 99}},
            {"type": "turn.completed", "usage": {"input_tokens": 9, "output_tokens": 4,
                                                    "input_tokens_details": {"cached_tokens": 3},
                                                    "total_cost_usd": .06}},
        ]
        usage = get_adapter("codex").parse_usage(RunOutcome(0, events=codex_events))
        self.assertEqual(usage["input_tokens"], 9)
        self.assertEqual(usage["output_tokens"], 4)
        self.assertEqual(usage["cached_tokens"], 3)
        self.assertEqual(usage["cost_usd"], .06)
        hermes_events = [
            {"type": "message", "usage": {"input_tokens": 4, "output_tokens": 1, "cost_usd": .01}},
            {"type": "result", "usage": {"input_tokens": 6, "output_tokens": 2, "cost_usd": .02}},
            {"type": "message", "usage": {"input_tokens": 3, "output_tokens": 1, "cost_usd": .01}},
            {"type": "result", "usage": {"input_tokens": 5, "output_tokens": 2, "cost_usd": .015}},
        ]
        usage = get_adapter("hermes").parse_usage(RunOutcome(0, events=hermes_events))
        self.assertEqual(usage["input_tokens"], 11)
        self.assertEqual(usage["output_tokens"], 4)
        self.assertEqual(usage["cost_usd"], .035)

    def test_hermes_resumed_rounds_use_remaining_timeout_and_preserve_exit_failure(self):
        scenario = {"steps": [{"action": "prompt", "text": "first"},
                              {"action": "context", "text": "second"}]}
        ctx = self.context("11", scenario)
        ctx.timeout_seconds = .5
        adapter = get_adapter("hermes")
        received = []
        def successful_turn(turn_context, command):
            received.append((turn_context.timeout_seconds, command))
            time.sleep(.02)
            return RunOutcome(0, events=[{"type": "result", "session_id": "session-12345678"}])
        with patch.object(adapter, "_run", side_effect=successful_turn):
            outcome = adapter.run_scenario(ctx, Controller(scenario["steps"]))
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(len(received), 2)
        self.assertLess(received[1][0], received[0][0])
        self.assertIn("--resume", received[1][1])

        failed = get_adapter("hermes")
        with patch.object(failed, "_run", return_value=RunOutcome(7, stderr="native failure")):
            outcome = failed.run_scenario(ctx, Controller(scenario["steps"]))
        self.assertEqual(outcome.exit_code, 7)
        self.assertEqual(outcome.error, "hermes_exit:7")

    def test_atlas_native_eight_rounds_are_sequential_and_usage_not_double_counted(self):
        steps = [{"action": "prompt", "text": f"turn {i}"} for i in range(8)]
        controller = Controller(steps)
        ctx = self.context("11", {"steps": steps})
        socket = MockAtlasSocket()
        with patch("websockets.sync.client.connect", return_value=socket):
            result = get_adapter("atlas").run_scenario(ctx, controller)
        starts = [packet for packet in socket.sent if packet["type"] == "run.start"]
        self.assertEqual(len(starts), 8)
        self.assertEqual(len({packet["run_id"] for packet in starts}), 8)
        self.assertEqual(len({packet["conversation_id"] for packet in starts}), 1)
        self.assertEqual(len(controller.deliveries), 8)
        usage = get_adapter("atlas").parse_usage(result)
        self.assertEqual(usage["input_tokens"], 80)
        self.assertEqual(usage["cached_tokens"], 8)
        self.assertEqual(usage["cost_usd"], .08)

    def test_atlas_plan_approval_snapshots_and_live_steer_use_native_messages(self):
        plan_steps = [{"action": "plan", "text": "先计划"}, {"action": "approve", "text": "批准"}]
        controller = Controller(plan_steps)
        ctx = self.context("15", {"steps": plan_steps})
        socket = MockAtlasSocket("plan")
        with patch("websockets.sync.client.connect", return_value=socket):
            result = get_adapter("atlas").run_scenario(ctx, controller)
        self.assertEqual(controller.snapshots, 1)
        self.assertEqual([p["type"] for p in socket.sent], ["run.start", "run.plan.approve"])
        self.assertEqual(len(controller.deliveries), 2)
        self.assertEqual(result.exit_code, 0)

        steer_steps = [{"action": "prompt", "text": "开始"},
                       {"action": "steer", "text": "追加约束", "trigger": {"after_seconds": .02}}]
        steer_controller = Controller(steer_steps)
        steer_ctx = self.context("19", {"steps": steer_steps})
        socket = MockAtlasSocket("steer")
        with patch("websockets.sync.client.connect", return_value=socket):
            result = get_adapter("atlas").run_scenario(steer_ctx, steer_controller)
        self.assertEqual([p["type"] for p in socket.sent], ["run.start", "run.steer"])
        self.assertEqual(len(steer_controller.deliveries), 2)
        self.assertEqual(result.exit_code, 0)

    def test_pi_rpc_uses_documented_commands_and_native_session_stats(self):
        steps = [{"action": "prompt", "text": "first"},
                 {"action": "prompt", "text": "second"}]
        controller = Controller(steps)
        ctx = self.context("11", {"steps": steps})
        proc = MockPiProcess()
        with patch("participants.pi.subprocess.Popen", return_value=proc):
            outcome = get_adapter("pi").run_scenario(ctx, controller)
        commands = proc.stdin.payloads
        self.assertEqual([item["type"] for item in commands], ["prompt", "prompt", "get_session_stats"])
        self.assertEqual([item["message"] for item in commands[:2]], ["first", "second"])
        self.assertEqual(len(controller.deliveries), 2)
        usage = get_adapter("pi").parse_usage(outcome)
        self.assertEqual(usage, {"tool_calls": 3, "turns": 2, "input_tokens": 21,
                                 "output_tokens": 8, "cached_tokens": 5, "cost_usd": .07})

    def test_claude_streaming_waits_for_result_before_sending_next_turn_and_steers_live(self):
        steps = [{"action": "prompt", "text": "start"},
                 {"action": "prompt", "text": "next"}]
        controller = Controller(steps)
        ctx = self.context("11", {"steps": steps})
        proc = MockClaudeProcess(complete_after=1)
        with patch("participants.claude.subprocess.Popen", return_value=proc):
            outcome = get_adapter("claude").run_scenario(ctx, controller)
        self.assertEqual([row["message"]["content"][0]["text"] for row in proc.stdin.messages],
                         ["start", "next"])
        self.assertEqual(len(controller.deliveries), 2)
        self.assertEqual(outcome.exit_code, 0)

        steps = [{"action": "prompt", "text": "start"},
                 {"action": "steer", "text": "change", "trigger": {"after_seconds": .01}}]
        controller = Controller(steps)
        ctx = self.context("19", {"steps": steps})
        proc = MockClaudeProcess(complete_after=2)
        with patch("participants.claude.subprocess.Popen", return_value=proc):
            outcome = get_adapter("claude").run_scenario(ctx, controller)
        self.assertEqual([row["message"]["content"][0]["text"] for row in proc.stdin.messages],
                         ["start", "change"])
        self.assertEqual(len(controller.deliveries), 2)
        self.assertEqual(outcome.exit_code, 0)

    def test_dry_run_command_sanitization_hides_credentials_and_query_options(self):
        result = sanitize_command(["claude", "--query", "secret prompt", "--api-key=sk-ant-abcdefghijklmnopqrstuvwxyz"])
        self.assertEqual(result, ["claude", "--query", "<prompt>", "--api-key=<redacted>"])
        self.assertNotIn("secret prompt", " ".join(result))

    def test_fake_overlay_failure_forbidden_and_timeout_modes(self):
        ctx = self.context()
        adapter = get_adapter("fake", {"fake_mode": "success", "fake_cost_usd": .02})
        result = adapter.run_once(ctx)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual((ctx.workspace / "answer.txt").read_text(encoding="utf-8"), "reference")
        self.assertEqual(adapter.parse_usage(result)["cost_usd"], .02)
        forbidden = get_adapter("fake", {"fake_mode": "forbidden"}).run_once(ctx)
        self.assertTrue((ctx.workspace / ".t1-forbidden.txt").is_file())
        self.assertTrue(any(event.get("type") == "fake_forbidden_change" for event in forbidden.events))
        timeout = get_adapter("fake", {"fake_mode": "timeout"}).run_once(ctx)
        self.assertEqual(timeout.error, "timeout")

    def test_fake_approval_snapshot_and_rewind_are_workspace_changes(self):
        scenario = {"steps": [
            {"action": "plan", "text": "先只计划"},
            {"action": "approve", "text": "开始执行"},
        ]}
        ctx = self.context(scenario=scenario)
        controller = Controller(scenario["steps"])
        outcome = get_adapter("fake").run_scenario(ctx, controller)
        self.assertEqual(controller.snapshots, 1)
        self.assertEqual(len(controller.deliveries), 2)
        self.assertTrue((ctx.workspace / "answer.txt").exists())
        rewind_scenario = {"steps": [
            {"action": "context", "text": "只读检查"}, {"action": "checkpoint"},
            {"action": "prompt", "text": "尝试方案 A", "fake_reference": "reference-a"},
            {"action": "rewind"}, {"action": "steer", "text": "改走方案 B"},
        ]}
        ctx = self.context(scenario=rewind_scenario)
        (ctx.task_dir / "reference-a").mkdir()
        (ctx.task_dir / "reference-a" / "choice_a.txt").write_text("A", encoding="utf-8")
        (ctx.task_dir / "solution" / "choice_b.txt").write_text("B", encoding="utf-8")
        outcome = get_adapter("fake").run_once(ctx)
        rewind_events = [e for e in outcome.events if e.get("type") == "workspace_snapshot" and e.get("action") == "rewind"]
        self.assertEqual(len(rewind_events), 1)
        self.assertFalse((ctx.workspace / "choice_a.txt").exists())
        self.assertTrue((ctx.workspace / "choice_b.txt").exists())
        self.assertGreaterEqual(sum(e.get("type") == "fake_overlay" for e in outcome.events), 2)

    def test_fake_task19_records_initial_work_then_timed_steer(self):
        scenario = {"steps": [
            {"action": "prompt", "text": "paid only"},
            {"action": "steer", "text": "paid and pending", "trigger": {"after_seconds": .02}},
        ]}
        ctx = self.context("19", scenario)
        (ctx.workspace / "transactions.json").write_text(
            '[{"id":"a","status":"paid","cents":10},{"id":"b","status":"pending","cents":20}]', encoding="utf-8")
        (ctx.task_dir / "solution" / "summary.json").write_text(
            '{"included_ids":["a","b"],"total_cents":30,"note":"已应用中途更新"}', encoding="utf-8")
        controller = Controller(scenario["steps"])
        outcome = get_adapter("fake").run_scenario(ctx, controller)
        phases = [event.get("phase") for event in outcome.events if event.get("type") == "fake_workspace_mutation"]
        self.assertEqual(phases, ["initial_work", "post_steer"])
        self.assertEqual((ctx.workspace / "summary.json").read_text(encoding="utf-8"),
                         '{"included_ids":["a","b"],"total_cents":30,"note":"已应用中途更新"}')
        self.assertEqual(len(controller.deliveries), 2)

    def test_task20_fake_uses_only_local_fault_proxy_and_recovers_stream(self):
        ctx = self.context("20")
        result = get_adapter("fake").run_once(ctx)
        summary = next(event for event in result.events if event.get("type") == "fault_proxy_summary")
        self.assertEqual(summary["requests"], 4)
        self.assertTrue(summary["stream_done"])
        trace = next(event for event in result.events if event.get("type") == "provider_fault_trace")
        self.assertEqual(trace["source"], "local-fake-provider")
        self.assertEqual([row["fault"] for row in trace["requests"]], ["429", "500", "disconnect", None])
        self.assertTrue(trace["recovered"])
        self.assertEqual(json.loads((ctx.workspace / "recovery.json").read_text(encoding="utf-8")), {
            "incident_id": "T1-PROVIDER-20", "recovered": True, "attempts": 4,
            "faults": ["429", "500", "disconnect"], "response": "recovered"})
        self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
