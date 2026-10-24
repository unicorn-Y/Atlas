from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

DEFAULT_MAX_TURNS = 20
_CONTRACT_FIELDS = ("outcome", "verification", "constraints", "boundaries", "stop_when")
_CONTRACT_LABELS = {"outcome": "Outcome", "verification": "Verification", "constraints": "Constraints", "boundaries": "Boundaries", "stop_when": "Stop when blocked"}
_CONTRACT_ALIASES = {
    "outcome": "outcome", "goal": "outcome", "done": "outcome", "done when": "outcome",
    "verification": "verification", "verify": "verification", "verified by": "verification", "evidence": "verification", "proof": "verification",
    "constraints": "constraints", "constraint": "constraints", "preserve": "constraints", "must not": "constraints", "do not change": "constraints",
    "boundaries": "boundaries", "boundary": "boundaries", "scope": "boundaries", "allowed": "boundaries", "files": "boundaries",
    "stop when": "stop_when", "stop_when": "stop_when", "blocked": "stop_when", "stop if blocked": "stop_when", "give up when": "stop_when",
}

@dataclass
class GoalContract:
    outcome: str = ""
    verification: str = ""
    constraints: str = ""
    boundaries: str = ""
    stop_when: str = ""

    def is_empty(self) -> bool:
        return not any(getattr(self, name).strip() for name in _CONTRACT_FIELDS)

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in _CONTRACT_FIELDS}

    @classmethod
    def from_dict(cls, value: Any) -> GoalContract:
        return cls(**{name: str(value.get(name) or "").strip() for name in _CONTRACT_FIELDS}) if isinstance(value, dict) else cls()

    def render_block(self) -> str:
        return "\n".join(f"- {_CONTRACT_LABELS[name]}: {getattr(self, name).strip()}" for name in _CONTRACT_FIELDS if getattr(self, name).strip())


def parse_contract(text: str) -> tuple[str, GoalContract]:
    fields: dict[str, list[str]] = {name: [] for name in _CONTRACT_FIELDS}
    headline: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        key, sep, value = line.partition(":")
        field_name = _CONTRACT_ALIASES.get(key.strip().lower()) if sep else None
        (fields[field_name] if field_name else headline).append(value.strip() if field_name else line)
    return "\n".join(headline).strip(), GoalContract(**{name: "\n".join(parts).strip() for name, parts in fields.items()})

@dataclass
class GoalGate:
    command: str
    timeout_seconds: int = 120
    max_retries: int = 3
    attempts: int = 0
    last_exit_code: int | None = None
    output_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GoalGate:
        return cls(command=str(value.get("command") or ""), timeout_seconds=int(value.get("timeout_seconds") or 120), max_retries=int(value.get("max_retries") or 3), attempts=int(value.get("attempts") or 0), last_exit_code=value.get("last_exit_code"), output_tail=str(value.get("output_tail") or ""))

@dataclass
class GoalState:
    goal: str
    status: str = "active"
    turns_used: int = 0
    max_turns: int = DEFAULT_MAX_TURNS
    created_at: float = 0.0
    last_turn_at: float = 0.0
    last_verdict: str | None = None
    last_reason: str | None = None
    paused_reason: str | None = None
    consecutive_parse_failures: int = 0
    consecutive_transport_failures: int = 0
    subgoals: list[str] = field(default_factory=list)
    completed_subgoals: list[int] = field(default_factory=list)
    waiting_on_pid: int | None = None
    waiting_on_session: str | None = None
    waiting_until: float = 0.0
    waiting_on_delegations: int = 0
    waiting_reason: str | None = None
    waiting_since: float = 0.0
    contract: GoalContract = field(default_factory=GoalContract)
    gates: list[GoalGate] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> GoalState:
        data = json.loads(raw)
        data["contract"] = GoalContract.from_dict(data.get("contract"))
        data["gates"] = [GoalGate.from_dict(g) for g in data.get("gates", []) if isinstance(g, dict) and g.get("command")]
        data["subgoals"] = [str(item.get("text") or "") if isinstance(item, dict) else str(item)
                             for item in data.get("subgoals", [])]
        data["completed_subgoals"] = [int(i) for i in data.get("completed_subgoals", []) if str(i).isdigit()]
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})

    def has_contract(self) -> bool:
        return bool(self.contract and not self.contract.is_empty())

    def render_subgoals_block(self) -> str:
        return "\n".join(f"- [{'x' if i in self.completed_subgoals else ' '}] {i}. {text}"
                          for i, text in enumerate(self.subgoals, 1))

    def clear_wait(self) -> None:
        self.waiting_on_pid = self.waiting_on_session = self.waiting_reason = None
        self.waiting_until = self.waiting_since = 0.0
        self.waiting_on_delegations = 0


def _load(session_id: str, home: str | Path | None) -> GoalState | None:
    if home is None:
        return None
    from atlas.engine_core.state.hermes_state import SessionDB
    path = Path(home).expanduser().resolve() / "state.db"
    with SessionDB(db_path=path) as db:
        raw = db.get_meta(f"goal:{session_id}")
    try:
        return GoalState.from_json(raw) if raw else None
    except (ValueError, TypeError):
        return None


def _save(session_id: str, home: str | Path | None, state: GoalState | None) -> None:
    if home is None:
        return
    from atlas.engine_core.state.hermes_state import SessionDB
    path = Path(home).expanduser().resolve() / "state.db"
    with SessionDB(db_path=path) as db:
        key = f"goal:{session_id}"
        if state is None:
            # Keep historical semantics: clear stores a tombstone; use the exact legacy cleared shape.
            db.set_meta(key, json.dumps({"goal": "", "status": "cleared", "max_turns": DEFAULT_MAX_TURNS}, ensure_ascii=False))
        else:
            db.set_meta(key, state.to_json())


def goal_kick_prompt(goal: str, last_user_message: Any = None) -> str:
    suffix = f"\n\nUser's original request: {last_user_message}" if isinstance(last_user_message, str) and last_user_message.strip() else ""
    return f"[Working toward this goal]\n{goal}{suffix}\n\nMake concrete progress toward the goal. If it needs multiple steps, use the goal_subgoal tool to save concise, independently verifiable milestones before implementation, then mark each one complete only after finishing it. When resuming, list saved milestones and continue with the first incomplete one. Continue until all subgoals are complete, the goal is complete, or you are blocked."

class GoalManager:
    def __init__(self, session_id: str, *, home: str | Path | None = None, default_max_turns: int = DEFAULT_MAX_TURNS):
        self.session_id, self.home = session_id, home
        self.default_max_turns = int(default_max_turns or DEFAULT_MAX_TURNS)
        self._state = _load(session_id, home)

    @property
    def state(self) -> GoalState | None: return self._state
    def is_active(self) -> bool: return bool(self._state and self._state.status == "active")
    def has_goal(self) -> bool: return bool(self._state and self._state.goal)
    def has_contract(self) -> bool: return bool(self._state and self._state.has_contract())
    def _save(self):
        _save(self.session_id, self.home, self._state)
        return self._state
    def status_line(self) -> str:
        if not self._state: return "(no active goal)"
        s = self._state
        return f"⊙ Goal ({s.status}, {s.turns_used}/{s.max_turns} turns): {s.goal}"
    def set(self, goal: str, *, max_turns: int | None = None, contract: GoalContract | None = None) -> GoalState:
        goal = (goal or "").strip()
        if not goal: raise ValueError("goal text is empty")
        self._state = GoalState(goal=goal, max_turns=int(max_turns or self.default_max_turns), created_at=time.time(), contract=contract or GoalContract())
        return self._save()
    def set_contract(self, contract: GoalContract):
        if self._state: self._state.contract = contract or GoalContract(); return self._save()
        return None
    def pause(self, reason: str = "user-paused"):
        if self._state: self._state.status, self._state.paused_reason = "paused", reason; self._state.clear_wait(); return self._save()
        return None
    def resume(self, *, reset_budget: bool = True):
        if not self._state: return None
        self._state.status, self._state.paused_reason = "active", None; self._state.clear_wait()
        if reset_budget: self._state.turns_used = 0
        return self._save()
    def clear(self):
        if self._state: self._state.status = "cleared"; self._save(); self._state = None
    def mark_done(self, reason: str):
        if self._state: self._state.status, self._state.last_verdict, self._state.last_reason = "done", "done", reason; self._save()
    def _require(self):
        if not self.has_goal(): raise RuntimeError("no active goal")
        return self._state
    def add_subgoal(self, text: str):
        text = (text or "").strip()
        if not text: raise ValueError("subgoal text is empty")
        self._require().subgoals.append(text); self._save(); return text
    def remove_subgoal(self, index: int): return self._pop("subgoals", index)
    def clear_subgoals(self):
        return self._clear_items("subgoals")
    def render_subgoals(self): return self._state.render_subgoals_block() if self._state else "(no active goal)"
    def complete_subgoal(self, index: int, completed: bool = True):
        state = self._require(); index = int(index)
        if index < 1 or index > len(state.subgoals): raise IndexError(f"index out of range (1..{len(state.subgoals)})")
        done = set(state.completed_subgoals)
        (done.add if completed else done.discard)(index)
        state.completed_subgoals = sorted(done); self._save()
        return state.subgoals[index - 1]
    def add_gate(self, command: str, *, timeout_seconds=None, max_retries=None):
        gate = GoalGate((command or "").strip(), int(timeout_seconds or 120), int(max_retries or 3))
        if not gate.command: raise ValueError("gate command is empty")
        self._require().gates.append(gate); self._save(); return gate
    def remove_gate(self, index): return self._pop("gates", index).command
    def clear_gates(self): return self._clear_items("gates")
    def render_gates(self): return "\n".join(f"- {i}. $ {g.command}" for i, g in enumerate(self._state.gates, 1)) if self._state and self._state.gates else "(no quality gates)"
    def _pop(self, attr, index):
        items = getattr(self._require(), attr); idx = int(index) - 1
        if idx < 0 or idx >= len(items): raise IndexError(f"index out of range (1..{len(items)})")
        item = items.pop(idx)
        if attr == "subgoals":
            self._state.completed_subgoals = sorted(
                done - 1 if done > idx + 1 else done
                for done in self._state.completed_subgoals if done != idx + 1
            )
        self._save(); return item
    def _clear_items(self, attr):
        state = self._require(); count = len(getattr(state, attr)); setattr(state, attr, [])
        if attr == "subgoals": state.completed_subgoals = []
        self._save(); return count
    def wait_on(self, pid: int, reason: str = ""):
        s = self._require(); s.waiting_on_pid = int(pid); s.waiting_reason = reason; s.waiting_since = time.time(); self._save(); return s
    def stop_waiting(self):
        if not self._state or not (self._state.waiting_on_pid or self._state.waiting_on_session or self._state.waiting_until): return False
        self._state.clear_wait(); self._save(); return True
    def is_waiting(self):
        s = self._state
        if not s: return False
        waiting = bool(s.waiting_until and time.time() < s.waiting_until)
        if s.waiting_on_pid:
            import os
            try: os.kill(s.waiting_on_pid, 0); waiting = True
            except OSError: waiting = False
        if not waiting and (s.waiting_on_pid or s.waiting_until): self.stop_waiting()
        return waiting
    def next_continuation_prompt(self):
        s = self._state
        if not s or s.status != "active": return None
        remaining = [f"{i}. {text}" for i, text in enumerate(s.subgoals, 1) if i not in s.completed_subgoals]
        progress = "\nSubgoal progress (persisted):\n" + "\n".join(
            f"- [{'x' if i in s.completed_subgoals else ' '}] {i}. {text}" for i, text in enumerate(s.subgoals, 1)
        ) if s.subgoals else ""
        next_step = f"\nResume at the first incomplete subgoal: {remaining[0]}" if remaining else ""
        return goal_kick_prompt(s.goal + ("\n" + s.contract.render_block() if s.has_contract() else "") + progress + next_step)
    def render_contract(self): return self._state.contract.render_block() if self._state and self._state.has_contract() else "(no completion contract)"
    def evaluate_after_turn(self, response: str, *, judge: Callable | None = None, **kwargs):
        s = self._state
        if not s or s.status != "active": return {"status": s.status if s else None, "should_continue": False, "continuation_prompt": None, "verdict": "inactive", "reason": "no active goal", "message": ""}
        if self.is_waiting(): return {"status": "active", "should_continue": False, "continuation_prompt": None, "verdict": "waiting", "reason": s.waiting_reason or "wait barrier", "message": "Goal is waiting."}
        s.turns_used += 1; s.last_turn_at = time.time()
        if judge is None:
            s.last_verdict, s.last_reason = "continue", "Atlas goal judge has not been connected to this call site."
            if s.turns_used >= s.max_turns:
                s.status, s.paused_reason = "paused", "turn budget exhausted"
                self._save()
                return {"status": "paused", "should_continue": False, "continuation_prompt": None, "verdict": "continue", "reason": s.last_reason, "message": "Goal paused because its turn budget was exhausted."}
            self._save()
            return {"status": "active", "should_continue": False, "continuation_prompt": None, "verdict": "judge_unavailable", "reason": s.last_reason, "message": "Goal state was retained; no completion judge is wired."}
        verdict, reason = judge(s.goal, response, s)
        s.last_verdict, s.last_reason = verdict, reason
        if verdict == "done": s.status = "done"; self._save(); return {"status": "done", "should_continue": False, "continuation_prompt": None, "verdict": "done", "reason": reason, "message": f"Goal achieved: {reason}"}
        if verdict == "blocked": s.status, s.paused_reason = "paused", reason; self._save(); return {"status": "paused", "should_continue": False, "continuation_prompt": None, "verdict": "blocked", "reason": reason, "message": reason}
        self._save()
        return {"status": "active", "should_continue": True, "continuation_prompt": self.next_continuation_prompt(), "verdict": "continue", "reason": reason, "message": "Continuing toward goal."}
