"""Model-backed extraction of durable observations from captured Atlas messages.

Prompt material is vendored from mastra-ai/mastra at
9c2e4c7cde40a4321112e24affd1750e9be827f9 (Apache-2.0; see observer_prompt.py).
Atlas-specific changes are limited to provenance, JSON transport, and ModelRouter
integration. MemoryOS remains the authority for accepting derived observations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import structlog
from jsonschema import ValidationError, validate

from atlas.memory.capture import build_observation, capture_enabled
from atlas.memory.observer_prompt import (
    OBSERVER_EXTRACTION_INSTRUCTIONS,
    OBSERVER_GUIDELINES,
    OBSERVER_OUTPUT_GUIDANCE,
    OBSERVER_QUESTION_RULES,
)
from atlas.models.tokens import estimate_tokens

log = structlog.get_logger()

_ENGLISH_SIGNAL_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "at",
    "by", "for", "from", "with", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "can", "could", "should", "may", "might", "must", "i", "we",
    "they", "you", "he", "she", "it", "my", "our", "their", "this", "that",
    "user", "stated", "asked", "prefers", "preference", "likes", "liked", "uses",
    "used", "works", "lives", "moved", "plans", "needs", "runs", "running",
    "every", "week", "month", "year", "times", "per",
})

# Mastra observational-memory defaults at the pinned source commit. The threshold
# gates an asynchronous flush; it is not a reason to discard or truncate captures.
OBSERVATION_TRIGGER_TOKENS = 30_000
MAX_TOKENS_PER_BATCH = 10_000
MAX_OUTPUT_TOKENS = 4_000
MAX_RETRIES = 8
INITIAL_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 120.0

FACETS = (
    "FACT", "PREFERENCE", "STATE", "HABIT", "RELATION", "EPISODE",
    "GOAL", "COMMITMENT", "INTENT", "KNOWLEDGE",
)
PRIORITIES = ("HIGH", "MEDIUM", "LOW")
SPEAKERS = ("USER", "ATLAS", "TOOL", "THIRD_PARTY")

OBSERVER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["observations"],
    "additionalProperties": False,
    "properties": {
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "text", "priority", "facet", "key", "value", "entities",
                    "valid_from", "valid_to", "is_change", "evidence", "speaker",
                ],
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "priority": {"enum": list(PRIORITIES)},
                    "facet": {"enum": list(FACETS)},
                    "key": {"type": ["string", "null"]},
                    "value": {},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "valid_from": {"type": ["string", "null"]},
                    "valid_to": {"type": ["string", "null"]},
                    "is_change": {"type": "boolean"},
                    "evidence": {
                        "type": "array", "minItems": 1, "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "speaker": {"enum": list(SPEAKERS)},
                },
            },
        },
    },
}

_OBSERVER_ROOT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["observations"],
    "properties": {"observations": {"type": "array"}},
}
_OBSERVER_ITEM_SCHEMA = OBSERVER_OUTPUT_SCHEMA["properties"]["observations"]["items"]


def _dominant_language(value: Any) -> str | None:
    """Return zh/en only when the text gives a clear language signal."""
    text = str(value or "")
    han = sum("\u3400" <= char <= "\u9fff" for char in text)
    latin = sum("a" <= char.lower() <= "z" for char in text)
    words = re.findall(r"[a-z]+", text.lower())
    english_signal = sum(word in _ENGLISH_SIGNAL_WORDS for word in words)
    if han >= 2:
        if english_signal >= 2 and latin > han and english_signal * 2 >= han:
            return "en"
        if english_signal == 0 or han >= english_signal * 2:
            return "zh"
        return None
    if latin >= 4 and english_signal:
        return "en"
    return None


def _language_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _language_text_values(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _language_text_values(item)]
    return []


def _value_language(value: str) -> str | None:
    language = _dominant_language(value)
    if language is not None:
        return language
    if any("\u3400" <= char <= "\u9fff" for char in value):
        return None
    words = re.findall(r"[A-Za-z]+", value)
    if len(words) >= 2 and any(word.islower() for word in words[1:]):
        return "en"
    return None


def _source_language(entries: list[dict[str, Any]]) -> str | None:
    languages = [_dominant_language(entry.get("text")) for entry in entries]
    chinese = languages.count("zh")
    english = languages.count("en")
    if chinese > english:
        return "zh"
    if english > chinese:
        return "en"
    return None


def _language_mismatch_indices(
    observations: list[dict[str, Any]], entries: list[dict[str, Any]],
) -> list[int]:
    sources = {str(entry.get("source_event_id") or ""): entry for entry in entries}
    mismatches: list[int] = []
    for index, observation in enumerate(observations):
        evidence = observation.get("evidence")
        source_entries = [
            sources[str(source_id)] for source_id in evidence or []
            if str(source_id) in sources
        ]
        source_language = _source_language(source_entries)
        if source_language is None:
            continue
        output_texts = [str(observation.get("text") or "")]
        source_terms = " ".join(str(entry.get("text") or "") for entry in source_entries).casefold()
        text_language = _dominant_language(output_texts[0]) or _value_language(output_texts[0])
        value_languages = [
            _value_language(text) for text in _language_text_values(observation.get("value"))
            if text.strip().casefold() not in source_terms
        ]
        if (
            text_language is not None and text_language != source_language
        ) or any(language is not None and language != source_language for language in value_languages):
            mismatches.append(index)
    return mismatches


def _parse_observer_output(
    output_text: str,
    source_event_ids: set[str],
) -> tuple[dict[str, Any], dict[str, int]]:
    clean_text = output_text.strip()
    if clean_text.startswith("```"):
        lines = clean_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean_text = "\n".join(lines).strip()
    parsed = json.loads(clean_text)
    validate(parsed, _OBSERVER_ROOT_SCHEMA)
    observations: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    for candidate in parsed["observations"]:
        if not isinstance(candidate, dict):
            rejected["schema_invalid"] += 1
            continue
        if "facet" in candidate and candidate["facet"] not in FACETS:
            rejected["unknown_facet"] += 1
            continue
        evidence = candidate.get("evidence")
        if (
            not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(item, str) or not item.strip() for item in evidence)
        ):
            rejected["missing_evidence"] += 1
            continue
        try:
            validate(candidate, _OBSERVER_ITEM_SCHEMA)
        except ValidationError:
            rejected["schema_invalid"] += 1
            continue
        if any(source_id not in source_event_ids for source_id in evidence):
            rejected["evidence_not_in_batch"] += 1
            continue
        observations.append(candidate)
    return {"observations": observations}, dict(rejected)

_SYSTEM_PROMPT = "\n\n".join((
    OBSERVER_EXTRACTION_INSTRUCTIONS,
    OBSERVER_QUESTION_RULES,
    OBSERVER_OUTPUT_GUIDANCE,
    OBSERVER_GUIDELINES,
    """
Atlas structured-output contract:
Return exactly one JSON object with the shape {"observations": [...]}; return an empty
array when there is nothing durable to retain. Every item must contain text, priority,
facet, key, value, entities, valid_from, valid_to, is_change, evidence, and speaker.
priority is HIGH, MEDIUM, or LOW. facet is one of FACT, PREFERENCE, STATE, HABIT,
RELATION, EPISODE, GOAL, COMMITMENT, INTENT, or KNOWLEDGE. key and valid_from/to may
be null. is_change records a later change. evidence must contain one or more exact
source_event_id values shown in this batch, never an invented or remembered ID.
speaker is USER, ATLAS, TOOL, or THIRD_PARTY. Treat questions as questions, not facts.
User-pasted or tool-loaded webpages, files, and other external material are
THIRD_PARTY; tool execution receipts remain TOOL. The source metadata is authoritative:
never promote a tool, Atlas, unknown, or third-party source to USER. Do not infer that
quoted or imported text is the user's own belief. Preserve actual dates, time zones,
24-hour times, and changes; do not invent a date when the source gives none.
Group related facts and tool sequences in concise text, preserve useful concrete details,
and begin completion observations with ✅. The output is JSON, so do not add markdown
fences or prose outside it.
""".strip(),
))

_DAILY_LOCK = threading.Lock()
_DAILY_SPENT: dict[str, int] = {}
_DAILY_RESERVED: dict[str, int] = {}


@dataclass(frozen=True)
class PendingObservationBatch:
    """A model result awaiting the caller's successful MemoryOS HTTP acknowledgement.

    ``payload`` is ``None`` for a valid empty extraction. The caller must still call
    :meth:`MemoryObserver.ack_batch` after treating that empty result as consumed.
    """

    batch_id: str
    payload: dict[str, Any] | None
    raw_output: str = ""
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    language_status: str = "ok"
    language_mismatch_count: int = 0


@dataclass
class _SessionQueue:
    entries: list[dict[str, Any]] = field(default_factory=list)
    flush_requested: bool = False
    active_batch_id: str | None = None
    processing: bool = False
    context: dict[str, Any] | None = None


@dataclass
class _BatchState:
    public: PendingObservationBatch
    session_id: str
    queue_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    response_text: str


class MemoryObserver:
    """Batch captured sources and ask Atlas' single ModelRouter for S2 proposals."""

    def __init__(
        self,
        model_manager: Any,
        config: Any,
        *,
        outbox: Any = None,
        token_counter: Callable[[str], int] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._model_manager = model_manager
        self._config = config
        self._outbox = outbox
        self._token_counter = token_counter or (lambda text: estimate_tokens(text))
        self._now = now or (lambda: datetime.now(UTC))
        self._queues: dict[str, _SessionQueue] = {}
        self._inflight: dict[str, _BatchState] = {}
        self._restored_sessions: set[str] = set()
        self._language_mismatch_count = 0
        self._item_rejected_counts: Counter[str] = Counter()

    @property
    def language_mismatch_count(self) -> int:
        """Number of retained observation rows still mismatched after one retry."""
        return self._language_mismatch_count

    @property
    def item_rejected_counts(self) -> dict[str, int]:
        """Cumulative item-level rejection counts grouped by stable reason."""
        return dict(self._item_rejected_counts)

    def pending_sessions(self) -> list[str]:
        """List durable sessions whose original captured source refs remain queued."""
        if self._outbox is None:
            return []
        return list(self._outbox.observer_pending_sessions())

    def mark_session_ended(self, session_id: str) -> None:
        """Persist a flush request synchronously before shutdown/switch draining."""
        session = str(session_id or "").strip()
        if not session:
            raise ValueError("observer session_id is required")
        queue = self._queues.setdefault(session, _SessionQueue())
        queue.flush_requested = True
        if self._outbox is not None:
            self._outbox.observer_mark_session_ended(session)

    async def resume(
        self,
        session_id: str,
        *,
        context: dict[str, Any] | None = None,
        session_ended: bool = False,
    ) -> PendingObservationBatch | None:
        """Restore a session without repeating a model result already awaiting HTTP ack."""
        if not capture_enabled(self._config):
            return None
        session = str(session_id)
        self._recover_unprocessed_sources(session)
        queue = self._restore_queue(session, context)
        pending = self._outbox.observer_pending_batch(session) if self._outbox is not None else None
        if pending is not None:
            state = self._inflight.get(str(pending["batch_id"]))
            if state is not None:
                return state.public
            public = PendingObservationBatch(
                batch_id=str(pending["batch_id"]), payload=pending["payload"],
                raw_output=str(pending["raw_output"]), model_id=str(pending["model_id"]),
                input_tokens=int(pending["input_tokens"]),
                output_tokens=int(pending["output_tokens"]),
            )
            queue_ids = tuple(str(value) for value in pending["queue_ids"])
            source_ids = tuple(str(value) for value in pending["source_event_ids"])
            queue.active_batch_id = public.batch_id
            self._inflight[public.batch_id] = _BatchState(
                public, session, queue_ids, source_ids, public.raw_output,
            )
            return public
        if session_ended:
            queue.flush_requested = True
            self._set_flush_requested(session, True)
        if self._queue_tokens(queue.entries) >= OBSERVATION_TRIGGER_TOKENS:
            queue.flush_requested = True
            self._set_flush_requested(session, True)
        if not queue.flush_requested:
            return None
        return await self._start_batch(session, queue, context)

    async def add_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        session_ended: bool = False,
        context: dict[str, Any] | None = None,
    ) -> PendingObservationBatch | None:
        """Queue ACKED capture sources, returning one ready batch without blocking chat.

        The integration owner runs this coroutine in the post-turn background task.
        Captures received while collection is paused are ignored; existing queued work
        remains intact. A session-end flag remains set until its complete queue drains.
        """
        if not capture_enabled(self._config):
            log.info("memory_observer.paused", session_id=session_id,
                     ignored_sources=len(messages))
            return None

        session = str(session_id)
        queue = self._restore_queue(session, context)
        if context is not None:
            queue.context = context

        seen = {str(item.get("source_event_id") or "") for item in queue.entries}
        new_entries: list[dict[str, Any]] = []
        for message in messages:
            source_id = str(message.get("source_event_id") or "").strip()
            if not source_id:
                log.warning("memory_observer.source_rejected", reason="missing_source_event_id",
                            session_id=session_id)
                continue
            if source_id in seen:
                continue
            normalized = dict(message)
            normalized["source_event_id"] = source_id
            content_text = ""
            if isinstance(message.get("content"), dict):
                content_text = str(message["content"].get("text") or "")
            normalized["text"] = str(message.get("text") or content_text or "")
            fragments = self._split_source(normalized)
            if not fragments:
                log.error("memory_observer.source_deferred", source_event_id=source_id,
                           reason="source_cannot_fit_batch_cap")
                continue
            new_entries.extend(fragments)
            seen.add(source_id)

        if new_entries and self._outbox is not None:
            refs = []
            for entry in new_entries:
                refs.append({
                    **{key: entry.get(key) for key in (
                        "source_event_id", "speaker_role", "epistemic_kind", "source_kind",
                        "source_object_id", "source_revision", "occurred_at",
                        "source_timezone", "provenance",
                    )},
                    "part_index": int(entry["_observer_part_index"]),
                    "part_count": int(entry["_observer_part_count"]),
                })
            persisted = self._outbox.observer_enqueue_sources(session, refs)
            ids = {(str(item["source_event_id"]), int(item["part_index"])):
                   str(item["queue_id"]) for item in persisted}
            live_entries = []
            for entry in new_entries:
                queue_id = ids.get((
                    str(entry["source_event_id"]), int(entry["_observer_part_index"]),
                ))
                if queue_id is None:
                    continue  # a duplicate capture already delivered by an earlier batch
                entry["_observer_queue_id"] = queue_id
                live_entries.append(entry)
            new_entries = live_entries
        queue.entries.extend(new_entries)

        if queue.active_batch_id or queue.processing:
            inflight = self._inflight.get(queue.active_batch_id)
            return inflight.public if inflight is not None else None

        if session_ended:
            queue.flush_requested = True
            self._set_flush_requested(session, True)
        pending_tokens = self._queue_tokens(queue.entries)
        if pending_tokens >= OBSERVATION_TRIGGER_TOKENS:
            queue.flush_requested = True
            self._set_flush_requested(session, True)
        if not queue.flush_requested:
            return None
        return await self._start_batch(session, queue, context)

    async def ack_batch(self, batch_id: str) -> PendingObservationBatch | None:
        """Release only a successful HTTP batch, then return the next eligible batch."""
        state = self._inflight.get(str(batch_id))
        if state is None:
            raise KeyError(f"unknown or already acknowledged observer batch {batch_id!r}")
        queue = self._queues[state.session_id]
        consumed = set(state.queue_ids)
        queue.entries = [entry for entry in queue.entries
                         if entry.get("_observer_queue_id") not in consumed]
        if self._outbox is not None:
            self._outbox.observer_ack_batch(state.public.batch_id)
        queue.active_batch_id = None
        del self._inflight[state.public.batch_id]
        if not queue.entries:
            queue.flush_requested = False
            self._queues.pop(state.session_id, None)
            return None
        if queue.flush_requested or self._queue_tokens(queue.entries) >= OBSERVATION_TRIGGER_TOKENS:
            queue.flush_requested = True
            return await self._start_batch(state.session_id, queue, queue.context)
        return None

    def _set_flush_requested(self, session_id: str, requested: bool) -> None:
        if self._outbox is not None:
            self._outbox.observer_set_flush_requested(session_id, requested)

    def _restore_queue(
        self, session_id: str, context: dict[str, Any] | None = None,
    ) -> _SessionQueue:
        queue = self._queues.setdefault(session_id, _SessionQueue())
        if context is not None:
            queue.context = context
        if self._outbox is None or session_id in self._restored_sessions:
            return queue
        self._restored_sessions.add(session_id)
        queue.flush_requested = self._outbox.observer_flush_requested(session_id)
        for row in self._outbox.observer_queue_sources(session_id):
            source = self._source_from_capture_row(row)
            fragments = self._split_source(source)
            part_index = int(row["part_index"])
            if len(fragments) != int(row["part_count"]) or not 1 <= part_index <= len(fragments):
                raise ValueError("durable Observer fragment layout no longer matches captured source")
            entry = fragments[part_index - 1]
            entry["_observer_queue_id"] = str(row["queue_id"])
            entry["_observer_part_index"] = part_index
            entry["_observer_part_count"] = int(row["part_count"])
            queue.entries.append(entry)
        pending = self._outbox.observer_pending_batch(session_id)
        if pending is not None:
            public = PendingObservationBatch(
                batch_id=str(pending["batch_id"]), payload=pending["payload"],
                raw_output=str(pending["raw_output"]), model_id=str(pending["model_id"]),
                input_tokens=int(pending["input_tokens"]),
                output_tokens=int(pending["output_tokens"]),
            )
            queue_ids = tuple(str(value) for value in pending["queue_ids"])
            source_ids = tuple(str(value) for value in pending["source_event_ids"])
            queue.active_batch_id = public.batch_id
            self._inflight[public.batch_id] = _BatchState(
                public, session_id, queue_ids, source_ids, public.raw_output,
            )
        return queue

    def _recover_unprocessed_sources(self, session_id: str) -> None:
        """Queue ACKED capture rows that were never handed to Observer before restart."""
        if self._outbox is None:
            return
        rows = self._outbox.observer_unprocessed_sources(session_id)
        refs: list[dict[str, Any]] = []
        for row in rows:
            source = self._source_from_capture_row(row)
            for fragment in self._split_source(source):
                refs.append({
                    **{key: source.get(key) for key in (
                        "source_event_id", "speaker_role", "epistemic_kind", "source_kind",
                        "source_object_id", "source_revision", "occurred_at",
                        "source_timezone", "provenance",
                    )},
                    "part_index": int(fragment["_observer_part_index"]),
                    "part_count": int(fragment["_observer_part_count"]),
                })
        if refs:
            self._outbox.observer_enqueue_sources(session_id, refs)

    @staticmethod
    def _source_from_capture_row(row: dict[str, Any]) -> dict[str, Any]:
        envelope = row.get("payload") or {}
        observation = envelope.get("observation") or {}
        content = observation.get("content") or {}
        if not isinstance(content, dict):
            raise ValueError("captured Observer source content is malformed")
        source = dict(row.get("source_view") or {})
        stored_context = envelope.get("context") or {}
        source.update({
            "source_event_id": str(row["source_event_id"]),
            "text": str(content.get("text") or ""),
            "source_kind": source.get("source_kind") or observation.get("source_kind"),
            "source_object_id": source.get("source_object_id") or observation.get("source_object_id"),
            "source_revision": source.get("source_revision") or observation.get("source_revision"),
            "speaker_role": source.get("speaker_role") or observation.get("speaker_role"),
            "epistemic_kind": source.get("epistemic_kind") or observation.get("epistemic_kind"),
            "occurred_at": source.get("occurred_at") or observation.get("occurred_at"),
            "source_timezone": source.get("source_timezone") or observation.get("source_timezone"),
            "provenance": source.get("provenance") or {
                "event_class": envelope.get("event_class"),
                "locator": observation.get("locator"),
                "external_content": bool(stored_context.get("external_content")),
                "tool_name": stored_context.get("tool_name"),
                "source_content_metadata": {key: value for key, value in content.items()
                                            if key != "text"},
            },
        })
        return source

    def _split_source(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        """Split oversized text losslessly so no model input batch exceeds its cap."""
        text = str(source.get("text") or "")
        if self._token_counter(text) <= MAX_TOKENS_PER_BATCH:
            return [self._queue_entry(source, text)]
        fragments: list[str] = []
        remaining = text
        while remaining:
            low, high, best = 1, len(remaining), 0
            while low <= high:
                mid = (low + high) // 2
                if self._token_counter(remaining[:mid]) <= MAX_TOKENS_PER_BATCH:
                    best = mid
                    low = mid + 1
                else:
                    high = mid - 1
            if best == 0:
                return []
            fragments.append(remaining[:best])
            remaining = remaining[best:]
        count = len(fragments)
        return [self._queue_entry(source, part, index, count)
                for index, part in enumerate(fragments, start=1)]

    @staticmethod
    def _queue_entry(source: dict[str, Any], text: str,
                     part_index: int = 1, part_count: int = 1) -> dict[str, Any]:
        entry = dict(source)
        entry["text"] = text
        entry["_observer_queue_id"] = uuid.uuid4().hex
        entry["_observer_part_index"] = part_index
        entry["_observer_part_count"] = part_count
        return entry

    def _queue_tokens(self, entries: list[dict[str, Any]]) -> int:
        return sum(max(0, int(self._token_counter(str(item.get("text") or ""))))
                   for item in entries)

    async def _start_batch(
        self,
        session_id: str,
        queue: _SessionQueue,
        context: dict[str, Any] | None,
    ) -> PendingObservationBatch | None:
        if queue.active_batch_id or queue.processing:
            active = self._inflight.get(queue.active_batch_id)
            return active.public if active else None
        entries: list[dict[str, Any]] = []
        token_count = 0
        for entry in queue.entries:
            cost = max(0, int(self._token_counter(str(entry.get("text") or ""))))
            if entries and token_count + cost > MAX_TOKENS_PER_BATCH:
                break
            if cost > MAX_TOKENS_PER_BATCH:
                log.error("memory_observer.source_deferred",
                          source_event_id=entry.get("source_event_id"),
                          reason="source_fragment_exceeds_batch_cap", estimated_tokens=cost)
                return None
            entries.append(entry)
            token_count += cost
        if not entries:
            return None

        source_ids = tuple(dict.fromkeys(
            str(entry["source_event_id"]) for entry in entries
        ))
        prompt = self._format_sources(entries)
        model_id = self._select_model_id()
        model_messages = [{"role": "user", "content": prompt}]
        request_tokens = max(1, estimate_tokens(
            model_messages, model=model_id, system_prompt=_SYSTEM_PROMPT,
        ))
        budget = self._daily_budget()
        day_key = self._now().date().isoformat()
        if self._outbox is not None:
            usage = self._outbox.observer_budget_snapshot(day_key)
            spent, reserved = usage["spent"], usage["reserved"]
            available = budget - spent - reserved - request_tokens
        else:
            with _DAILY_LOCK:
                spent = _DAILY_SPENT.get(day_key, 0)
                reserved = _DAILY_RESERVED.get(day_key, 0)
                available = budget - spent - reserved - request_tokens
        if available <= 0:
            log.info("memory_observer.budget_deferred", session_id=session_id,
                     source_event_ids=list(source_ids), day=day_key, budget=budget,
                     spent=spent, reserved=reserved, estimated_input_tokens=request_tokens)
            return None
        max_output = min(MAX_OUTPUT_TOKENS, available)
        reservation = request_tokens + max_output
        reservation_id = f"observer:{session_id}:{uuid.uuid4().hex}"
        if self._outbox is not None:
            if not self._outbox.observer_budget_reserve(
                day_key, budget, reservation_id, reservation,
            ):
                usage = self._outbox.observer_budget_snapshot(day_key)
                log.info("memory_observer.budget_deferred", session_id=session_id,
                         source_event_ids=list(source_ids), day=day_key, budget=budget,
                         spent=usage["spent"], reserved=usage["reserved"],
                         estimated_input_tokens=request_tokens)
                return None
        else:
            with _DAILY_LOCK:
                _DAILY_RESERVED[day_key] = _DAILY_RESERVED.get(day_key, 0) + reservation

        queue_ids = tuple(str(entry["_observer_queue_id"]) for entry in entries)
        # Set before the first await: simultaneous calls for this session observe the
        # in-flight state and cannot launch a duplicate model extraction.
        queue.processing = True
        try:
            result = await self._complete_with_retry(
                model_id, model_messages, max_tokens=max_output,
            )
            output_text = str(getattr(result, "text", "") or "")
            usage = getattr(result, "usage", None)
            input_tokens, output_tokens = self._reported_usage(usage)
            if input_tokens is None:
                input_tokens = request_tokens
            if output_tokens is None:
                output_tokens = max(0, int(estimate_tokens(output_text)))
            actual_tokens = input_tokens + output_tokens
            total_input_tokens = input_tokens
            total_output_tokens = output_tokens
            if self._outbox is not None:
                self._outbox.observer_budget_commit(reservation_id, actual_tokens)
            else:
                with _DAILY_LOCK:
                    _DAILY_RESERVED[day_key] = max(
                        0, _DAILY_RESERVED.get(day_key, 0) - reservation,
                    )
                    _DAILY_SPENT[day_key] = _DAILY_SPENT.get(day_key, 0) + actual_tokens
            reservation = 0
            try:
                parsed, item_rejected = _parse_observer_output(
                    output_text, set(source_ids),
                )
                item_rejected = Counter(item_rejected)
            except (json.JSONDecodeError, ValidationError) as exc:
                log.warning("memory_observer.output_rejected", model_id=model_id,
                            source_event_ids=list(source_ids), reason=str(exc)[:400],
                            raw_output=output_text, input_tokens=input_tokens,
                            output_tokens=output_tokens)
                raise ValueError("memory_observe output failed the S2 JSON schema") from exc

            language_status = "ok"
            mismatches = _language_mismatch_indices(parsed["observations"], entries)
            if mismatches:
                initial_mismatch_count = len(mismatches)
                retry_messages = [
                    *model_messages,
                    {
                        "role": "user",
                        "content": (
                            "Retry this extraction once. For each observation, use the language "
                            "of the raw source text identified by that observation's evidence: "
                            "Chinese source text gets Chinese text/value, and English source text "
                            "gets English text/value. Do not force a batch-wide language when its "
                            "cited source texts differ. Keep any "
                            "key as an English dot-separated slug. Return the same JSON schema and "
                            "cite only the source_event_id values already provided. Do not add facts."
                        ),
                    },
                ]
                retry_request_tokens = max(1, estimate_tokens(
                    retry_messages, model=model_id, system_prompt=_SYSTEM_PROMPT,
                ))
                retry_budget = self._reserve_language_retry(
                    session_id, day_key, budget, retry_request_tokens,
                )
                if retry_budget is None:
                    language_status = "language_mismatch"
                else:
                    retry_reservation_id, retry_max_output, retry_reservation = retry_budget
                    try:
                        retry_result = await self._complete_with_retry(
                            model_id, retry_messages, max_tokens=retry_max_output,
                        )
                        retry_output_text = str(getattr(retry_result, "text", "") or "")
                        retry_input_tokens, retry_output_tokens = self._reported_usage(
                            getattr(retry_result, "usage", None),
                        )
                        if retry_input_tokens is None:
                            retry_input_tokens = retry_request_tokens
                        if retry_output_tokens is None:
                            retry_output_tokens = max(0, int(estimate_tokens(retry_output_text)))
                        retry_actual_tokens = retry_input_tokens + retry_output_tokens
                        self._commit_language_retry(
                            day_key, retry_reservation_id, retry_reservation,
                            retry_actual_tokens,
                        )
                        retry_reservation = 0
                        total_input_tokens += retry_input_tokens
                        total_output_tokens += retry_output_tokens
                        actual_tokens += retry_actual_tokens
                        try:
                            retry_parsed, retry_rejected = _parse_observer_output(
                                retry_output_text, set(source_ids),
                            )
                        except (json.JSONDecodeError, ValidationError) as exc:
                            log.warning(
                                "memory_observer.language_retry_output_rejected",
                                model_id=model_id, source_event_ids=list(source_ids),
                                reason=str(exc)[:400], raw_output=retry_output_text,
                            )
                            language_status = "language_mismatch"
                        else:
                            output_text = retry_output_text
                            parsed = retry_parsed
                            item_rejected.update(retry_rejected)
                            mismatches = _language_mismatch_indices(
                                parsed["observations"], entries,
                            )
                            if mismatches:
                                language_status = "language_mismatch"
                            else:
                                language_status = "retry_recovered"
                                log.info(
                                    "memory_observer.language_retry_recovered",
                                    model_id=model_id, source_event_ids=list(source_ids),
                                    initial_mismatch_count=initial_mismatch_count,
                                    input_tokens=total_input_tokens,
                                    output_tokens=total_output_tokens,
                                )
                    except Exception as exc:
                        language_status = "language_mismatch"
                        log.warning(
                            "memory_observer.language_retry_failed",
                            model_id=model_id, source_event_ids=list(source_ids),
                            error_type=type(exc).__name__,
                        )
                    finally:
                        if retry_reservation:
                            self._release_language_retry(
                                day_key, retry_reservation_id, retry_reservation,
                            )

                if language_status == "language_mismatch":
                    self._language_mismatch_count += len(mismatches)
                    log.warning(
                        "memory_observer.language_mismatch",
                        status=language_status, model_id=model_id,
                        source_event_ids=list(source_ids),
                        language_mismatch_count=len(mismatches),
                        total_language_mismatch_count=self._language_mismatch_count,
                        retry_attempted=retry_budget is not None,
                        raw_output=output_text,
                    )

            payload = self._build_payload(
                parsed["observations"], entries, source_ids, session_id, output_text, context,
            )
            self._item_rejected_counts.update(item_rejected)
            batch_id = self._batch_id(session_id, source_ids, queue_ids, output_text)
            public = PendingObservationBatch(
                batch_id=batch_id, payload=payload, raw_output=output_text,
                model_id=model_id, input_tokens=total_input_tokens,
                output_tokens=total_output_tokens, language_status=language_status,
                language_mismatch_count=(
                    len(mismatches) if language_status == "language_mismatch" else 0
                ),
            )
            if self._outbox is not None:
                self._outbox.observer_store_batch(
                    batch_id=batch_id, session_id=session_id,
                    source_event_ids=list(source_ids),
                    queue_ids=list(queue_ids), payload=payload, raw_output=output_text,
                    model_id=model_id, input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )
            queue.active_batch_id = batch_id
            self._inflight[batch_id] = _BatchState(
                public, session_id, queue_ids, source_ids, output_text,
            )

            accepted = len(payload["observations"]) if payload else 0
            for reason, count in item_rejected.items():
                log.warning(
                    "memory_observer.item_rejected", reason=reason, count=count,
                    model_id=model_id, source_event_ids=list(source_ids),
                )
            log.info("memory_observer.completed", model_id=model_id, purpose="memory_observe",
                     input_tokens=total_input_tokens, output_tokens=total_output_tokens,
                     total_tokens=actual_tokens, source_event_ids=list(source_ids),
                     accepted_observations=accepted, raw_output=output_text,
                     item_rejected=dict(item_rejected),
                     batch_id=batch_id, language_status=language_status,
                     language_mismatch_count=public.language_mismatch_count)
            return public
        except BaseException:
            if reservation:
                if self._outbox is not None:
                    self._outbox.observer_budget_release(reservation_id)
                else:
                    with _DAILY_LOCK:
                        _DAILY_RESERVED[day_key] = max(
                            0, _DAILY_RESERVED.get(day_key, 0) - reservation,
                        )
            raise
        finally:
            queue.processing = False

    async def _complete_with_retry(
        self, model_id: str, messages: list[dict[str, Any]], *, max_tokens: int,
    ) -> Any:
        router = getattr(self._model_manager, "model_router", None)
        if router is None:
            raise RuntimeError("ModelRouter is unavailable for memory observation")
        delay = INITIAL_RETRY_DELAY_SECONDS
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await router.complete_for(
                    model_id, "memory_observe",
                    [{"role": "system", "content": _SYSTEM_PROMPT}, *messages],
                    max_tokens=max_tokens, temperature=0.1,
                )
            except Exception as exc:
                if attempt >= MAX_RETRIES or not self._retryable(exc):
                    log.error("memory_observer.model_call_failed", model_id=model_id,
                              purpose="memory_observe", attempt=attempt + 1,
                              provider_error_code=self._error_code(exc),
                              error_type=type(exc).__name__)
                    raise
                wait = min(MAX_RETRY_DELAY_SECONDS, delay) * random.uniform(0.8, 1.2)
                log.warning("memory_observer.model_call_retry", model_id=model_id,
                            attempt=attempt + 1, wait_seconds=round(wait, 3),
                            provider_error_code=self._error_code(exc))
                await asyncio.sleep(wait)
                delay = min(MAX_RETRY_DELAY_SECONDS, delay * 2)
        raise AssertionError("unreachable retry loop")

    def _reserve_language_retry(
        self, session_id: str, day_key: str, budget: int, request_tokens: int,
    ) -> tuple[str, int, int] | None:
        reservation_id = f"observer:{session_id}:language-retry:{uuid.uuid4().hex}"
        if self._outbox is not None:
            usage = self._outbox.observer_budget_snapshot(day_key)
            available = budget - usage["spent"] - usage["reserved"] - request_tokens
            retry_max_tokens = min(MAX_OUTPUT_TOKENS, available)
            if retry_max_tokens <= 0:
                return None
            reservation_tokens = request_tokens + retry_max_tokens
            if not self._outbox.observer_budget_reserve(
                day_key, budget, reservation_id, reservation_tokens,
            ):
                return None
            return reservation_id, retry_max_tokens, reservation_tokens

        with _DAILY_LOCK:
            available = (
                budget - _DAILY_SPENT.get(day_key, 0) - _DAILY_RESERVED.get(day_key, 0)
                - request_tokens
            )
            retry_max_tokens = min(MAX_OUTPUT_TOKENS, available)
            if retry_max_tokens <= 0:
                return None
            reservation_tokens = request_tokens + retry_max_tokens
            _DAILY_RESERVED[day_key] = _DAILY_RESERVED.get(day_key, 0) + reservation_tokens
        return reservation_id, retry_max_tokens, reservation_tokens

    def _commit_language_retry(
        self, day_key: str, reservation_id: str, reservation_tokens: int,
        actual_tokens: int,
    ) -> None:
        if self._outbox is not None:
            self._outbox.observer_budget_commit(reservation_id, actual_tokens)
            return
        with _DAILY_LOCK:
            _DAILY_RESERVED[day_key] = max(
                0, _DAILY_RESERVED.get(day_key, 0) - reservation_tokens,
            )
            _DAILY_SPENT[day_key] = _DAILY_SPENT.get(day_key, 0) + actual_tokens

    def _release_language_retry(
        self, day_key: str, reservation_id: str, reservation_tokens: int,
    ) -> None:
        if self._outbox is not None:
            self._outbox.observer_budget_release(reservation_id)
            return
        with _DAILY_LOCK:
            _DAILY_RESERVED[day_key] = max(
                0, _DAILY_RESERVED.get(day_key, 0) - reservation_tokens,
            )

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        status = status or getattr(response, "status_code", None)
        if status is not None:
            try:
                code = int(status)
            except (TypeError, ValueError):
                return False
            return code in {408, 425, 429} or code >= 500
        try:
            import httpx
            if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
                return True
        except ImportError:  # pragma: no cover
            pass
        return isinstance(exc, (TimeoutError, ConnectionError, OSError))

    @staticmethod
    def _error_code(exc: Exception) -> str | int | None:
        response = getattr(exc, "response", None)
        return (getattr(exc, "status_code", None)
                or getattr(response, "status_code", None)
                or getattr(exc, "code", None))

    def _select_model_id(self) -> str:
        if self._model_manager is None:
            raise RuntimeError("ModelManager is unavailable for memory observation")
        from atlas.config import load_user_settings

        try:
            settings = load_user_settings() or {}
        except Exception:
            settings = {}
        models = self._model_manager.list_models()
        for candidate in (
            settings.get("memory_model"),
            settings.get("compression_model"),
            getattr(self._model_manager, "current_model", None),
        ):
            chosen = str(candidate or "").strip()
            if not chosen:
                continue
            match = next((model for model in models
                          if chosen in {str(model.get("id") or ""),
                                        str(model.get("litellm_model") or "")}), None)
            if match is not None:
                return str(match.get("id") or match.get("litellm_model"))
            if candidate == getattr(self._model_manager, "current_model", None):
                return chosen
        raise RuntimeError("no configured memory/compression/current model is available")

    def _daily_budget(self) -> int:
        try:
            return max(0, int(self._config.get(
                "memory.v1.observer_daily_token_budget", 50_000,
            )))
        except (AttributeError, TypeError, ValueError):
            return 50_000

    def _build_payload(
        self,
        observations: list[dict[str, Any]],
        batch_entries: list[dict[str, Any]],
        source_ids: tuple[str, ...],
        session_id: str,
        output_text: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        sources = {str(entry["source_event_id"]): entry for entry in batch_entries}
        derived: list[dict[str, Any]] = []
        for index, candidate in enumerate(observations):
            evidence = candidate["evidence"]
            if not evidence or any(source_id not in sources for source_id in evidence):
                log.warning("memory_observer.observation_rejected", reason="evidence_not_in_batch",
                            session_id=session_id, evidence=evidence,
                            batch_source_event_ids=list(source_ids))
                continue
            speaker = self._trusted_speaker(candidate["speaker"],
                                             [sources[source_id] for source_id in evidence])
            epistemic = {
                "USER": "USER_ASSERTED",
                "TOOL": "OBSERVED",
                "THIRD_PARTY": "THIRD_PARTY_ASSERTED",
                "ATLAS": "INFERRED",
            }[speaker]
            content = {
                "text": candidate["text"],
                "priority": candidate["priority"],
                "facet": candidate["facet"],
                "key": candidate["key"],
                "value": candidate["value"],
                "entities": candidate["entities"],
                "valid_from": candidate["valid_from"],
                "valid_to": candidate["valid_to"],
                "change": candidate["is_change"],
            }
            occurred_at, source_timezone = self._effective_source_time(
                [sources[source_id] for source_id in evidence],
            )
            derived.append(build_observation(
                source_kind="DERIVED",
                source_object_id=self._derived_object_id(
                    session_id, evidence, content, index, output_text,
                ),
                source_revision="1",
                content=content,
                speaker_role=speaker,
                epistemic_kind=epistemic,
                occurred_at=occurred_at,
                source_timezone=source_timezone,
                derived_from=list(evidence),
            ))
        if not derived:
            return None
        event_class = str(
            os.environ.get("ATLAS_UNIFIED_EVENT_CLASS", "").strip()
            or self._config.get("memory.unified.event_class", "PRODUCTION")
            or "PRODUCTION"
        )
        return {
            "contract_version": "UM-WIN-1.0",
            "event_class": event_class,
            "context": context or {},
            "observations": derived,
        }

    @staticmethod
    def _trusted_speaker(model_speaker: str, evidence_sources: list[dict[str, Any]]) -> str:
        """Allow model attribution to downgrade authority, never to invent authority."""
        source_speakers: list[str] = []
        for source in evidence_sources:
            role = str(source.get("speaker_role") or "UNKNOWN").upper()
            epistemic = str(source.get("epistemic_kind") or "").upper()
            provenance = source.get("provenance") or {}
            external = bool(
                provenance.get("external_content")
                or provenance.get("is_external_content")
                or epistemic == "THIRD_PARTY_ASSERTED"
                or role == "THIRD_PARTY"
                or source.get("source_kind") == "USER_IMPORT"
            )
            if external:
                source_speakers.append("THIRD_PARTY")
            elif role == "TOOL":
                source_speakers.append("TOOL")
            elif role == "USER" and epistemic == "USER_ASSERTED":
                source_speakers.append("USER")
            else:
                source_speakers.append("ATLAS")

        model_speaker = str(model_speaker).upper()
        if model_speaker == "THIRD_PARTY" or "THIRD_PARTY" in source_speakers:
            return "THIRD_PARTY"
        if model_speaker == "USER" and source_speakers and all(
            speaker == "USER" for speaker in source_speakers
        ):
            return "USER"
        if model_speaker == "TOOL" and "TOOL" in source_speakers:
            return "TOOL"
        if "TOOL" in source_speakers:
            return "TOOL"
        return "ATLAS"

    @staticmethod
    def _effective_source_time(evidence_sources: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        """Use the latest supported source time; never date an old fact at extraction time."""
        known = [
            (instant, source) for source in evidence_sources
            if (instant := MemoryObserver._source_datetime(source)) is not None
        ]
        if not known:
            return None, None
        _, source = max(known, key=lambda pair: pair[0])
        occurred_at = source.get("occurred_at")
        source_timezone = str(source.get("source_timezone") or "").strip()
        if not source_timezone:
            parsed = MemoryObserver._source_datetime(source)
            if parsed is None or parsed.utcoffset() is None:
                return None, None
            source_timezone = str(parsed.strftime("%z") or "UTC")
        if isinstance(occurred_at, datetime):
            return occurred_at.isoformat(), source_timezone
        return str(occurred_at), source_timezone

    @staticmethod
    def _batch_id(session_id: str, source_ids: tuple[str, ...], queue_ids: tuple[str, ...],
                  output_text: str) -> str:
        material = json.dumps(
            [session_id, source_ids, queue_ids, output_text],
            ensure_ascii=False, separators=(",", ":"),
        )
        return "observer-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _derived_object_id(
        session_id: str,
        evidence: list[str],
        content: dict[str, Any],
        index: int,
        output_text: str,
    ) -> str:
        material = json.dumps(
            [session_id, evidence, content, index, output_text],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return "observer-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def _format_sources(self, entries: list[dict[str, Any]]) -> str:
        records: list[tuple[datetime | None, dict[str, Any]]] = [
            (self._source_datetime(item), item) for item in entries
        ]
        records.sort(key=lambda pair: pair[0] or datetime.min.replace(tzinfo=UTC))
        lines = ["Captured messages (each source_event_id is an authoritative evidence ID):"]
        previous: datetime | None = None
        current_day: str | None = None
        for instant, source in records:
            local_time = self._localized_datetime(instant, source.get("source_timezone"))
            day_label = local_time.strftime("%Y-%m-%d") if local_time else "unknown date"
            if day_label != current_day:
                lines.append(f"\nDate: {day_label}")
                current_day = day_label
            if previous is not None and instant is not None:
                gap = self._format_temporal_gap((instant - previous).total_seconds() * 1000)
                if gap:
                    stamp = local_time.strftime("%Y-%m-%d %H:%M %Z") if local_time else ""
                    lines.append(f"[temporal-gap: {gap} — {stamp}]")
            time_label = local_time.strftime("%H:%M") if local_time else "unknown time"
            source_view = {
                "source_event_id": source["source_event_id"],
                "speaker_role": source.get("speaker_role", "UNKNOWN"),
                "epistemic_kind": source.get("epistemic_kind", "INFERRED"),
                "source_kind": source.get("source_kind"),
                "source_object_id": source.get("source_object_id"),
                "source_revision": source.get("source_revision"),
                "occurred_at": source.get("occurred_at"),
                "source_timezone": source.get("source_timezone"),
                "provenance": source.get("provenance") or {},
                "text": source.get("text", ""),
            }
            lines.append(f"* ({time_label}) {json.dumps(source_view, ensure_ascii=False)}")
            if instant is not None:
                previous = instant
        return "\n".join(lines)

    @staticmethod
    def _source_datetime(source: dict[str, Any]) -> datetime | None:
        value = source.get("occurred_at")
        if not value:
            return None
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _localized_datetime(instant: datetime | None, zone_name: Any) -> datetime | None:
        if instant is None:
            return None
        try:
            return instant.astimezone(ZoneInfo(str(zone_name))) if zone_name else instant
        except (KeyError, ValueError):
            return instant

    @staticmethod
    def _format_temporal_gap(diff_ms: float) -> str | None:
        """Mastra date-utils.ts formatTemporalGap semantics (10-minute minimum)."""
        if diff_ms < 10 * 60 * 1000:
            return None
        minute = 60 * 1000
        hour = 60 * minute
        day = 24 * hour
        week = 7 * day
        month = 30 * day
        year = 365 * day

        def unit(value: int, name: str) -> str:
            return f"{value} {name}{'' if value == 1 else 's'}"

        if diff_ms < hour:
            return f"{unit(max(1, round(diff_ms / minute)), 'minute')} later"

        def two_units(primary_ms: int, primary_name: str,
                      secondary_ms: int, secondary_name: str) -> str:
            primary = int(diff_ms // primary_ms)
            remainder = diff_ms - primary * primary_ms
            secondary = int(remainder // secondary_ms)
            parts = [unit(primary, primary_name)]
            if secondary > 0:
                parts.append(unit(secondary, secondary_name))
            return " ".join(parts) + " later"

        if diff_ms < day:
            return two_units(hour, "hour", minute, "minute")
        if diff_ms < week:
            return two_units(day, "day", hour, "hour")
        if diff_ms < month:
            return two_units(week, "week", day, "day")
        if diff_ms < year:
            return two_units(month, "month", week, "week")
        return two_units(year, "year", month, "month")

    @staticmethod
    def _reported_usage(usage: Any) -> tuple[int | None, int | None]:
        def read(*keys: str) -> int | None:
            for key in keys:
                value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
                if isinstance(value, (int, float)) and value >= 0:
                    return int(value)
            return None

        return read("input_tokens", "prompt_tokens"), read("output_tokens", "completion_tokens")
