# Exact embedded task-state and event-delivery source

- Artifact: Claude Code 2.1.302 win32-x64 `package/claude.exe`, SHA-256 `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`.
- Method: direct bounded byte extraction from readable embedded Bun application JS at the decimal PE file offsets listed here. Static S only; this is not a native control-flow graph or a live event capture.

## Task registration and lifecycle event production

At offset **246,861,552**, `Kn(e,n)` registers/updates a task in the host task map. It assigns/retains a `run_id` per run and emits `system/task_started` unless the task is suppressed by `Yu(e)`. The payload includes `task_id`, `run_id`, `owned_by_subagent`, `tool_use_id`, description, subagent type, background/awaited flags, spawn depth, `parent_task_id`, task type, workflow, prompt and skip/ambient fields. A resumed task can keep its `task_id` and get a later `run_id` per the exact schema description at `evidence/13-native-message-task-schemas.md`.

At offset **246,859,691**, `Hn(e,n,r)` applies a state transition to an existing task. It computes the wire-safe patch using `Un`, checks the transition from nonterminal to terminal, builds terminal notification options from tool-use ID, status, summary/description, failure kind, output file, usage, resource links and handback/report fields, and updates the task map. For a nonterminal transition it emits `task_updated`; on terminal transition it emits both the final `task_updated` patch and `_a(taskId,status,opts)`, which creates a `task_notification`. The source uses `Dy`/`EMo` terminal-emission claims to prevent duplicate notification emission; do not infer crash durability from this in-memory guard.

`_a` begins at offset **242,665,992**. It creates a terminal notification with task/run/tool IDs, status, reason, output file, summary, usage, links, handback and transcript flags, then passes it through event sanitization (`Vgt`) and `Ei` into the event queue.

## Queue and event consumer behavior

The source around offset **242,662,000** defines the `Ny` per-host task event queue. Its queue limit is 1,000 entries. On overflow it drops a `stream_event` directly; otherwise it first evicts non-bookend events while preserving `task_started`, `task_notification`, selected status-clear and dev-intent frames. When only bookends remain, it may evict one and records a specific bookend-eviction metric. `background_tasks_changed` snapshots can be held/coalesced while level events are held. Drain stamps queued frames with UUID and `session_id`; an optional persisted-lane redaction transforms task failure output before sending. This is bounded event delivery, not a durable event log.

At offset **269,514,323**, `Gzr` consumes lifecycle frames into a task map: a `background_tasks_changed` frame replaces the current map, `task_started` upserts background tasks, `task_notification` removes a task, and progress/patch frames are recognized without direct map replacement there. Adjacent `Tyn` computes both lifecycle recognition and a `backgroundTaskEnded` result from terminal notifications.

At offset **275,456,189**, class `ut` tracks non-`_in_process_teammate` tasks in an activity-age set. It adds on task start, removes on task notification or terminal-status patch, and drops/rebuilds from replacement background-task snapshots. It has a six-hour age bound (`21,600,000` ms). This establishes an additional consumer policy but not a user-visible panel implementation.

At offset **271,766,500**, one CLI consumer explicitly skips `task_started`, `task_progress`, `task_updated`, `task_notification` and `background_tasks_changed` from ordinary text rendering while handling status, errors and stream events separately. At offset **275,511,900**, a history/redaction projection preserves a narrow task identity/status subset and replaces error/summary payloads with sanitized forms. These are distinct consumers with different needs.

## What this closes and what remains open

Static code now closes task-map mutation → task lifecycle event construction → bounded host queue → selected lifecycle consumers. A separate static SendMessage route closes inbox append/read/ack and retry-wake ordering (`evidence/15-native-mailbox-source.md`). No source trace yet proves that the same spawned child consumes the queued inbox entry, finishes its next model turn, or causes the parent CLI/UI to receive and persist this exact terminal notification. The observed synthetic CLI request stopped at HTTP 401 before a task was created. Runtime event ordering, cross-process transport, persistence, parent notification and restart replay therefore remain U.
