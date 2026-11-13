from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

DEFAULT_MAX_TURNS = 256
MAX_PLAN_ATTEMPTS = 2
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


class GoalRevisionConflict(RuntimeError):
    """A goal write was based on an obsolete goal identity or revision."""

    def __init__(self, expected_id: str, expected_revision: int,
                 actual_id: str | None, actual_revision: int) -> None:
        super().__init__(
            f"stale goal revision: expected {expected_id or '<none>'}@{expected_revision}, "
            f"found {actual_id or '<none>'}@{actual_revision}"
        )
        self.expected_id = expected_id
        self.expected_revision = expected_revision
        self.actual_id = actual_id
        self.actual_revision = actual_revision


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
    goal_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    revision: int = 0
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
    decomposition_required: bool = True
    plan_attempts: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> GoalState:
        data = json.loads(raw)
        data["goal_id"] = str(data.get("goal_id") or "")
        try:
            data["revision"] = max(0, int(data.get("revision", 0)))
        except (TypeError, ValueError):
            data["revision"] = 0
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

    def needs_plan(self) -> bool:
        """True when this goal must be decomposed before execution continues.

        A goal that is already split, or was deliberately marked as needing no plan,
        is never blocked. This is what turns "please use goal_subgoal" from a prompt
        suggestion into an engine gate: the first turn of a fresh multi-step goal
        cannot be spent on implementation before the milestones exist.
        """
        if not self.decomposition_required:
            return False
        if self.plan_attempts >= MAX_PLAN_ATTEMPTS:
            return False
        return bool(self.goal.strip()) and not self.subgoals

    def render_plan_requirement(self) -> str:
        remaining = max(0, MAX_PLAN_ATTEMPTS - self.plan_attempts)
        warn = ""
        if remaining <= 1:
            warn = (
                "\nThis is the last planning turn. If no milestone is saved next turn, "
                "Atlas drops the plan gate and proceeds without a decomposition."
            )
        return _PLAN_REQUIREMENT + warn

    def clear_wait(self) -> None:
        self.waiting_on_pid = self.waiting_on_session = self.waiting_reason = None
        self.waiting_until = self.waiting_since = 0.0
        self.waiting_on_delegations = 0


def _load(session_id: str, home: str | Path | None) -> GoalState | None:
    if home is None:
        return None
    from atlas.engine.state.atlas_state import SessionDB
    path = Path(home).expanduser().resolve() / "state.db"
    with SessionDB(db_path=path) as db:
        raw = db.get_meta(f"goal:{session_id}")
    try:
        return GoalState.from_json(raw) if raw else None
    except (ValueError, TypeError):
        return None


def _save(
    session_id: str, home: str | Path | None, state: GoalState, *,
    expected_goal_id: str | None, expected_revision: int,
) -> int:
    next_revision = expected_revision + 1
    if home is None:
        state.revision = next_revision
        return next_revision
    from atlas.engine.state.atlas_state import SessionDB
    path = Path(home).expanduser().resolve() / "state.db"
    with SessionDB(db_path=path) as db:
        key = f"goal:{session_id}"

        def compare_and_save(conn):
            row = conn.execute("SELECT value FROM state_meta WHERE key = ?", (key,)).fetchone()
            current_raw = row[0] if row else None
            try:
                current_data = json.loads(current_raw) if current_raw else {}
                actual_revision = max(0, int(current_data.get("revision", 0)))
                actual_id = str(current_data.get("goal_id") or "") or None
            except (AttributeError, TypeError, ValueError):
                actual_revision, actual_id = 0, None
            if (actual_revision != expected_revision
                    or actual_id != (expected_goal_id or None)):
                raise GoalRevisionConflict(
                    expected_goal_id or "", expected_revision, actual_id, actual_revision,
                )
            state.revision = actual_revision + 1
            conn.execute(
                "INSERT INTO state_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, state.to_json()),
            )
            return state.revision

        try:
            return db._execute_write(compare_and_save)
        except GoalRevisionConflict:
            raise


_DRAFT_PROMPT = (
    "Turn this request into a completion contract. Return one JSON object with "
    "exactly these string keys: outcome, verification, constraints, boundaries, "
    "stop_when.\n\n"
    "outcome: the observable end state, not the effort.\n"
    "verification: the check that proves it, preferring a command or artifact "
    "over prose.\n"
    "constraints: what must not be violated while doing it.\n"
    "boundaries: files, systems, or data that are out of scope.\n"
    "stop_when: the condition that means stop rather than keep going.\n\n"
    "Leave a field as an empty string when the request genuinely does not say. "
    "Do not invent requirements, and do not restate the request as all five "
    "fields.\n\n"
    "REQUEST:\n{goal}"
)


def draft_contract(goal: str, *, complete: Callable[..., Any] | None = None) -> GoalContract | None:
    """Ask the routed model to turn a plain-language goal into a contract.

    Returns ``None`` rather than raising when no model is reachable: drafting is a
    convenience, and the caller already falls back to a free-form goal. ``complete``
    is an injectable ``(prompt) -> text`` callable so this stays testable without a
    live model; it is resolved lazily otherwise so importing this module never
    pulls in the model layer.
    """
    text = (goal or "").strip()
    if not text:
        return None
    if complete is None:
        try:
            complete = _routed_completion()
        except Exception:  # noqa: BLE001 - drafting is optional; any wiring fault means "no draft"
            return None
    if complete is None:
        return None
    try:
        raw = complete(_DRAFT_PROMPT.format(goal=text[:4000]))
    except Exception:  # noqa: BLE001 - a model/provider fault must fall back, not kill /goal
        return None
    payload = _json_object(str(raw or ""))
    if payload is None:
        return None
    contract = GoalContract.from_dict(payload)
    return None if contract.is_empty() else contract


def _json_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _routed_completion():
    """Bind ``(prompt) -> text`` to Atlas' routed model API, or ``None``."""
    try:
        from atlas import server as _server
    except Exception:  # noqa: BLE001 - goals.py must import standalone, outside a server
        return None
    manager = getattr(_server, "model_mgr", None)
    router = getattr(manager, "model_router", None)
    model = getattr(manager, "current_model", None)
    if router is None or not model:
        return None

    def complete(prompt: str) -> str:
        import asyncio

        result = asyncio.run(router.complete_for(
            model, "goal_draft", [{"role": "user", "content": prompt}], max_tokens=400,
        ))
        return str(getattr(result, "text", "") or "")

    return complete


_PLAN_REQUIREMENT = (
    "PLAN REQUIRED: this goal has no saved milestones yet. Spend this turn only on "
    "decomposition, then stop. Call the goal_subgoal tool once per milestone with "
    "action=\"add\" to persist 2-6 concise, independently verifiable milestones, "
    "ordered so each one is checkable on its own. Do not start implementing in this "
    "turn. Mark each milestone complete with action=\"complete\" only after it is "
    "actually finished."
)


def goal_kick_prompt(goal: str, last_user_message: Any = None, *, require_plan: bool = False, plan_attempts: int = 0) -> str:
    suffix = f"\n\nUser's original request: {last_user_message}" if isinstance(last_user_message, str) and last_user_message.strip() else ""
    body = f"[Working toward this goal]\n{goal}{suffix}\n\nMake concrete progress toward the goal. If it needs multiple steps, use the goal_subgoal tool to save concise, independently verifiable milestones before implementation, then mark each one complete only after finishing it. For every goal_subgoal mutation, include the current goal_id and revision shown below; if a revision conflict is returned, refresh goal progress before retrying. When resuming, list saved milestones and continue with the first incomplete one. Continue until all subgoals are complete, the goal is complete, or you are blocked."
    if require_plan:
        body += "\n\n" + _PLAN_REQUIREMENT
        if plan_attempts >= MAX_PLAN_ATTEMPTS - 1:
            body += (
                "\nThis is the last planning turn. If no milestone is saved this turn, "
                "Atlas drops the plan gate and proceeds without a decomposition."
            )
    return body

class GoalManager:
    def __init__(self, session_id: str, *, home: str | Path | None = None, default_max_turns: int = DEFAULT_MAX_TURNS):
        self.session_id, self.home = session_id, home
        self.default_max_turns = int(default_max_turns or DEFAULT_MAX_TURNS)
        self._state = _load(session_id, home)
        self._base_revision = int(self._state.revision) if self._state else 0
        self._base_goal_id = (self._state.goal_id or None) if self._state else None
        if self._state and self._state.goal and not self._state.goal_id:
            self._state.goal_id = uuid.uuid4().hex
            self._save()

    @property
    def state(self) -> GoalState | None: return self._state
    def is_active(self) -> bool: return bool(self._state and self._state.status == "active")
    def has_goal(self) -> bool: return bool(self._state and self._state.goal)
    def has_contract(self) -> bool: return bool(self._state and self._state.has_contract())
    def _save(self):
        if self._state is None:
            return None
        if not self._state.goal_id:
            self._state.goal_id = uuid.uuid4().hex
        try:
            revision = _save(
                self.session_id, self.home, self._state,
                expected_goal_id=self._base_goal_id,
                expected_revision=self._base_revision,
            )
        except GoalRevisionConflict:
            self._state = _load(self.session_id, self.home)
            self._base_revision = int(self._state.revision) if self._state else 0
            self._base_goal_id = (self._state.goal_id or None) if self._state else None
            raise
        self._base_revision = revision
        self._base_goal_id = self._state.goal_id
        return self._state

    def check_revision(self, goal_id: str | None, revision: int | None) -> None:
        if goal_id is None and revision is None:
            return
        state = self._state
        actual_id = state.goal_id if state else None
        actual_revision = state.revision if state else 0
        if (not isinstance(goal_id, str) or not goal_id
                or not isinstance(revision, int) or isinstance(revision, bool)
                or goal_id != actual_id or revision != actual_revision):
            raise GoalRevisionConflict(
                str(goal_id or ""), int(revision or 0), actual_id, actual_revision,
            )
    def status_line(self) -> str:
        if not self._state: return "(no active goal)"
        s = self._state
        line = f"⊙ Goal ({s.status}, {s.turns_used}/{s.max_turns} turns): {s.goal}"
        if s.needs_plan():
            return line + "\n  ↳ planning: no milestones saved yet — the next turn must decompose first"
        if s.subgoals:
            done = len([i for i in s.completed_subgoals if 0 < i <= len(s.subgoals)])
            return line + f"\n  ↳ plan: {done}/{len(s.subgoals)} milestones complete"
        return line
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
    def add_subgoal(self, text: str, *, expected_goal_id: str | None = None,
                    expected_revision: int | None = None):
        self.check_revision(expected_goal_id, expected_revision)
        text = (text or "").strip()
        if not text: raise ValueError("subgoal text is empty")
        self._require().subgoals.append(text); self._save(); return text
    def remove_subgoal(self, index: int): return self._pop("subgoals", index)
    def edit_subgoal(self, index: int, text: str):
        text = (text or "").strip()
        if not text: raise ValueError("subgoal text is empty")
        state = self._require(); index = int(index)
        if index < 1 or index > len(state.subgoals): raise IndexError(f"index out of range (1..{len(state.subgoals)})")
        state.subgoals[index - 1] = text; self._save(); return text
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
            # Never probe liveness with os.kill(pid, 0): on Windows that delivers a
            # real signal and terminates the watched process instead of testing it.
            from atlas.engine.goal_loop import pid_alive
            waiting = pid_alive(s.waiting_on_pid)
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
        require_plan = s.needs_plan()
        prompt = goal_kick_prompt(
            s.goal + ("\n" + s.contract.render_block() if s.has_contract() else "")
            + f"\nCurrent goal CAS token: goal_id={s.goal_id} revision={s.revision}."
            + progress + next_step,
            require_plan=require_plan,
            plan_attempts=s.plan_attempts,
        )
        prompt_revision = s.revision
        if require_plan:
            # Bounded gate: the model gets MAX_PLAN_ATTEMPTS planning turns, then
            # Atlas proceeds regardless. Without this a model that never calls
            # goal_subgoal would trap the goal in planning forever.
            s.plan_attempts += 1
            self._save()
        if s.revision != prompt_revision:
            prompt = prompt.replace(
                f"goal_id={s.goal_id} revision={prompt_revision}.",
                f"goal_id={s.goal_id} revision={s.revision}.",
            )
        return prompt
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
        try:
            verdict, reason = judge(s.goal, response, s)
        except Exception:  # noqa: BLE001 - a broken judge must not destroy the goal
            s.last_verdict = "judge_error"
            s.last_reason = "The goal judge raised; the goal was kept active without a verdict."
            self._save()
            return {"status": s.status, "should_continue": False, "continuation_prompt": None,
                    "verdict": "judge_error", "reason": s.last_reason,
                    "message": "Goal state was retained; the completion judge failed this turn."}
        s.last_verdict, s.last_reason = verdict, reason
        if verdict == "done": s.status = "done"; self._save(); return {"status": "done", "should_continue": False, "continuation_prompt": None, "verdict": "done", "reason": reason, "message": f"Goal achieved: {reason}"}
        if verdict == "blocked": s.status, s.paused_reason = "paused", reason; self._save(); return {"status": "paused", "should_continue": False, "continuation_prompt": None, "verdict": "blocked", "reason": reason, "message": reason}
        self._save()
        before = s.plan_attempts
        prompt = self.next_continuation_prompt()
        decision = {"status": "active", "should_continue": True, "continuation_prompt": prompt, "verdict": "continue", "reason": reason, "message": "Continuing toward goal."}
        if s.plan_attempts > before:
            # The next turn is a planning turn. Surface it so the driver can record
            # it and the UI can tell planning rounds apart from execution rounds.
            decision["planning_turn"] = True
            decision["plan_attempts"] = s.plan_attempts
            decision["max_plan_attempts"] = MAX_PLAN_ATTEMPTS
            decision["milestones"] = len(s.subgoals)
            decision["plan_gate_expiring"] = (MAX_PLAN_ATTEMPTS - s.plan_attempts) <= 1
        else:
            decision["planning_turn"] = False
            decision["plan_attempts"] = s.plan_attempts
            decision["milestones"] = len(s.subgoals)
        return decision
