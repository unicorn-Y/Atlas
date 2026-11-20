# ported from hermes-agent@c9e076b atlas_state_portability.py (MIT)
"""Session listing/rich rows, export, and import (portability) for SessionDB.

Plain mixin for ``atlas_state.SessionDB`` (no ``__init__``/state of its own).
Must never import atlas_state (cycle); shared constants live in atlas_state_common.
"""

import logging
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone, UTC
from typing import Any, Dict, List, Optional

from atlas.engine.agent.skill_commands import AUTO_LOAD_SCAFFOLD_SQL_LIKE, SKILL_SCAFFOLD_SQL_LIKE
from atlas.engine.utils import safe_json_loads
from atlas.engine.state.timefmt import coerce_epoch
from atlas.engine.state.atlas_state_ids import new_session_id
from atlas.engine.state.atlas_state_common import SCHEMA_SQL, _shape_preview, _sql_preview_raw, _sql_session_last_active
from atlas.engine.state.atlas_state_messages import _parse_tool_calls, _tool_calls_count
import itertools

# Pre-split logger identity so log filtering/capture is unchanged.
logger = logging.getLogger("atlas_state")

_IMPORT_SESSION_TEXT_FIELDS = (
    "source", "user_id", "model", "system_prompt", "end_reason", "cwd", "git_branch", "git_repo_root",
    "billing_provider", "billing_base_url", "billing_mode", "cost_status", "cost_source", "pricing_version", "title",
)
# ``role`` is validated separately (non-empty string).
_IMPORT_MESSAGE_TEXT_FIELDS = (
    "tool_call_id", "tool_name", "effect_disposition", "finish_reason",
    "reasoning", "reasoning_content", "platform_message_id", "message_id",
)


def _append_session_event_row(
    conn, session_id: str, event_type: str, payload: dict[str, Any],
) -> int:
    session_id = str(session_id or "").strip()
    event_type = str(event_type or "").strip()
    if not session_id:
        raise ValueError("session_id must not be empty")
    if not event_type:
        raise ValueError("event_type must not be empty")
    if not isinstance(payload, dict):
        raise ValueError("session event payload must be an object")
    cursor = conn.execute(
        "INSERT INTO session_events(session_id, event_type, payload_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, event_type,
         json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
         datetime.now(timezone.utc).isoformat()),
    )
    sequence = int(cursor.lastrowid)
    from atlas.session_telemetry import mirror_session_event

    mirror_session_event(conn, sequence)
    return sequence
_IMPORT_MESSAGE_JSON_FIELDS = (
    "reasoning_details", "codex_reasoning_items", "codex_message_items", "absorbed_message_uids", "tool_call_uids",
)
_IMPORT_SESSION_INSERT_SQL = """INSERT INTO sessions (
                           id, source, user_id, model, model_config, system_prompt,
                           system_prompt_hash,
                           parent_session_id, started_at, ended_at, end_reason,
                           message_count, tool_call_count, input_tokens, output_tokens,
                           cache_read_tokens, cache_write_tokens, reasoning_tokens,
                           cwd, git_branch, git_repo_root,
                           billing_provider, billing_base_url, billing_mode,
                           estimated_cost_usd, actual_cost_usd, cost_status, cost_source,
                           pricing_version, title, api_call_count, archived, auto_archived, pinned, hidden
                       )
                       VALUES (
                           :id, :source, :user_id, :model, :model_config,
                           NULL, :system_prompt_hash, NULL, :started_at, :ended_at,
                           :end_reason, 0, 0, :input_tokens, :output_tokens,
                           :cache_read_tokens, :cache_write_tokens,
                           :reasoning_tokens, :cwd, :git_branch, :git_repo_root,
                           :billing_provider, :billing_base_url, :billing_mode,
                           :estimated_cost_usd, :actual_cost_usd, :cost_status,
                           :cost_source, :pricing_version, :title,
                           :api_call_count, :archived, :auto_archived, :pinned, :hidden
                       )"""
# Columns copied verbatim from the payload; typed columns are converted below.
_IMPORT_PASSTHROUGH_COLS = (
    "user_id", "model", "model_config", "end_reason", "cwd", "git_branch", "git_repo_root", "billing_provider",
    "billing_base_url", "billing_mode", "cost_status", "cost_source", "pricing_version", "title",
)
_IMPORT_INT_COLS = (
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "api_call_count",
)
_IMPORT_FLOAT_COLS = ("ended_at", "estimated_cost_usd", "actual_cost_usd")
# Flags a restore must keep: pinned/hidden/auto_archived drive the prune, listings and resume-unarchive.
_IMPORT_FLAG_COLS = ("archived", "auto_archived", "pinned", "hidden")


def _rich_select(select_cols: str, where: str, tail: str = "", prompt_select: Optional[str] = "") -> str:
    """``list_sessions_rich``-shaped SELECT: resolved prompt (``prompt_select`` fragment;
    None omits prompt columns AND the join), preview, last_active. Whitespace matches
    the historical inline queries (SQL text is pinned)."""
    prompt_join = "" if prompt_select is None else "LEFT JOIN system_prompts sp ON sp.hash = s.system_prompt_hash"
    return f"""
            SELECT {select_cols}{prompt_select or ""},
                {_sql_preview_raw()},
                {_sql_session_last_active("s")} AS last_active
            FROM sessions s
            {prompt_join}
            WHERE {where}{tail}
        """


_PROMPT_RESOLVED_SQL = "COALESCE(sp.prompt, s.system_prompt) AS _system_prompt_resolved"


def _export_timings(messages: list[dict[str, Any]], session_id: Optional[str] = None) -> dict[str, Any]:
    """Text-free timing evidence for a session export.

    Exports get attached to bug reports; a reader should not have to infer from raw
    timestamps whether a slow turn was one long model gap or many small tool
    intervals. Hermes persists no model/tool stopwatch samples, so message
    timestamps are the durable floor (``complete`` is therefore always False).
    Ids, roles, counts and durations only — never prompt text, arguments or results.
    Corrupt timestamp cells go through ``coerce_epoch`` like every other reader: they
    count as ``missing`` and never abort the export.
    """
    timestamped = [(msg, ts) for msg in messages
                   if (ts := coerce_epoch(msg.get("timestamp"), session_id=session_id)) is not None]
    role_counts = Counter(str(msg.get("role") or "unknown") for msg in messages)
    tool_calls_emitted = sum(
        len(tc) if isinstance(tc, list) else 1 for tc in (msg.get("tool_calls") for msg in messages) if tc)
    intervals = [{
        "from_message_id": prev.get("id"), "to_message_id": nxt.get("id"),
        "from_role": prev.get("role"), "to_role": nxt.get("role"),
        "gap_ms": max(0, round((nxt_ts - prev_ts) * 1000)),
    } for (prev, prev_ts), (nxt, nxt_ts) in itertools.pairwise(timestamped)]
    iso = lambda ts: datetime.fromtimestamp(ts, tz=UTC).isoformat()
    first_ts, last_ts = (timestamped[0][1], timestamped[-1][1]) if timestamped else (None, None)
    return {
        "source": "message_timestamps",
        "available": bool(timestamped),
        "complete": False,
        "unavailable_reason": None if timestamped else "no_timestamped_messages",
        "message_timestamps": {"available": len(timestamped), "missing": len(messages) - len(timestamped)},
        "first_message_at": iso(first_ts) if first_ts is not None else None,
        "last_message_at": iso(last_ts) if last_ts is not None else None,
        "wall_clock_ms": max(0, round((last_ts - first_ts) * 1000)) if timestamped else None,
        "largest_gap_ms": max(i["gap_ms"] for i in intervals) if intervals else None,
        "role_counts": dict(role_counts),
        "tool_result_count": role_counts.get("tool", 0),
        "tool_calls_emitted": tool_calls_emitted,
        "intervals": intervals,
    }


class SessionPortabilityMixin:
    """See module docstring — mixin for SessionDB (Port cluster)."""

    @staticmethod
    def _find_foreign_import_on_conn(conn, origin):
        rows = conn.execute("SELECT id, origin_json FROM sessions WHERE source = ? AND origin_json IS NOT NULL",
                            (origin["tool"],)).fetchall()
        for row in rows:
            imported = (safe_json_loads(row["origin_json"], default={}) or {}).get("imported_from", {})
            if imported.get("tool") != origin["tool"]:
                continue
            foreign_id = origin.get("foreign_session_id")
            if ((foreign_id and foreign_id == imported.get("foreign_session_id"))
                    or (not foreign_id and imported.get("path") == origin["path"])):
                return row["id"]
        return None

    def find_foreign_import(self, origin):
        with self._read_ctx() as conn:
            return self._find_foreign_import_on_conn(conn, origin)

    def import_foreign_history(self, origin, messages, *, title, cwd, profile):
        """Adopt or mint a foreign snapshot in one transaction, including its provenance.

        BEGIN IMMEDIATE serializes duplicate clicks across connections/processes.
        Reuse the portability validator and message writer so counters and FTS
        obey the same contract as ordinary transcript imports.
        """
        session_id = new_session_id(hex_len=12)
        normalized, errors = self._validate_import_payload([
            {"id": session_id, "source": origin["tool"], "title": title,
             "cwd": cwd, "messages": messages}])
        if errors:
            raise ValueError(errors[0]["error"])

        def _do(conn):
            existing = self._find_foreign_import_on_conn(conn, origin)
            if existing:
                return {"session_id": existing, "already_imported": True}
            # Titles are globally unique within a profile. Preserve a readable
            # title while giving unrelated conversations with the same text room.
            item = normalized[0]
            if conn.execute("SELECT 1 FROM sessions WHERE title = ?", (title,)).fetchone():
                item["session"]["title"] = f"{title} ({session_id[-12:]})"
            self._import_session_row(conn, item["session"], item["messages"], session_id)
            conn.execute("UPDATE sessions SET origin_json = ?, profile_name = ? WHERE id = ?",
                         (json.dumps({"imported_from": origin}), profile, session_id))
            return {"session_id": session_id, "already_imported": False}

        return self._execute_write(_do)

    @classmethod
    def _compact_session_cols(cls) -> str:
        """``s.``-prefixed SELECT list of every SCHEMA_SQL ``sessions`` column except
        prompt storage internals (the compact_rows projection)."""
        if cls._session_compact_cols_sql is None:
            declared = cls._parse_schema_columns(SCHEMA_SQL)["sessions"]
            cls._session_compact_cols_sql = ", ".join(
                f"s.{name}" for name in declared if name not in cls._SESSION_COMPACT_EXCLUDED
            )
        return cls._session_compact_cols_sql

    @classmethod
    def _rich_row(cls, row) -> dict[str, Any]:
        """Session row dict with ``_preview_raw`` shaped into ``preview``."""
        s = cls._session_row_dict(row)
        s["preview"] = _shape_preview(s.pop("_preview_raw", ""))
        return s

    def _read_rows(self, sql: str, params=()) -> list:
        """Pure-read query via ``_read_ctx()`` (never the writer lock: turn persistence must not convoy)."""
        with self._read_ctx() as conn:
            return conn.execute(sql, params).fetchall()

    def distinct_session_cwds(self, include_archived: bool = False) -> list[dict[str, Any]]:
        """Distinct non-empty session cwds with usage stats, for repo discovery. Aggregates
        across ALL history; children/branches count (a worktree session is a real
        workspace signal)."""
        where = "cwd IS NOT NULL AND TRIM(cwd) != ''"
        if not include_archived:
            where += " AND archived = 0"
        rows = self._read_rows(
            "SELECT cwd AS cwd, COUNT(*) AS sessions, MAX(COALESCE(ended_at, started_at, 0)) AS last_active "
            f"FROM sessions WHERE {where} GROUP BY cwd"
        )
        return [{"cwd": r["cwd"], "sessions": int(r["sessions"] or 0), "last_active": float(r["last_active"] or 0)}
                for r in rows]

    def list_cron_job_runs(self, job_id: str, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """Run sessions of one cron job, newest first, in the ``list_sessions_rich`` row shape.
        Cron runs are flat ``cron_{job_id}_{timestamp}`` sessions that never compress or
        branch, so this skips ``list_sessions_rich``'s compression-chain CTE /
        leading-wildcard ``id_query`` path (which seeds from EVERY ``source='cron'`` row)
        for a ``[prefix, prefix_hi)`` id range scan that scales with the window."""
        prefix = f"cron_{job_id}_"
        # Half-open upper bound: bump the final byte so the range covers exactly the prefix.
        prefix_hi = prefix[:-1] + chr(ord(prefix[-1]) + 1)
        query = _rich_select(
            "s.*", "s.source = 'cron' AND s.id >= ? AND s.id < ?",
            "\n            ORDER BY s.started_at DESC, s.id DESC\n            LIMIT ? OFFSET ?",
            prompt_select=f",\n                {_PROMPT_RESOLVED_SQL}",
        )
        return [self._rich_row(row) for row in self._read_rows(query, (prefix, prefix_hi, limit, offset))]

    def _get_session_rich_row(self, session_id: str, compact_rows: bool = False) -> Optional[dict[str, Any]]:
        """One session with the ``list_sessions_rich`` enriched columns, or None.
        ``compact_rows=True`` omits the ``system_prompt`` blob. Public alias:
        :meth:`get_session_rich_row` (web server hydration)."""
        return self._get_session_rich_rows_batch([session_id], compact_rows=compact_rows).get(session_id)

    get_session_rich_row = _get_session_rich_row

    def _get_session_rich_rows_batch(self, session_ids, compact_rows: bool = False) -> dict[str, dict[str, Any]]:
        """Enriched rows for many sessions in one query, keyed by id; missing ids are absent
        (a page of compression tips resolves in one round trip)."""
        ids = [sid for sid in session_ids if sid]
        if not ids:
            return {}
        # Old SQLite caps bound variables at 999 (SQLITE_MAX_VARIABLE_NUMBER); limit=10000
        # callers exist. Chunk here — the single choke point.
        _CHUNK = 900
        if len(ids) > _CHUNK:
            result: dict[str, dict[str, Any]] = {}
            for start in range(0, len(ids), _CHUNK):
                result.update(self._get_session_rich_rows_batch(ids[start:start + _CHUNK], compact_rows=compact_rows))
            return result
        # Same read-your-writes guarantee as list_sessions_rich.
        self.flush_token_counts()
        query = _rich_select(
            self._compact_session_cols() if compact_rows else "s.*", f"s.id IN ({','.join('?' for _ in ids)})",
            prompt_select=None if compact_rows else f", {_PROMPT_RESOLVED_SQL}",
        )
        return {s["id"]: s for s in map(self._rich_row, self._read_rows(query, ids))}

    def list_skill_scaffolded_sessions(self, limit: int = 200) -> list[dict[str, Any]]:
        """Titled sessions whose first user turn was a ``/skill`` invocation or a gateway
        auto-load scaffold (their titles describe the expanded skill body, not the
        request). Returns ``id``, ``title`` and the first-turn ``content`` so callers can
        re-derive what was typed. Newest first."""
        rows = self._read_rows("""
                SELECT s.id, s.title, m.content
                FROM sessions s
                JOIN messages m ON m.id = (
                    SELECT m2.id FROM messages m2
                    WHERE m2.session_id = s.id AND m2.role = 'user'
                      AND m2.content IS NOT NULL
                    ORDER BY m2.timestamp, m2.id LIMIT 1
                )
                WHERE s.title IS NOT NULL AND (m.content LIKE ? OR m.content LIKE ?)
                ORDER BY s.started_at DESC
                LIMIT ?
                """, (SKILL_SCAFFOLD_SQL_LIKE, AUTO_LOAD_SCAFFOLD_SQL_LIKE, int(limit)))
        return [dict(row) for row in rows]

    # ── Export ─────────────────────────────────────────────────────────────

    def _with_messages(self, session: dict[str, Any], include_compacted: bool = False,
                       include_inactive: bool = False) -> dict[str, Any]:
        messages = self.get_messages(session["id"], include_inactive=include_inactive, include_compacted=include_compacted)
        return {**session, "messages": messages, "timings": _export_timings(messages, session["id"])}

    def export_session(self, session_id: str, include_compacted: bool = False,
                       include_inactive: bool = False) -> Optional[dict[str, Any]]:
        """Export a single session with all its messages as a dict. ``include_compacted`` adds the turns
        in-place compaction archived (the history the user still sees); it stays off for payloads that go
        back through :meth:`import_sessions`, because that projection is deduped and ordered for display, and
        importing it would make those turns live context. ``include_inactive`` exports every row in storage
        order with its ``active``/``compacted`` flags, which :meth:`import_sessions` restores as archived."""
        session = self.get_session(session_id)
        return self._with_messages(session, include_compacted, include_inactive) if session else None

    def export_session_lineage(self, session_id: str, include_compacted: bool = False,
                               include_inactive: bool = False) -> Optional[dict[str, Any]]:
        """Export a compression lineage as one logical session dict (flags as in :meth:`export_session`)."""
        lineage_ids = self.get_compression_lineage(session_id)
        if not lineage_ids:
            return None
        segments = [seg for seg in (self.export_session(sid, include_compacted, include_inactive)
                                    for sid in lineage_ids) if seg]
        if not segments:
            return None
        messages = [msg for seg in segments for msg in (seg.get("messages") or [])]
        return {
            **segments[-1], "segments": segments,
            "lineage_session_ids": [seg["id"] for seg in segments], "message_count": len(messages),
            "messages": messages, "timings": _export_timings(messages, session_id),
        }

    def export_all(self, source: str | None = None, include_compacted: bool = False,
                   include_inactive: bool = False) -> list[dict[str, Any]]:
        """Export all sessions (with messages) as dicts, e.g. for JSONL backup (flags as in
        :meth:`export_session`; that display read dedupes per session, so it skips the batched read).
        Backups that go back through :meth:`import_sessions` pass ``include_inactive`` so
        compaction-archived turns survive the round trip as archived rows."""
        sessions = self.search_sessions(source=source, limit=100000)
        if include_compacted:
            return [self._with_messages(session, True, include_inactive) for session in sessions]
        messages_by_session = {session["id"]: [] for session in sessions}
        session_ids = list(messages_by_session)
        active_clause = self._active_clause(include_inactive, False)
        # Stay below SQLite's legacy 999-variable limit while replacing the per-session N+1 reads.
        for start in range(0, len(session_ids), 900):
            chunk = session_ids[start:start + 900]
            rows = self._read_all(
                f"SELECT * FROM messages WHERE session_id IN ({','.join('?' for _ in chunk)}) "
                f"{active_clause} ORDER BY session_id, id",
                chunk,
            )
            for row in rows:
                messages_by_session[row["session_id"]].append(
                    self._row_to_message_dict(row, warn_context="get_messages", summary_flag=True)
                )
        return [{**session, "messages": messages_by_session[session["id"]],
                 "timings": _export_timings(messages_by_session[session["id"]], session["id"])} for session in sessions]

    def adopt_session_lineage_from(self, donor_db: Any, session_id: str, *, retire_donor: bool = True) -> dict[str, Any]:
        """Adopt *session_id*'s full compression lineage from *donor_db* (stranded-bot-session
        heal: a profile bot's rows accumulated in the DEFAULT profile's state.db before the
        desktop routed session RPCs by target session). Pure composition
        ``donor_db.export_session_lineage()`` -> ``self.import_sessions()``: runtime
        fields reset, already-present ids skipped (idempotent). Every message row is carried
        with its archived state, so turns in-place compaction archived stay visible here and
        stay out of model context. With ``retire_donor`` and a complete adoption, donor rows
        are ARCHIVED (never deleted) with
        ``end_reason='adopted_by_profile'`` — deliberately NOT in the recoverable set, so
        resurrection cannot undo an adoption. Returns the ``import_sessions`` dict plus
        ``adopted`` and ``donor_retired`` (True only when EVERY segment retired).

        Once routing was fixed, the profile backend correctly received the RPCs but had no such session, so
        the same chat 4001'd for the opposite reason. This method moves the conversation to where routing
        now looks for it. See #93091, #93296.
        """
        # Every row, not just live ones: the retired donor is unrecoverable, so any turn left behind
        # (compaction-archived history included) would be visible nowhere.
        payload = donor_db.export_session_lineage(session_id, include_inactive=True)
        if not payload:
            return {"ok": False, "adopted": False, "donor_retired": False,
                    "error": f"session {session_id!r} not found in donor store"}
        segments = payload.get("segments") or [payload]

        # Divergence guard: a segment we will SKIP (already here) may have kept growing in
        # the donor after a partial adoption; retiring it would strand those messages
        # behind a non-recoverable archive. Still import, but refuse to retire.
        donor_ahead = False
        for seg in segments:
            seg_id = seg.get("id")
            if not seg_id or self.get_session(seg_id) is None:
                continue
            donor_count = len(seg.get("messages") or [])
            local_count = len(self.get_messages(seg_id, include_inactive=True))
            if donor_count > local_count:
                donor_ahead = True
                logger.warning("adoption divergence: donor segment %s has %d messages, "
                               "local copy has %d — donor will NOT be retired", seg_id, donor_count, local_count)

        result = self.import_sessions([dict(seg) for seg in segments])
        imported = int(result.get("imported") or 0)
        skipped = int(result.get("skipped") or 0)
        adopted = result.get("ok", False) and (imported + skipped) == len(segments)
        if not adopted:
            logger.warning("adoption of %s did not complete: imported=%s skipped=%s of %s segment(s); errors=%s",
                           session_id, imported, skipped, len(segments), result.get("errors"))

        donor_retired = False
        if adopted and retire_donor and not donor_ahead:
            donor_retired = all(self._retire_donor_segment(donor_db, seg["id"]) for seg in segments if seg.get("id"))
        return {**result, "adopted": adopted, "donor_retired": donor_retired}

    def _retire_donor_segment(self, donor_db: Any, seg_id: str) -> bool:
        """Archive one adopted donor segment; False when skipped or failed. TOCTOU close-out:
        the divergence guard used EXPORT-TIME counts; re-read both stores right before
        stamping so donor growth never lands behind a non-recoverable archive
        (equal-count CONTENT divergence is accepted — bytes stay in the donor either way).
        A retirement failure must not fail the adoption (a later resume retries
        idempotently), but never claims success it didn't have."""
        try:
            donor_now = len(donor_db.get_messages(seg_id, include_inactive=True))
            local_now = len(self.get_messages(seg_id, include_inactive=True))
            if donor_now > local_now:
                logger.warning(
                    "adoption divergence at retire time: donor segment %s grew to %d messages (local %d) — "
                    "leaving donor unretired", seg_id, donor_now, local_now,
                )
                return False
            # First end_reason wins in end_session(); reopen so the adoption boundary is
            # stamped even on ended segments.
            donor_db.reopen_session(seg_id)
            donor_db.end_session(seg_id, "adopted_by_profile")
            donor_db.set_session_archived(seg_id, True)
            return True
        except Exception:
            logger.warning("failed to retire donor segment %s after adoption", seg_id, exc_info=True)
            return False

    # ── Import ─────────────────────────────────────────────────────────────

    @staticmethod
    def _import_text_or_none(value: Any, field: str) -> Optional[str]:
        if value is None or isinstance(value, str):
            return value
        raise ValueError(f"{field} must be a string")

    @staticmethod
    def _import_int_or_none(value: Any, field: str) -> Optional[int]:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be an integer") from exc

    @staticmethod
    def _import_non_finite_path(value: Any, path: str) -> Optional[str]:
        """First ``path`` of a NaN/inf number anywhere in decoded JSON data, else None.

        Iterative walk (a recursive visitor would overflow on crafted nesting); cycles
        can't arrive through ``json.loads`` but guard anyway.
        """
        pending = [(value, path)]
        while pending:
            current, current_path = pending.pop()
            if isinstance(current, float) and not math.isfinite(current):
                return current_path
            if isinstance(current, dict):
                pending.extend((child, f"{current_path}.{key}") for key, child in current.items())
            elif isinstance(current, list):
                pending.extend((child, f"{current_path}[{key}]") for key, child in enumerate(current))
        return None

    @classmethod
    def _import_load_json(cls, value: str, path: str) -> Any:
        """``json.loads`` that refuses NaN/Infinity anywhere in the decoded value.

        A JSON exponent like ``1e309`` decodes to ``float("inf")``, which strict
        serializers reject and cost analytics mis-handle. Callers that intentionally
        decode a JSON-backed column (model_config, reasoning items) re-check through
        here so non-finite values can't reappear after the outer payload was inspected.
        """
        parsed = json.loads(value)  # NaN/Infinity are accepted syntax; catch them after decode
        non_finite = cls._import_non_finite_path(parsed, path)
        if non_finite is not None:
            raise ValueError(f"non-finite number at {non_finite}")
        return parsed

    @classmethod
    def _import_json_object_or_none(cls, value: Any, field: str) -> Optional[str]:
        if value is None:
            return None
        path = f"session.{field}"
        if isinstance(value, str):
            try:
                parsed = cls._import_load_json(value, path)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{field} must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"{field} must be a JSON object")
            return value
        if not isinstance(value, dict):
            raise ValueError(f"{field} must be a JSON object")
        if cls._import_non_finite_path(value, path) is not None:
            raise ValueError(f"non-finite number at {path}")
        try:
            return json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be JSON serializable") from exc

    @staticmethod
    def _coerce_or(value: Any, cast, default):
        """``cast(value)``; *default* for None or an unparsable value."""
        try:
            return default if value is None else cast(value)
        except (TypeError, ValueError):
            return default

    # SQLite binds Python ints only inside the signed 64-bit range; anything wider
    # raises OverflowError at INSERT time (an unhandled 500, not a 400).
    _SQLITE_INT_MIN = -(1 << 63)
    _SQLITE_INT_MAX = (1 << 63) - 1

    @classmethod
    def _import_int_or_bounded(cls, value: Any, field: str, default: int) -> int:
        """Import an int column: SQL-int-range or *default* (never fails the import)."""
        number = cls._coerce_or(value, int, default)
        if number is None:
            return default
        if isinstance(number, bool) or not (cls._SQLITE_INT_MIN <= number <= cls._SQLITE_INT_MAX):
            return default
        return number

    def _normalize_import_message(self, message: dict[str, Any], message_index: int) -> dict[str, Any]:
        """Type-check one payload message; raises ValueError naming the offending field."""
        clean_message = dict(message)
        role = clean_message.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"messages[{message_index}].role must be a non-empty string")
        for field in _IMPORT_MESSAGE_TEXT_FIELDS:
            clean_message[field] = self._import_text_or_none(clean_message.get(field), field)
        token_count = self._import_int_or_none(clean_message.get("token_count"), "token_count")
        if token_count is not None and not (self._SQLITE_INT_MIN <= token_count <= self._SQLITE_INT_MAX):
            raise ValueError("token_count is outside SQLite's integer range")
        clean_message["token_count"] = token_count
        message_path = f"session.messages[{message_index}]"
        timestamp = clean_message.get("timestamp")
        if timestamp is not None and coerce_epoch(timestamp, field="messages[].timestamp") is None:
            raise ValueError(f"{message_path}.timestamp must be a supported Unix timestamp")
        self._validate_import_message_content(clean_message.get("content"), message_path)
        for field in _IMPORT_MESSAGE_JSON_FIELDS:
            json_value = clean_message.get(field)
            if isinstance(json_value, str):
                # Malformed JSON text persists verbatim (readers fall back via _json_or);
                # only a PARSED non-finite number is rejected — it would break strict
                # JSON serializers once decoded back out of the row.
                try:
                    self._import_load_json(json_value, f"{message_path}.{field}")
                except json.JSONDecodeError:
                    pass
                except ValueError:
                    raise
            elif json_value is not None:
                non_finite = self._import_non_finite_path(json_value, f"{message_path}.{field}")
                if non_finite is not None:
                    raise ValueError(f"non-finite number at {non_finite}")
        return clean_message

    @classmethod
    def _validate_import_message_content(cls, content: Any, message_path: str) -> None:
        """Scalar message content must be bindable and later serializable."""
        if isinstance(content, int) and not isinstance(content, bool) and not (
                cls._SQLITE_INT_MIN <= content <= cls._SQLITE_INT_MAX):
            # SQLite can't bind a wider int: this reached INSERT and raised OverflowError.
            raise ValueError(f"{message_path}.content is outside SQLite's integer range")
        if isinstance(content, float) and not math.isfinite(content):
            raise ValueError(f"non-finite number at {message_path}.content")
        if isinstance(content, (bytes, bytearray)):
            raise ValueError(f"{message_path}.content must be a string, list, object, finite number, or null")

    @classmethod
    def _import_float_or_finite(cls, value: Any, field: str) -> Optional[float]:
        """Import a float column: finite float or None (never fails the import).

        A JSON exponent like ``1e309`` decodes to ``float("inf")``; persisted, it later
        breaks strict JSON serialization in the session APIs. Missing stays missing.
        """
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def _normalize_import_session(self, raw: dict[str, Any], session_id: str, messages: list) -> dict[str, Any]:
        """Type-check one payload session + its messages; raises ValueError."""
        clean_session = dict(raw)
        clean_session["id"] = session_id
        clean_session["model_config"] = self._import_json_object_or_none(clean_session.get("model_config"), "model_config")
        for field in ("parent_session_id", *_IMPORT_SESSION_TEXT_FIELDS):
            clean_session[field] = self._import_text_or_none(clean_session.get(field), field)
        started_at = clean_session.get("started_at")
        if started_at is not None and coerce_epoch(started_at, field="started_at") is None:
            raise ValueError("session.started_at must be a supported Unix timestamp")
        for field in _IMPORT_FLOAT_COLS:
            value = clean_session.get(field)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"non-finite number at session.{field}")
        for field in _IMPORT_INT_COLS:
            value = clean_session.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and not (
                    self._SQLITE_INT_MIN <= value <= self._SQLITE_INT_MAX):
                raise ValueError(f"{field} is outside SQLite's integer range")
        clean_messages: list[dict[str, Any]] = []
        for message_index, message in enumerate(messages):
            clean_messages.append(self._normalize_import_message(message, message_index))
        return {"session": clean_session, "messages": clean_messages}

    def _validate_import_payload(self, sessions: list[dict[str, Any]]) -> tuple:
        """Size/shape/type validation of the whole payload; returns ``(normalized_items,
        errors)``. Every rejected entry is reported."""
        normalized: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        totals = {"messages": 0, "bytes": 0}
        for index, raw in enumerate(sessions):
            session_id = str(raw.get("id") or "").strip() if isinstance(raw, dict) else ""
            try:
                item = self._validate_import_session(raw, session_id, seen_ids, totals)
            except ValueError as exc:
                item = {"index": index, "error": str(exc)}
                if session_id:
                    item["session_id"] = session_id
                errors.append(item)
                continue
            seen_ids.add(session_id)
            normalized.append({"index": index, **item})
        return normalized, errors

    def _validate_import_session(self, raw: Any, session_id: str, seen_ids: set, totals: dict[str, int]) -> dict[str, Any]:
        """One payload session -> normalized item; ValueError(message) on rejection. *totals*
        accumulate before their limit check (a rejected oversize entry still counts)."""
        if not isinstance(raw, dict):
            raise ValueError("session must be an object")
        if not session_id:
            raise ValueError("session id is required")
        if session_id in seen_ids:
            raise ValueError("duplicate session id")
        messages = raw.get("messages") or []
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")
        if len(messages) > self._IMPORT_MAX_MESSAGES_PER_SESSION:
            raise ValueError("messages exceeds the per-session import limit")
        if any(not isinstance(msg, dict) for msg in messages):
            raise ValueError("messages must contain only objects")
        try:
            # `timings` is derived from the messages at export time and rebuilt on the next export;
            # it must not eat into the size budget of the content it merely describes.
            measured = {k: v for k, v in raw.items() if k != "timings"}
            session_bytes = len(json.dumps(measured, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            raise ValueError("session must be JSON serializable") from None
        if session_bytes > self._IMPORT_MAX_SESSION_BYTES:
            raise ValueError("session exceeds the import size limit")
        totals["bytes"] += session_bytes
        if totals["bytes"] > self._IMPORT_MAX_TOTAL_BYTES:
            raise ValueError("import exceeds the total size limit")
        item = self._normalize_import_session(raw, session_id, messages)
        totals["messages"] += len(item["messages"])
        if totals["messages"] > self._IMPORT_MAX_TOTAL_MESSAGES:
            raise ValueError("messages exceeds the total import limit")
        return item

    def _import_session_row(self, conn, raw: dict[str, Any], messages: list[dict[str, Any]], session_id: str) -> None:
        """INSERT one normalized session + its messages; counts fixed up after."""
        started_at = coerce_epoch(raw.get("started_at"), session_id=session_id, field="started_at")
        params = {
            "id": session_id, "source": str(raw.get("source") or "import"),
            "system_prompt_hash": self._store_system_prompt(conn, raw.get("system_prompt")),
            "started_at": time.time() if started_at is None else started_at,
            **{col: 1 if self._coerce_or(raw.get(col), int, 0) else 0 for col in _IMPORT_FLAG_COLS},
            **{col: raw.get(col) for col in _IMPORT_PASSTHROUGH_COLS},
            **{col: self._import_float_or_finite(raw.get(col), col) for col in _IMPORT_FLOAT_COLS},
            **{col: self._import_int_or_bounded(raw.get(col), col, 0) for col in _IMPORT_INT_COLS},
        }
        params["auto_archived"] &= params["archived"]  # only the sweep sets it, and only on rows it archives
        conn.execute(_IMPORT_SESSION_INSERT_SQL, params)
        def _json_value(value: Any) -> Any:
            return safe_json_loads(value, default=value) if isinstance(value, str) else value
        sanitized_messages = [
            {**msg, **{key: _json_value(msg.get(key)) for key in _IMPORT_MESSAGE_JSON_FIELDS}} for msg in messages
        ]
        # A row exported archived (``include_inactive``) must stay archived: inserted live, compacted or
        # rewound turns would re-enter model context. Flags are coerced like the int session columns, so a
        # hand-edited "0" archives and a missing/null/unparsable flag imports live (older exports have none).
        live: list[dict[str, Any]] = []
        archived: list[dict[str, Any]] = []
        for msg in sanitized_messages:
            (live if self._coerce_or(msg.get("active"), int, 1) else archived).append(msg)
        self._insert_message_rows(conn, session_id, sanitized_messages, prune_checkpoints=False)
        if archived:
            conn.executemany("UPDATE messages SET active = 0, compacted = ? WHERE id = ?",
                             [(1 if self._coerce_or(msg.get("compacted"), int, 0) else 0, msg["_row_id"])
                              for msg in archived])
        # Pruning keys on live rows, so it runs only now: while every row was still live, an archived row's
        # newer checkpoint would strip the newest live one, and archived rows keep theirs as in the donor.
        self._prune_shadowed_checkpoints(conn, session_id, live)
        # Session counters count live rows only.
        conn.execute("UPDATE sessions SET message_count = ?, tool_call_count = ? WHERE id = ?",
                     (len(live), sum(_tool_calls_count(_parse_tool_calls(msg.get("tool_calls"))) for msg in live),
                      session_id))

    @staticmethod
    def _attach_import_parents(conn, parent_updates: list[tuple]) -> int:
        """Re-attach imported children whose parent exists (in the store or the same payload)
        without creating a cycle; returns the detached count. Only the closing edge of a
        cycle is dropped, so later entries can still attach to the now-root session."""
        parent_by_child = dict(parent_updates)

        def _would_create_cycle(session_id: str, parent_id: str) -> bool:
            seen = {session_id}
            current = parent_id
            while current:
                if current in seen:
                    return True
                seen.add(current)
                if current in parent_by_child:
                    current = parent_by_child[current]
                    continue
                row = conn.execute(
                    "SELECT parent_session_id FROM sessions WHERE id = ? LIMIT 1", (current,),
                ).fetchone()
                if row is None:
                    return False
                current = row["parent_session_id"]
            return False

        detached = 0
        for session_id, parent_id in parent_updates:
            parent_exists = conn.execute("SELECT 1 FROM sessions WHERE id = ? LIMIT 1", (parent_id,)).fetchone()
            if parent_exists and not _would_create_cycle(session_id, parent_id):
                conn.execute("UPDATE sessions SET parent_session_id = ? WHERE id = ?", (parent_id, session_id))
            else:
                parent_by_child.pop(session_id, None)
                detached += 1
        return detached

    def append_session_event_with_cursor(
        self, cursor, session_id: str, event_type: str, payload: dict[str, Any],
    ) -> int:
        """Insert an event using the caller's active write cursor.

        Only call this from an existing ``_execute_write`` callback. It never
        starts or commits a transaction, so it is safe to compose with a state
        mutation without re-entering SessionDB's non-reentrant writer lock.
        """
        return _append_session_event_row(cursor, session_id, event_type, payload)

    def append_session_event(
        self, session_id: str, event_type: str, payload: dict[str, Any],
    ) -> int:
        """Append one immutable lifecycle event in its own write transaction."""
        return self._execute_write(
            lambda conn: self.append_session_event_with_cursor(
                conn, session_id, event_type, payload,
            )
        )

    def append_inbox_enqueue_with_receipt(
        self, session_id: str, payload: dict[str, Any],
    ) -> tuple[str, int, bool]:
        """Atomically deduplicate an inbox request id and append its receipt event."""
        request_id = str(payload.get("request_id") or "").strip()
        event_id = str(payload.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("inbox event id must not be empty")
        if request_id:
            lane = payload.get("lane")
            content = payload.get("content")

            def _append(conn):
                rows = conn.execute(
                    "SELECT seq, payload_json FROM session_events "
                    "WHERE session_id = ? AND event_type = 'inbox.enqueued' ORDER BY seq",
                    (str(session_id),),
                ).fetchall()
                for row in rows:
                    previous = safe_json_loads(row["payload_json"], default={})
                    if not isinstance(previous, dict):
                        continue
                    if str(previous.get("request_id") or "").strip() != request_id:
                        continue
                    if previous.get("lane") != lane or previous.get("content") != content:
                        raise ValueError("request id was already used with a different payload")
                    previous_event_id = str(previous.get("event_id") or "").strip()
                    if not previous_event_id:
                        raise RuntimeError("durable inbox request is missing its event id")
                    return previous_event_id, int(row["seq"]), False

                sequence = self.append_session_event_with_cursor(
                    conn, session_id, "inbox.enqueued", payload,
                )
                return event_id, sequence, True

            return self._execute_write(_append)

        sequence = self.append_session_event(session_id, "inbox.enqueued", payload)
        return event_id, sequence, True

    def claim_inbox_start(
        self, session_id: str, *, event_id: str, lane: str, run_id: str,
        request_id: str | None = None,
    ) -> tuple[int | None, str | None, bool]:
        """Atomically assign one pending inbox event to one worker run."""
        session_key = str(session_id or "").strip()
        event_key = str(event_id or "").strip()
        lane_key = str(lane or "").strip()
        run_key = str(run_id or "").strip()
        if not session_key or not event_key or not run_key:
            raise ValueError("session, event, and run identities must not be empty")
        if lane_key not in {"next-turn", "next-step"}:
            raise ValueError("invalid inbox lane")

        def _claim(conn):
            rows = conn.execute(
                "SELECT seq, event_type, payload_json FROM session_events "
                "WHERE session_id = ? AND event_type IN "
                "('inbox.enqueued', 'inbox.started', 'inbox.consumed', 'inbox.cancelled') "
                "ORDER BY seq",
                (session_key,),
            ).fetchall()
            enqueued = False
            started_run: str | None = None
            started_seq: int | None = None
            terminal = False
            for row in rows:
                payload = safe_json_loads(row["payload_json"], default={})
                if not isinstance(payload, dict) or str(payload.get("event_id") or "") != event_key:
                    continue
                if row["event_type"] == "inbox.enqueued" and payload.get("lane") == lane_key:
                    enqueued = True
                elif row["event_type"] == "inbox.started":
                    if started_run is None:
                        started_run = str(payload.get("run_id") or "") or None
                        started_seq = int(row["seq"])
                elif row["event_type"] in {"inbox.consumed", "inbox.cancelled"}:
                    terminal = True

            if not enqueued or terminal:
                return None, None, False
            if started_run is not None:
                return started_seq, started_run, started_run == run_key

            sequence = self.append_session_event_with_cursor(
                conn, session_key, "inbox.started", {
                    "event_id": event_key, "lane": lane_key,
                    "run_id": run_key, "request_id": request_id,
                },
            )
            return sequence, run_key, True

        return self._execute_write(_claim)

    def cancel_inbox_if_unstarted(
        self, session_id: str, *, event_id: str, lane: str,
        request_id: str | None = None,
    ) -> bool:
        """Append cancellation only if no worker has durably started the event."""
        session_key = str(session_id or "").strip()
        event_key = str(event_id or "").strip()
        lane_key = str(lane or "").strip()
        if not session_key or not event_key:
            raise ValueError("session and event identities must not be empty")
        if lane_key not in {"next-turn", "next-step"}:
            raise ValueError("invalid inbox lane")

        def _cancel(conn):
            rows = conn.execute(
                "SELECT event_type, payload_json FROM session_events "
                "WHERE session_id = ? AND event_type IN "
                "('inbox.enqueued', 'inbox.started', 'inbox.consumed', 'inbox.cancelled') "
                "ORDER BY seq",
                (session_key,),
            ).fetchall()
            enqueued = False
            started = False
            terminal = False
            for row in rows:
                payload = safe_json_loads(row["payload_json"], default={})
                if not isinstance(payload, dict) or str(payload.get("event_id") or "") != event_key:
                    continue
                if row["event_type"] == "inbox.enqueued" and payload.get("lane") == lane_key:
                    enqueued = True
                elif row["event_type"] == "inbox.started":
                    started = True
                elif row["event_type"] in {"inbox.consumed", "inbox.cancelled"}:
                    terminal = True
            if not enqueued or started or terminal:
                return False
            self.append_session_event_with_cursor(conn, session_key, "inbox.cancelled", {
                "event_id": event_key, "lane": lane_key, "request_id": request_id,
            })
            return True

        return self._execute_write(_cancel)

    def repair_interrupted_turns(self, session_id: str, turn_ids: set[str]) -> int:
        """Append reader-discovered turn closers without modifying transcript messages.

        The active turn set is rechecked inside the write transaction, making a
        concurrent reader repair idempotent and preventing duplicate closers.
        """
        if not turn_ids:
            return 0

        def _repair(conn):
            rows = conn.execute(
                "SELECT event_type, payload_json FROM session_events "
                "WHERE session_id = ? ORDER BY seq", (session_id,),
            ).fetchall()
            open_turns: dict[str, dict] = {}
            for row in rows:
                payload = json.loads(row["payload_json"])
                turn_id = str(payload.get("turn_id") or "")
                if not turn_id:
                    continue
                if row["event_type"] == "turn/start":
                    open_turns[turn_id] = payload
                elif row["event_type"] == "turn/end":
                    open_turns.pop(turn_id, None)
            repaired = 0
            for turn_id in sorted(turn_ids.intersection(open_turns)):
                self.append_session_event_with_cursor(conn, session_id, "turn/end", {
                    "turn_id": turn_id, "reason": "interrupted", "synthetic": True,
                })
                repaired += 1
            return repaired

        return self._execute_write(_repair)

    def list_session_events(
        self, session_id: str, *, after_seq: int = 0, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read durable session events after a sequence cursor, in append order."""
        session_id = str(session_id or "").strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError("after_seq must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, session_id, event_type, payload_json, created_at "
                "FROM session_events WHERE session_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                (session_id, after_seq, limit),
            ).fetchall()
        return [{
            "seq": int(row["seq"]),
            "session_id": str(row["session_id"]),
            "event_type": str(row["event_type"]),
            "payload": json.loads(row["payload_json"]),
            "created_at": str(row["created_at"]),
        } for row in rows]

    def list_inbox_events(
        self, session_id: str, *, after_seq: int = 0, limit: int = 1000,
    ) -> tuple[list[dict[str, Any]], int]:
        """Read only inbox lifecycle events after a cursor and return its safe high-water mark."""
        session_id = str(session_id or "").strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError("after_seq must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")

        event_types = (
            "inbox.enqueued", "inbox.started", "inbox.consumed", "inbox.cancelled",
        )
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                rows = self._conn.execute(
                    "SELECT seq, session_id, event_type, payload_json, created_at "
                    "FROM session_events WHERE session_id = ? AND seq > ? "
                    "AND event_type IN (?, ?, ?, ?) ORDER BY seq LIMIT ?",
                    (session_id, after_seq, *event_types, limit),
                ).fetchall()
                high_water = int(self._conn.execute(
                    "SELECT COALESCE(MAX(seq), ?) FROM session_events WHERE session_id = ?",
                    (after_seq, session_id),
                ).fetchone()[0])
            finally:
                self._conn.execute("ROLLBACK")

        events = [{
            "seq": int(row["seq"]),
            "session_id": str(row["session_id"]),
            "event_type": str(row["event_type"]),
            "payload": json.loads(row["payload_json"]),
            "created_at": str(row["created_at"]),
        } for row in rows]
        next_cursor = events[-1]["seq"] if len(events) == limit else high_water
        return events, max(after_seq, int(next_cursor))

    def import_sessions(
        self, sessions: list[dict[str, Any]], *,
        session_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Import sessions exported by :meth:`export_session` or ``export_all``. Existing ids
        are skipped. A child keeps its parent only when the parent exists or is in the
        same payload; otherwise it is detached so partial imports pass FK validation.
        Gateway routing, handoff, rewind and other live runtime state are reset: this
        restores history, not ownership of a live channel or process. Export INCLUDES
        ``last_activity_*`` but import RESETS them to NULL — resurrecting a stale
        "working ..." label would fabricate activity the watchdog acts on (pinned).

        Activity contract (#76354 review S4): export INCLUDES the live activity fields (``last_activity_at``
        / ``last_activity_description`` / ``last_activity_provenance``) because they are part of the durable
        row, but import deliberately RESETS them to NULL. This asymmetry is intentional and covered by
        regression
        (tests/gateway/test_watchdog_review.py::test_s4_export_includes_activity_import_resets_it).
        """
        if not isinstance(sessions, list):
            raise ValueError("sessions must be a list")
        if len(sessions) > self._IMPORT_MAX_SESSIONS:
            raise ValueError(f"sessions must contain at most {self._IMPORT_MAX_SESSIONS} entries")
        normalized, errors = self._validate_import_payload(sessions)
        if errors:
            return {"ok": False, "imported": 0, "skipped": 0, "detached": 0, "errors": errors}
        events = list(session_events or [])
        valid_ids = {str(item["session"].get("id") or "").strip() for item in normalized}
        for event in events:
            if (not isinstance(event, dict)
                    or str(event.get("session_id") or "").strip() not in valid_ids
                    or not str(event.get("event_type") or "").strip()
                    or not isinstance(event.get("payload", {}), dict)):
                raise ValueError("session_events must target an imported session and contain an event type and object payload")

        def _do(conn):
            imported_ids: list[str] = []
            skipped_ids: list[str] = []
            parent_updates: list[tuple[str, str]] = []
            for item in normalized:
                raw = item["session"]
                session_id = str(raw.get("id") or "").strip()
                if conn.execute("SELECT 1 FROM sessions WHERE id = ? LIMIT 1", (session_id,)).fetchone():
                    skipped_ids.append(session_id)
                    continue
                self._import_session_row(conn, raw, item["messages"], session_id)
                parent_id = str(raw.get("parent_session_id") or "").strip()
                if parent_id:
                    parent_updates.append((session_id, parent_id))
                imported_ids.append(session_id)
            imported_set = set(imported_ids)
            for event in events:
                session_id = str(event["session_id"]).strip()
                if session_id not in imported_set:
                    continue
                self.append_session_event_with_cursor(
                    conn, session_id, str(event["event_type"]), event.get("payload", {}),
                )
            return {
                "ok": True, "imported": len(imported_ids), "skipped": len(skipped_ids),
                "detached": self._attach_import_parents(conn, parent_updates),
                "imported_ids": imported_ids, "skipped_ids": skipped_ids, "errors": [],
            }

        return self._execute_write(_do)

