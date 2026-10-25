"""Group chat orchestration: the server-side room engine (integration-map §2 W8).

Port of the Hermes group-round semantics (r4 §3.3), authority for this module:

- **room log**: shared per-group timeline, in memory + ``<group_id>/log.jsonl``
  append; every entry carries a monotonic ``seq``.
- **watermarks**: per-(thread, member) read position — a member's prompt only
  contains log entries after its watermark, so members are stateless across
  restarts (watermarks + epochs persist in ``<group_id>/state.json``).
- **deterministic @ resolution**: explicit ``@id`` / ``@name`` / ``@"multi word"``
  (or ``@everyone``) selects exactly the named members, in member-list order;
  without mentions every member round-robins in member-list order. No LLM
  routing anywhere — serial rotation only.
- **round engine**: one speaking slot per member per round (rotation start
  shifts by one each round); ``(pass)`` keeps silence; ``max_rounds`` /
  ``max_messages`` / ``max_continuations`` cap the drive independently. Exit is
  ``settled`` (a full round where nobody spoke) vs ``capped`` (a hard limit
  truncated an active conversation) vs ``stopped`` (epoch bump).
- **@mention continuation = handoff**: a member's reply naming a teammate gives
  that teammate the immediately next speaking slot, ahead of the rotation,
  bounded by ``max_continuations``; handoffs beyond the budget are dropped and
  reported.
- **stranded harvest**: a member message arriving after its drive ended is
  logged as a ``stranded`` event and never replayed into later prompt windows.
- **epoch / stop**: :meth:`GroupOrchestrator.stop` bumps the thread epoch; a
  running drive terminates at the next member boundary with status ``stopped``.

Model turns go through the injected :class:`TurnDispatcher` (integration binds
the real chain; tests bind fakes). Member session keys come from
:func:`atlas.persistent_agents.session_key` — the single W1 implementation.
This module never imports channels/heartbeat and never touches the model loop.
"""

from __future__ import annotations

import inspect
import json
import re
from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from atlas.groups.store import GroupService, MemberLookup, default_round_caps
from atlas.persistent_agents import session_key

__all__ = [
    "DEFAULT_THREAD_ID",
    "DispatcherNotBound",
    "GroupOrchestrator",
    "GroupTurnReport",
    "PASS_TEXTS",
    "TurnConflict",
    "TurnDispatcher",
    "unbound_dispatcher",
]

DEFAULT_THREAD_ID = "main"
PASS_TEXTS = frozenset({"", "(pass)"})

_LOG_NAME = "log.jsonl"
_STATE_NAME = "state.json"

_THREAD_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_MENTION_RE = re.compile(r'@(?:"([^"]{1,64})"|([A-Za-z0-9_\-\u4e00-\u9fff]{1,64}))')
_EVERYONE_TOKENS = frozenset({"everyone"})


class TurnConflict(RuntimeError):  # noqa: N818 —— 面向调用方语义：409 conflict，保持无后缀
    """A drive is already running for this (group, thread)."""


class DispatcherNotBound(RuntimeError):  # noqa: N818 —— 路由映射 503，保持无后缀
    """Raised by the placeholder dispatcher before integration binds the real chain."""


class TurnDispatcher(Protocol):
    """Model-turn seam: ``(agent_id, prompt, session_key, context) -> str | Awaitable[str]``."""

    def __call__(
        self, agent_id: str, prompt: str, session_key: str, context: dict[str, Any],
    ) -> str | Awaitable[str]: ...


def unbound_dispatcher(
    agent_id: str, prompt: str, session_key: str, context: dict[str, Any],
) -> str:
    raise DispatcherNotBound(
        "no group turn dispatcher bound; construct GroupOrchestrator(dispatcher=...) at integration"
    )


@dataclass
class GroupTurnReport:
    """Outcome of one drive (r4: exit distinguishes settled vs capped vs stopped)."""

    group_id: str
    thread_id: str
    status: str                 # "settled" | "capped" | "stopped"
    capped_by: str | None       # "max_rounds" | "max_messages" | None
    rounds: int
    messages: int
    continuations: int
    speakers: list[str]
    passes: list[str]
    dropped_handoffs: list[str]
    started_seq: int
    ended_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "thread_id": self.thread_id,
            "status": self.status,
            "capped_by": self.capped_by,
            "rounds": self.rounds,
            "messages": self.messages,
            "continuations": self.continuations,
            "speakers": list(self.speakers),
            "passes": list(self.passes),
            "dropped_handoffs": list(self.dropped_handoffs),
            "started_seq": self.started_seq,
            "ended_seq": self.ended_seq,
        }


class GroupOrchestrator:
    """Room log + watermarks + deterministic round engine over group definitions."""

    def __init__(
        self,
        service: GroupService,
        dispatcher: TurnDispatcher | None = None,
        member_lookup: MemberLookup | None = None,
        log_root: Path | None = None,
        delta_window: int = 16,
        delta_char_budget: int = 4000,
    ) -> None:
        self._service = service
        self._dispatcher = dispatcher or unbound_dispatcher
        self._lookup = member_lookup
        self._log_root = Path(log_root) if log_root is not None else service.store.root
        self._delta_window = delta_window
        self._delta_chars = delta_char_budget
        # In-memory projections, reloaded from disk per group on first touch.
        self._entries: dict[str, list[dict[str, Any]]] = {}
        self._seq: dict[str, int] = {}
        self._epochs: dict[tuple[str, str], int] = {}
        self._watermarks: dict[tuple[str, str, str], int] = {}
        self._running: set[tuple[str, str]] = set()
        self._loaded: set[str] = set()

    # -- drive entry ----------------------------------------------------------

    async def run_turn(self, group_id: str, incoming: dict[str, Any]) -> GroupTurnReport:
        """Append ``incoming`` to the room log, then drive rounds until quiet/capped/stopped.

        ``incoming = {"from_actor": "user" | agent_id, "text": str, "thread_id"?: str}``.
        """
        group = self._require_group(group_id)
        if not group.get("enabled", True):
            raise ValueError(f"group is disabled: {group_id}")
        incoming = incoming or {}
        text = incoming.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text is required")
        thread_id = self._thread(incoming.get("thread_id"))
        from_actor = str(incoming.get("from_actor") or "user")
        members = self._member_records(group)
        if from_actor != "user" and from_actor not in {m["id"] for m in members}:
            raise ValueError(f"from_actor must be 'user' or a group member: {from_actor}")
        key = (group_id, thread_id)
        if key in self._running:
            raise TurnConflict(f"turn already running for {group_id}/{thread_id}")

        self._load(group_id)
        drive_epoch = self._epochs.get(key, 0)
        entry = self._append(
            group_id, thread_id=thread_id,
            kind="user" if from_actor == "user" else "member",
            actor=from_actor, text=text.strip(),
        )
        from atlas.channels.routing import resolve_group_recipients

        mentions = incoming.get("mentions", [])
        if not isinstance(mentions, list):
            raise ValueError("mentions must be a list of normalized mention names")
        route = resolve_group_recipients(
            members, entry["text"], mentions=[str(value) for value in mentions],
            role=str(incoming.get("role") or ""),
            topic_routes=group.get("topic_routes", []),
            default_route=group.get("default_route", []),
            fallback=str(group.get("route_fallback") or "broadcast"),
        )
        target_ids = set(route["agent_ids"])
        responders = [m for m in members if m["id"] in target_ids and m["id"] != from_actor]
        if route["reason"] != "fallback":
            self._append(
                group_id, thread_id=thread_id, kind="event", actor="system",
                text=(f"route.{route['reason']} · rule={route['matched_rule']} · "
                      f"targets={', '.join('@' + item['id'] for item in responders) or '(none)'}"),
            )

        self._running.add(key)
        try:
            return await self._drive(group, thread_id, responders, drive_epoch, entry["seq"])
        finally:
            self._running.discard(key)
            self._save_state(group_id)

    def stop(self, group_id: str, thread_id: str | None = None) -> dict[str, Any]:
        """Bump the thread epoch; a running drive ends at the next member boundary."""
        self._require_group(group_id)
        thread_id = self._thread(thread_id or DEFAULT_THREAD_ID)
        self._load(group_id)
        epoch = self._epochs.get((group_id, thread_id), 0) + 1
        self._epochs[(group_id, thread_id)] = epoch
        self._append(
            group_id, thread_id=thread_id, kind="event", actor="user",
            text=f"stopped (epoch {epoch})",
        )
        self._save_state(group_id)
        return {"group_id": group_id, "thread_id": thread_id, "epoch": epoch}

    def epoch(self, group_id: str, thread_id: str | None = None) -> int:
        self._load(group_id)
        return self._epochs.get((group_id, self._thread(thread_id or DEFAULT_THREAD_ID)), 0)

    def submit_member_message(
        self, group_id: str, actor: str, text: str, thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a member message that arrived outside its own drive slot.

        While a drive is running it joins the room log as a normal member
        message; after the turn ended it is a *stranded* event — recorded for
        the timeline but never replayed into later prompt windows (r4 harvest
        semantics, Atlas: no replay).
        """
        group = self._require_group(group_id)
        thread_id = self._thread(thread_id or DEFAULT_THREAD_ID)
        if actor not in {m["id"] for m in self._member_records(group)}:
            raise ValueError(f"not a group member: {actor}")
        kind = "member" if (group_id, thread_id) in self._running else "stranded"
        return self._append(
            group_id, thread_id=thread_id, kind=kind, actor=actor, text=str(text).strip(),
        )

    def timeline(
        self, group_id: str, thread_id: str | None = None,
        limit: int = 50, before_seq: int | None = None,
    ) -> dict[str, Any]:
        """Paginated room log (ascending seq); ``before_seq`` is exclusive."""
        self._require_group(group_id)
        self._load(group_id)
        entries = [
            entry for entry in self._entries.get(group_id, [])
            if (thread_id is None or entry["thread_id"] == thread_id)
            and (before_seq is None or entry["seq"] < before_seq)
        ]
        page = entries[-limit:] if isinstance(limit, int) and limit > 0 else entries
        return {
            "group_id": group_id,
            "thread_id": thread_id,
            "entries": page,
            "next_before_seq": page[0]["seq"] if page and len(entries) > len(page) else None,
        }

    # -- round engine ---------------------------------------------------------

    async def _drive(
        self, group: dict[str, Any], thread_id: str,
        responders: list[dict[str, str]], drive_epoch: int, started_seq: int,
    ) -> GroupTurnReport:
        group_id = group["id"]
        caps = group.get("round_caps") or default_round_caps()
        members = self._member_records(group)
        members_by_id = {m["id"]: m for m in members}
        rounds = messages = continuations = 0
        handoffs: deque[str] = deque()
        speakers: list[str] = []
        passes: list[str] = []
        dropped: list[str] = []
        status = "settled"
        capped_by: str | None = None
        total = len(responders)

        def boundary() -> str | None:
            if self._epochs.get((group_id, thread_id), 0) != drive_epoch:
                return "stopped"
            if messages >= caps["max_messages"]:
                return "capped_messages"
            return None

        while True:
            signal = boundary()
            if signal == "stopped":
                status = "stopped"
                break
            if signal:
                status, capped_by = "capped", "max_messages"
                break
            if rounds >= caps["max_rounds"]:
                status, capped_by = "capped", "max_rounds"
                break
            rounds += 1
            queue = [responders[(rounds - 1 + i) % total]["id"] for i in range(total)]
            any_reply = False
            aborted: str | None = None
            # Handoff slots have strict priority over the rotation queue: a
            # mention hands the immediately next slot to the named teammate.
            while queue or handoffs:
                from_handoff = False
                if handoffs:
                    if continuations >= caps["max_continuations"]:
                        dropped.extend(handoffs)
                        handoffs.clear()
                        continue
                    signal = boundary()
                    if signal:
                        aborted = signal
                        break
                    member_id = handoffs.popleft()
                    from_handoff = True
                    continuations += 1
                    if member_id in queue:  # their rotation slot is superseded
                        queue.remove(member_id)
                else:
                    signal = boundary()
                    if signal:
                        aborted = signal
                        break
                    member_id = queue.pop(0)
                reply = await self._member_turn(
                    group, thread_id, members_by_id[member_id], members, rounds,
                    is_continuation=from_handoff,
                )
                if reply is None:
                    passes.append(member_id)
                    continue
                any_reply = True
                messages += 1
                speakers.append(member_id)
                for target in self._parse_mentions(reply, members):
                    if target != member_id and target not in handoffs:
                        handoffs.append(target)
            if aborted == "stopped":
                status = "stopped"
                break
            if aborted:
                status, capped_by = "capped", "max_messages"
                break
            if not any_reply:
                status = "settled"  # consensus quiet: a full round with no speaker
                break
        return GroupTurnReport(
            group_id=group_id, thread_id=thread_id, status=status, capped_by=capped_by,
            rounds=rounds, messages=messages, continuations=continuations,
            speakers=speakers, passes=passes, dropped_handoffs=dropped,
            started_seq=started_seq, ended_seq=self._seq.get(group_id, 0),
        )

    async def _member_turn(
        self, group: dict[str, Any], thread_id: str, member: dict[str, str],
        members: list[dict[str, str]], round_no: int, is_continuation: bool,
    ) -> str | None:
        """Dispatch one model turn; returns the reply text, or None on pass/failure."""
        group_id = group["id"]
        agent_id = member["id"]
        delta = self._delta(group_id, thread_id, agent_id)
        prompt = self._build_prompt(group, thread_id, member, members, delta)
        skey = session_key(agent_id, peer=group_id, group=True)
        context = {
            "group_id": group_id,
            "thread_id": thread_id,
            "session_key": skey,
            "round": round_no,
            "continuation": is_continuation,
            "delta": [dict(entry) for entry in delta],
        }
        try:
            result = self._dispatcher(agent_id, prompt, skey, context)
            if inspect.isawaitable(result):
                result = await result
        except (DispatcherNotBound, TurnConflict):
            raise
        except Exception as exc:  # a failed member turn must not kill the drive
            self._append(
                group_id, thread_id=thread_id, kind="event", actor=agent_id,
                text=f"turn-failed: {exc}",
            )
            self._advance(group_id, thread_id, agent_id)
            return None
        text = str(result or "").strip()
        if not text or text.lower() in PASS_TEXTS:
            self._advance(group_id, thread_id, agent_id)
            return None
        self._append(group_id, thread_id=thread_id, kind="member", actor=agent_id, text=text)
        self._advance(group_id, thread_id, agent_id)
        return text

    # -- room log / state -----------------------------------------------------

    def _log_path(self, group_id: str) -> Path:
        return self._log_root / group_id / _LOG_NAME

    def _state_path(self, group_id: str) -> Path:
        return self._log_root / group_id / _STATE_NAME

    def _load(self, group_id: str) -> None:
        if group_id in self._loaded:
            return
        self._loaded.add(group_id)
        entries: list[dict[str, Any]] = []
        path = self._log_path(group_id)
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # torn tail write
        self._entries[group_id] = entries
        self._seq[group_id] = max((entry["seq"] for entry in entries), default=0)
        state_path = self._state_path(group_id)
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {}
            for thread, value in (state.get("epochs") or {}).items():
                self._epochs[(group_id, thread)] = int(value)
            for key, value in (state.get("watermarks") or {}).items():
                thread, _, member = key.rpartition("::")
                if thread and member:
                    self._watermarks[(group_id, thread, member)] = int(value)

    def _save_state(self, group_id: str) -> None:
        payload = {
            "epochs": {
                thread: epoch for (gid, thread), epoch in self._epochs.items() if gid == group_id
            },
            "watermarks": {
                f"{thread}::{member}": seq
                for (gid, thread, member), seq in self._watermarks.items() if gid == group_id
            },
        }
        path = self._state_path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def _append(
        self, group_id: str, *, thread_id: str, kind: str, actor: str, text: str,
    ) -> dict[str, Any]:
        self._load(group_id)
        entry = {
            "seq": self._seq.get(group_id, 0) + 1,
            "ts": datetime.now(UTC).isoformat(),
            "group_id": group_id,
            "thread_id": thread_id,
            "kind": kind,       # user | member | stranded | event
            "actor": actor,
            "text": text,
        }
        self._seq[group_id] = entry["seq"]
        self._entries.setdefault(group_id, []).append(entry)
        path = self._log_path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _advance(self, group_id: str, thread_id: str, agent_id: str) -> None:
        self._watermarks[(group_id, thread_id, agent_id)] = self._seq.get(group_id, 0)

    def _delta(self, group_id: str, thread_id: str, agent_id: str) -> list[dict[str, Any]]:
        self._load(group_id)
        floor = self._watermarks.get((group_id, thread_id, agent_id), 0)
        return [
            entry for entry in self._entries.get(group_id, [])
            if entry["thread_id"] == thread_id and entry["seq"] > floor
            and entry["kind"] in {"user", "member"}  # stranded/event never replayed
        ]

    # -- prompt construction (r4 group-round-prompt shape) ---------------------

    def _build_prompt(
        self, group: dict[str, Any], thread_id: str, member: dict[str, str],
        members: list[dict[str, str]], delta: list[dict[str, Any]],
    ) -> str:
        title = group["name"] + (f" · {thread_id}" if thread_id != DEFAULT_THREAD_ID else "")
        lines = [
            f'[Group chat: "{title}"] You are @{member["id"]}, one participant of this group chat.',
            "Participants: "
            + ", ".join(f"@{m['id']} ({m['name']})" for m in members)
            + ", plus the human user.",
            'Rules: exactly one message per turn; reply "(pass)" to stay silent; '
            "mention a teammate with @id or @name to hand the conversation over.",
        ]
        if delta:
            chosen, omitted = self._delta_lines(delta, member)
            lines.append("--- Messages since your last turn ---")
            if omitted > 0:
                lines.append(f"({omitted} earlier messages omitted)")
            lines.extend(chosen)
        else:
            lines.append("--- No messages since your last turn. ---")
        lines.append('It is your turn now. Reply with your single group message, or "(pass)".')
        return "\n".join(lines)

    def _delta_lines(
        self, delta: list[dict[str, Any]], member: dict[str, str],
    ) -> tuple[list[str], int]:
        """Newest-first pick under entry-count/char budgets (r4 formatGroupDeltaLines)."""
        window = delta[-self._delta_window:]
        chosen: list[str] = []
        used = 0
        for entry in reversed(window):
            line = self._format_delta_line(entry, member)
            if chosen and used + len(line) > self._delta_chars:
                break
            chosen.append(line)
            used += len(line)
        chosen.reverse()
        return chosen, len(delta) - len(chosen)

    @staticmethod
    def _format_delta_line(entry: dict[str, Any], member: dict[str, str]) -> str:
        actor = entry["actor"]
        if actor == "user":
            return f"user: {entry['text']}"
        if actor == member["id"]:
            return f"@{actor} (you): {entry['text']}"
        return f"@{actor}: {entry['text']}"

    # -- helpers ---------------------------------------------------------------

    def _require_group(self, group_id: str) -> dict[str, Any]:
        group = self._service.get(group_id)
        if group is None:
            raise KeyError(f"group not found: {group_id}")
        return group

    @staticmethod
    def _thread(value: Any) -> str:
        text = str(value or DEFAULT_THREAD_ID).strip() or DEFAULT_THREAD_ID
        if not _THREAD_RE.fullmatch(text):
            raise ValueError("thread_id must match [A-Za-z0-9._-]{1,64}")
        return text

    def _member_records(self, group: dict[str, Any]) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        for agent_id in group.get("member_agent_ids", []):
            name = agent_id
            if self._lookup is not None:
                found = self._lookup.get(agent_id)
                if found and found.get("name"):
                    name = str(found["name"])
            aliases: list[str] = []
            if self._lookup is not None:
                found = self._lookup.get(agent_id) or {}
                agent_config = found.get("agent") or {}
                for binding in agent_config.get("channels", []) or []:
                    aliases.extend(str(alias) for alias in binding.get("mention_names", []) or [])
            records.append({"id": agent_id, "name": name, "mention_names": list(dict.fromkeys(aliases))})
        return records

    @staticmethod
    def _parse_mentions(text: str, members: list[dict[str, str]]) -> list[str]:
        """Deterministic @ resolution; result is always in member-list order."""
        found: set[str] = set()
        for match in _MENTION_RE.finditer(text):
            token = (match.group(1) or match.group(2) or "").strip()
            if not token:
                continue
            if token.lower() in _EVERYONE_TOKENS:
                found.update(m["id"] for m in members)
                continue
            for m in members:
                if token == m["id"] or token.lower() == m["name"].lower():
                    found.add(m["id"])
        return [m["id"] for m in members if m["id"] in found]
