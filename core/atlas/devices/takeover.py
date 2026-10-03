"""Desktop control state machine — FREE / HUMAN / AGENT plus handoff cards.

W5 of ATLAS-MEGA-PERSISTENT-ALWAYS-ON; semantics from the R3 lane report §4/§6.5
(OpenClaw ``session-registry`` + ``computer-transport`` takeover model):

Transition matrix (``request(actor)``; ``actor="user"`` is the human, anything
else is an agent id)::

    FREE  ──user request──────► HUMAN   granted
    FREE  ──agent request─────► AGENT   granted
    HUMAN  ──agent request────► (denied — the operator holds the machine)
    HUMAN  ──user request─────► HUMAN   re-assert (no control change)
    AGENT  ──user request─────► HUMAN   preemption granted, evict recorded
    AGENT  ──holder agent─────► AGENT   re-assert (no control change)
    AGENT  ──other agent──────► (denied)
    HUMAN/AGENT ──release(holder)──► FREE

Enforced invariants (structurally — there is no timer, no background task, and
no code path that mutates state outside ``request``/``release``):

1. **Never auto-takeover.**  Normal input never grabs control; only an explicit
   ``request``/``release`` call moves the state.
2. **Every control change forces re-observation.**  A granted transition or a
   release sets ``needs_observation=True``; the next input action must observe
   first (:meth:`assert_can_act`), matching ``COMPUTER_STALE_OBSERVATION``.
   Re-asserts by the current holder change nothing and keep the flag as-is.
3. **Observation is never blocked by takeover.**  ``observe()`` is legal in
   every state — a HUMAN takeover pauses agent *input*, not its eyes.
4. ``release()`` always returns the machine to FREE.

Side surfaces: a bounded activity ring buffer (default 200 events of
``{ts, seq, actor, action, detail}``) and in-memory handoff cards
(``PENDING → done | give_up``) for the "please take over" UX.
"""
from __future__ import annotations

import itertools
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

FREE = "FREE"
HUMAN = "HUMAN"
AGENT = "AGENT"

HUMAN_ACTOR = "user"
DEFAULT_ACTIVITY_CAPACITY = 200

RESOLUTION_DONE = "done"
RESOLUTION_GIVE_UP = "give_up"
_HANDOFF_RESOLUTIONS = (RESOLUTION_DONE, RESOLUTION_GIVE_UP)

_CONTROL_CHANGED = "control_changed"
_CONTROL_REASSERT = "control_reassert"
_CONTROL_DENIED = "control_denied"
_CONTROL_RELEASED = "control_released"
_ACTION = "action"
_HANDOFF_OPENED = "handoff_opened"
_HANDOFF_RESOLVED = "handoff_resolved"


class TakeoverError(Exception):
    """Illegal transition / unknown card — carries the HTTP status for the router."""

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


class ObservationRequiredError(TakeoverError):
    """An input action was attempted after a control change without observing."""

    def __init__(self, message: str = "控制权已变化，必须先观察（截图）再执行动作") -> None:
        super().__init__(message, status_code=409)


def is_human_actor(actor: str) -> bool:
    return str(actor or "").strip() == HUMAN_ACTOR


class TakeoverStateMachine:
    """Single control slot for the atlas-laptop desktop (``device_id="self"``).

    Purely in-memory and synchronous: control authority is runtime state, not
    durable product data.  A process restart therefore resets to FREE, which is
    the safe direction (never auto-AGENT).
    """

    def __init__(
        self,
        *,
        device_id: str = "self",
        clock: Callable[[], float] | None = None,
        activity_capacity: int = DEFAULT_ACTIVITY_CAPACITY,
    ) -> None:
        self.device_id = device_id
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._state: str = FREE
        self._holder: str | None = None
        self._since: float = float(self._clock())
        self._needs_observation: bool = False
        self._activity: deque[dict[str, Any]] = deque(maxlen=max(1, int(activity_capacity)))
        self._seq = itertools.count(1)
        self._handoff: dict[str, dict[str, Any]] = {}
        self._handoff_seq = itertools.count(1)

    # ------------------------------------------------------------ helpers
    def _now(self) -> float:
        return float(self._clock())

    def _record(self, actor: str, action: str, detail: str) -> dict[str, Any]:
        event = {
            "ts": self._now(),
            "seq": next(self._seq),
            "actor": actor,
            "action": action,
            "detail": detail,
        }
        self._activity.append(event)
        return event

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def holder(self) -> str | None:
        with self._lock:
            return self._holder

    @property
    def needs_observation(self) -> bool:
        with self._lock:
            return self._needs_observation

    # ------------------------------------------------------------- control
    def request(self, actor: str, *, note: str = "") -> dict[str, Any]:
        """Apply the transition matrix; returns the post-state snapshot.

        Raises :class:`TakeoverError` (denied) for HUMAN+agent and AGENT+other-agent.
        """
        actor = str(actor or "").strip()
        if not actor:
            raise TakeoverError("actor 不能为空", status_code=422)
        with self._lock:
            if self._state == HUMAN and not is_human_actor(actor):
                self._record(actor, _CONTROL_DENIED,
                             f"人类持有控制权，agent 请求被拒绝{self._note_suffix(note)}")
                raise TakeoverError("人类正在控制桌面，agent 不能接管")
            if self._state == AGENT and is_human_actor(actor):
                # Preemption is legal for the human and always recorded.
                evicted = self._holder or "agent"
                self._state, self._holder, self._since = HUMAN, HUMAN_ACTOR, self._now()
                self._needs_observation = True
                self._record(actor, _CONTROL_CHANGED,
                             f"人类抢占 agent（逐出 {evicted}）{self._note_suffix(note)}")
                return self.snapshot()
            if actor == self._holder:
                # Re-assert by the current holder: no control change, no re-observe.
                self._record(actor, _CONTROL_REASSERT, f"保持 {self._state}{self._note_suffix(note)}")
                return self.snapshot()
            if self._state != FREE:
                self._record(actor, _CONTROL_DENIED,
                             f"{self._state} 由 {self._holder} 持有{self._note_suffix(note)}")
                raise TakeoverError(f"控制权由 {self._holder} 持有")
            self._state = HUMAN if is_human_actor(actor) else AGENT
            self._holder, self._since = actor, self._now()
            self._needs_observation = True
            self._record(actor, _CONTROL_CHANGED, f"进入 {self._state}{self._note_suffix(note)}")
            return self.snapshot()

    def release(self, actor: str, *, note: str = "") -> dict[str, Any]:
        """Only the current holder may release; the machine always returns to FREE."""
        actor = str(actor or "").strip()
        if not actor:
            raise TakeoverError("actor 不能为空", status_code=422)
        with self._lock:
            if self._state == FREE:
                raise TakeoverError("当前没有控制权持有者", status_code=409)
            if actor != self._holder:
                self._record(actor, _CONTROL_DENIED,
                             f"非持有者请求释放（持有者 {self._holder}）")
                raise TakeoverError(f"控制权由 {self._holder} 持有，只有持有者可以释放")
            previous = self._state
            self._state, self._holder, self._since = FREE, None, self._now()
            self._needs_observation = True  # a control change, even down to FREE
            self._record(actor, _CONTROL_RELEASED,
                         f"{previous} → FREE{self._note_suffix(note)}")
            return self.snapshot()

    def observe(self, actor: str = HUMAN_ACTOR) -> dict[str, Any]:
        """Fresh observation (screenshot).  Legal in every state — takeover never
        blocks looking; it only blocks the next *input* until this is called."""
        with self._lock:
            if self._needs_observation:
                self._record(actor, "observed", "控制权变化后的首次观察")
            self._needs_observation = False
            return self.snapshot()

    def assert_can_act(self, actor: str = HUMAN_ACTOR) -> None:
        """Gate for input actions: a control change forces observe-before-act."""
        with self._lock:
            if self._needs_observation:
                self._record(actor, "action_blocked", "needs_observation 未清零")
                raise ObservationRequiredError()

    def record_action(self, actor: str, action: str, detail: str = "") -> None:
        """External callers log executed desktop actions into the activity feed."""
        with self._lock:
            self._record(actor, f"{_ACTION}:{action}", detail)

    # ------------------------------------------------------------- handoff
    def open_handoff(self, note: str = "", *, actor: str = HUMAN_ACTOR) -> dict[str, Any]:
        """Open a pending handoff card (PENDING until done / give_up)."""
        with self._lock:
            card = {
                "card_id": f"handoff-{next(self._handoff_seq):04d}-{uuid.uuid4().hex[:8]}",
                "note": str(note or ""),
                "status": "PENDING",
                "created_ts": self._now(),
                "created_by": actor,
                "resolved_ts": None,
                "resolved_by": None,
            }
            self._handoff[card["card_id"]] = card
            self._record(actor, _HANDOFF_OPENED, card["card_id"])
            return dict(card)

    def resolve_handoff(
        self, card_id: str, resolution: str, *, actor: str = HUMAN_ACTOR,
    ) -> dict[str, Any]:
        """Resolve a PENDING card to ``done`` or ``give_up`` (terminal, once)."""
        with self._lock:
            card = self._handoff.get(card_id)
            if card is None:
                raise TakeoverError(f"没有 id 为 {card_id!r} 的交接卡片", status_code=404)
            if resolution not in _HANDOFF_RESOLUTIONS:
                raise TakeoverError(
                    f"resolution 必须是 {' / '.join(_HANDOFF_RESOLUTIONS)}", status_code=422)
            if card["status"] != "PENDING":
                raise TakeoverError(f"卡片 {card_id} 已结算为 {card['status']}", status_code=409)
            card["status"] = resolution
            card["resolved_ts"] = self._now()
            card["resolved_by"] = actor
            self._record(actor, _HANDOFF_RESOLVED, f"{card_id} → {resolution}")
            return dict(card)

    def handoff_cards(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            cards = [dict(card) for card in self._handoff.values()]
        if status:
            cards = [card for card in cards if card["status"] == status]
        cards.sort(key=lambda card: card["created_ts"])
        return cards

    # ------------------------------------------------------------ snapshots
    def activity(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Oldest-first copy of the ring buffer (newest last), optionally tail-limited."""
        with self._lock:
            events = list(self._activity)
        return events[-limit:] if limit else events

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            pending = sum(1 for card in self._handoff.values() if card["status"] == "PENDING")
            return {
                "device_id": self.device_id,
                "state": self._state,
                "holder": self._holder,
                "needs_observation": self._needs_observation,
                "since_ts": self._since,
                "pending_handoff": pending,
            }

    @staticmethod
    def _note_suffix(note: str) -> str:
        return f"（{note}）" if str(note or "").strip() else ""


__all__ = [
    "AGENT",
    "DEFAULT_ACTIVITY_CAPACITY",
    "FREE",
    "HUMAN",
    "HUMAN_ACTOR",
    "ObservationRequiredError",
    "RESOLUTION_DONE",
    "RESOLUTION_GIVE_UP",
    "TakeoverError",
    "TakeoverStateMachine",
    "is_human_actor",
]
