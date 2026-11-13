# Ported from OpenHands/software-agent-sdk@c4b93299cf2b31c8b5d0b2c5a89965ccc5ff24f9: openhands-sdk/openhands/sdk/conversation/stuck_detector.py (MIT)
# SPDX-License-Identifier: MIT
"""Windowed action/observation loop detection with one corrective nudge.

OpenHands event classes are translated to compact Atlas records. Pairing by the
completed call avoids independently collected actions/results becoming misaligned
when readonly tools finish out of order. IDs and elapsed times are not equality
inputs. User input resets the detection window; summaries do not count as speech.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any

MAX_EVENTS_TO_SCAN_FOR_STUCK_DETECTION = 20


def _error_observation(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _error_observation(item) for key, item in value.items() if key not in {
            "execution_id", "pid", "elapsed", "elapsed_ms", "output_path", "log_path",
        }}
    if isinstance(value, (list, tuple)):
        return [_error_observation(item) for item in value]
    if isinstance(value, str):
        # Local execution appends fresh receipt identities to otherwise identical errors.
        return re.sub(r"(?m)^\s*(?:Full output:|Process:) [^\r\n]*(?:\r?\n|$)", "", value)
    return value


def _fingerprint(value: Any) -> str:
    def stable(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: stable(val) for key, val in item.items() if key not in {
                "id", "call_id", "tool_call_id", "duration_ms", "duration_seconds",
                "started_at", "timestamp", "metrics", "receipt", "output_ref",
            }}
        if isinstance(item, (list, tuple)):
            return [stable(val) for val in item]
        return item
    return hashlib.sha256(json.dumps(stable(value), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class StuckDecision:
    action: str
    reason: str
    message: str


class RepeatToolReminder:
    """Advisory reminder for a tool called repeatedly with identical arguments.

    Results are intentionally excluded from the key: a changing error or output
    must not hide the fact that the agent is issuing the same request again.
    """

    THRESHOLDS = (3, 5, 8)

    def __init__(self) -> None:
        self._last_key: str | None = None
        self._count = 0
        self._notified: set[int] = set()

    def observe(self, name: str, arguments: dict[str, Any]) -> str | None:
        key = _fingerprint([str(name), arguments])
        if key == self._last_key:
            self._count += 1
        else:
            self._last_key = key
            self._count = 1
            self._notified.clear()
        if self._count not in self.THRESHOLDS or self._count in self._notified:
            return None
        self._notified.add(self._count)
        return (
            f"You have called {name} with the same arguments {self._count} times in a row. "
            "Review the results and change the request if needed. This is a reminder; "
            "the call is not blocked."
        )


class StuckDetector:
    def __init__(self, *, action_observation: int = 4, action_error: int = 3,
                 monologue: int = 3, alternating_pattern: int = 6) -> None:
        self.action_observation = max(1, action_observation)
        self.action_error = max(1, action_error)
        self.monologue = max(1, monologue)
        self.alternating_pattern = max(4, alternating_pattern)
        self.events: deque[tuple[str, Any]] = deque(maxlen=max(
            MAX_EVENTS_TO_SCAN_FOR_STUCK_DETECTION, self.action_observation,
            self.action_error, self.monologue, self.alternating_pattern,
        ))
        self._nudged = False
        self._sequence = 0
        self._last_decision_sequence = -1
        self._after_nudge: deque[tuple[str, Any]] = deque(maxlen=self.events.maxlen)

    def _observe(self, kind: str, value: Any) -> None:
        event = (kind, value)
        self.events.append(event)
        if self._nudged:
            self._after_nudge.append(event)
        self._sequence += 1

    def observe_tool(self, name: str, arguments: dict[str, Any], result: Any,
                     *, is_error: bool = False) -> None:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                pass
        if isinstance(result, dict):
            is_error = is_error or bool(result.get("error") or result.get("is_error"))
        observation = _error_observation(result) if is_error else result
        self._observe("tool", (_fingerprint([name, arguments]), _fingerprint(observation), is_error))

    def observe_message(self, text: str, *, role: str = "assistant") -> None:
        if role == "user":
            self.reset()
        elif role in {"assistant", "agent"}:
            self._observe("message", text)

    def reset(self) -> None:
        self.events.clear()
        self._after_nudge.clear()
        self._nudged = False
        self._sequence += 1
        self._last_decision_sequence = -1

    def _reason(self, events: list[tuple[str, Any]]) -> str | None:
        pairs = [value for kind, value in events if kind == "tool"]
        n = self.action_observation
        latest_is_tool = bool(events and events[-1][0] == "tool")
        if latest_is_tool and len(pairs) >= n and all(p[:2] == pairs[-1][:2] for p in pairs[-n:]):
            return "repeated_call_result"
        n = self.action_error
        # OpenHands requires the same action and the same error observation.
        if latest_is_tool and len(pairs) >= n and all(
            p[0] == pairs[-1][0] and p[1] == pairs[-1][1] and p[2]
            for p in pairs[-n:]
        ):
            return "repeated_errors"
        n = self.monologue
        if len(events) >= n and all(kind == "message" for kind, _ in events[-n:]):
            return "monologue"
        n = self.alternating_pattern
        if latest_is_tool and len(pairs) >= n:
            window = pairs[-n:]
            if window[-1][:2] != window[-2][:2] and all(
                window[i][:2] == window[i - 2][:2] for i in range(2, n)
            ):
                return "alternating_loop"
        return None

    def check(self) -> StuckDecision | None:
        if self._last_decision_sequence == self._sequence:
            return None
        # A nudge is not a new model action: evaluate only subsequent activity.
        # For the same frozen loop, one more repeated pair/message is sufficient
        # to establish that the corrective instruction was ignored.
        reason = self._reason(list(self.events))
        if reason is None:
            return None
        if self._nudged and not self._after_nudge:
            return None
        self._last_decision_sequence = self._sequence
        if self._nudged:
            return StuckDecision("halt", reason, f"Stopped this turn because the agent repeated an unproductive pattern after correction ({reason}).")
        self._nudged = True
        self._after_nudge.clear()
        return StuckDecision("nudge", reason, f"An unproductive pattern was detected ({reason}). Review the last results, correct the arguments or choose a different approach. Do not repeat the same calls or continue reasoning without taking action.")

    def is_stuck(self) -> bool:
        return self._reason(list(self.events)) is not None
