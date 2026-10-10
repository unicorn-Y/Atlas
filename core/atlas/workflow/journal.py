# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e: apps/zcode-cli/packages/dynamic-workflow/src/engine/engine.ts (Apache-2.0)
"""SQLite event journal and graph snapshot replay for workflow runs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .graph import graph_from_dict, graph_to_dict
from .types import WorkflowGraph


_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    workflow_id TEXT PRIMARY KEY,
    input_hash TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    status TEXT NOT NULL,
    pause_requested INTEGER NOT NULL DEFAULT 0,
    sequence INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_events (
    workflow_id TEXT NOT NULL REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY (workflow_id, sequence)
);
CREATE INDEX IF NOT EXISTS workflow_events_by_type
    ON workflow_events(workflow_id, timestamp);
"""


class WorkflowJournal:
    """Own a dedicated ``workflow.db``; it never opens or alters Atlas SessionDB."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_journal_path()
        self.path = self.path.expanduser().resolve()
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def ensure_graph(self, graph: WorkflowGraph, *, resume: bool = False) -> tuple[WorkflowGraph, str, bool, bool]:
        """Create a run once or load its persisted graph for deterministic resume."""
        if not graph.workflow_id:
            raise ValueError("Workflow graph must have a workflow_id before journaling")
        now = _utc_now()
        graph_json = _encode_graph(graph)
        input_hash = _input_hash(graph)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT input_hash, graph_json, status, pause_requested FROM workflow_runs WHERE workflow_id = ?",
                (graph.workflow_id,),
            ).fetchone()
            if row is None:
                if resume:
                    raise KeyError(f"Unknown workflow id: {graph.workflow_id}")
                connection.execute(
                    "INSERT INTO workflow_runs(workflow_id,input_hash,graph_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (graph.workflow_id, input_hash, graph_json, "running", now, now),
                )
                return graph_from_dict(json.loads(graph_json)), "running", False, True
            saved_hash, saved_json, status, pause_requested = row
            if not resume and saved_hash != input_hash:
                raise ValueError(f"Workflow id {graph.workflow_id!r} already exists with a different input graph")
            return graph_from_dict(json.loads(saved_json)), status, bool(pause_requested), False

    def load_graph(self, workflow_id: str) -> WorkflowGraph:
        """Replay the latest graph snapshot for a stored run."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT graph_json FROM workflow_runs WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown workflow id: {workflow_id}")
        return graph_from_dict(json.loads(row[0]))

    def status(self, workflow_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM workflow_runs WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown workflow id: {workflow_id}")
        return str(row[0])

    def pause_requested(self, workflow_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pause_requested FROM workflow_runs WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown workflow id: {workflow_id}")
        return bool(row[0])

    def request_pause(self, workflow_id: str) -> None:
        """Persist a cooperative pause request; the scheduler drains active nodes."""
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT sequence FROM workflow_runs WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown workflow id: {workflow_id}")
            sequence = int(row[0]) + 1
            timestamp = _utc_now()
            event = {"workflow_id": workflow_id, "timestamp": timestamp, "type": "workflow_pause_requested"}
            connection.execute(
                "INSERT INTO workflow_events(workflow_id,sequence,timestamp,event_json) VALUES(?,?,?,?)",
                (workflow_id, sequence, timestamp, json.dumps(event, separators=(",", ":"))),
            )
            connection.execute(
                "UPDATE workflow_runs SET pause_requested = 1, sequence = ?, updated_at = ? WHERE workflow_id = ?",
                (sequence, timestamp, workflow_id),
            )

    def clear_pause_request(self, workflow_id: str) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE workflow_runs SET pause_requested = 0, updated_at = ? WHERE workflow_id = ?",
                (_utc_now(), workflow_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown workflow id: {workflow_id}")

    def record_event(self, graph: WorkflowGraph, event: dict[str, Any], *, status: str | None = None) -> int:
        """Atomically append an event and persist the matching graph state."""
        if not graph.workflow_id:
            raise ValueError("Workflow graph has no workflow_id")
        now = _utc_now()
        event_json = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        graph_json = _encode_graph(graph)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT sequence, status FROM workflow_runs WHERE workflow_id = ?",
                (graph.workflow_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown workflow id: {graph.workflow_id}")
            sequence = int(row[0]) + 1
            next_status = status if status is not None else str(row[1])
            connection.execute(
                "INSERT INTO workflow_events(workflow_id,sequence,timestamp,event_json) VALUES(?,?,?,?)",
                (graph.workflow_id, sequence, str(event.get("timestamp", now)), event_json),
            )
            connection.execute(
                "UPDATE workflow_runs SET graph_json = ?, status = ?, sequence = ?, updated_at = ? WHERE workflow_id = ?",
                (graph_json, next_status, sequence, now, graph.workflow_id),
            )
            return sequence

    def events(self, workflow_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        """Read journal events in their durable sequence order."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM workflow_events WHERE workflow_id = ? AND sequence > ? ORDER BY sequence",
                (workflow_id, after_sequence),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection


def default_journal_path() -> Path:
    """Return ``<ATLAS_DATA_DIR>/workflow.db`` or the checkout's ``data/workflow.db``."""
    configured = os.environ.get("ATLAS_WORKFLOW_DB")
    if configured:
        return Path(configured)
    data_root = os.environ.get("ATLAS_DATA_DIR")
    if data_root:
        return Path(data_root) / "workflow.db"
    repository_root = Path(__file__).resolve().parents[3]
    return repository_root / "data" / "workflow.db"


def _input_hash(graph: WorkflowGraph) -> str:
    encoded = _encode_graph(graph)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encode_graph(graph: WorkflowGraph) -> str:
    return json.dumps(graph_to_dict(graph), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

