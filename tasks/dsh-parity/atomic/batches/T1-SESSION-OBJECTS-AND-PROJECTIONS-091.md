# T1-SESSION-OBJECTS-AND-PROJECTIONS-091 — session event state, leases and projection watermarks

Status: DONE_SCOPED for source mapping and pinned DSH acceptance.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Reviewed 115 units in `session.ts`, 111 in `service.ts`, and 33 in `projection-store.ts`, including their remote, journal, event-source, UI-subscription and lifecycle consumers.
- Atoms: `T1-DSH-SESSION-OBJECT-091`, `T1-DSH-SESSION-SERVICE-091`, `T1-DSH-PROJECTION-VALUE-STORE-091`.
- Edges separate open/history, attempt-aware assistant stream settlement, source-labelled Session ownership, and projection sequence/cached watermark behavior. All 259 source decisions bind indexed digests.

## Contract crosswalk

### `Session` (`session.ts`, 941 lines)

- Submission is synchronous before remote work: `beginSubmission` mints a request ID, chooses transcript/queued/steering placement from running state and mode, renders a local echo, and returns an explicit abandon path. `prompt` routes local versus addressed subagent prompts, rejects unsupported subagent file attachments, sends queue/steer unchanged, and retires only the matching echo on failure. A rejected first prompt remains blank/reusable; accepted prompt transitions blank state and records engagement.
- `open` is idempotent and single-flight. `doOpen` creates the history/follow journal for one open generation; stale opens cannot overwrite a later resync. Paging is turn-aligned, cursor-based and bounded; `loadThrough` coalesces/retargets concurrent jumps; `resync` replaces only the current stream generation. Remote failures become observable open state while unexpected errors propagate.
- Live history changes distinguish replace/prepend/durable append/assistant-stream. A replacement installs a contiguous cursor window and optional projection/assistant baseline; a gap repair discards transient assistant attempts and forces an atomic page/baseline reopen. Durable assistant messages settle only the exact attempt ID; discarded/abandoned assistant attempts retire transient rows; transient chunks remain separate from committed history. Reconnect baseline replacement prevents duplicate chunks.
- Inbox projection watchers correlate request IDs, target and sequence with durable `agent/inbox/spliced` receipts; an observed acceptance retires the optimistic echo only after the durable message can render. Failed/cancelled submissions, queued receipts, attachment refs, and frame-scheduled retirement are handled separately.
- Snapshot state includes open/error/running/blank/subagent, pending submission and history-loading state. Removal, Agent failure, parent availability and `dispose` have explicit transitions; disposal awaits remote stream cleanup and clears listeners/settlement state.

### `ClientSessions` (`service.ts`, 717 lines)

- Public summary/error/retention contracts preserve workspace/title/lineage and distinguish create/fork failures from successful publication. A `ClientSessionReference` owns one source-labelled lease, can attach to the current opening with optional abort, and releases exactly once.
- The service separates catalog discovery from history ownership: catalog rows do not eagerly open Sessions. `retain` resolves target identity, updates per-source counts, opens the exact Session generation, and exposes `ready`/release state. Parent/subagent scopes and the agent Context are bound to that exact generation and become unavailable on retirement.
- Search, list refresh, projection reads, create/fork and Host event methods delegate to the typed manager/remotes while retaining operation results and failures. Root disposal retires contexts and waits for opened Session sources/drop work to finish.

### `ProjectionValueStore` (`projection-store.ts`, 244 lines)

- Each projection key has a visible value and optional same-connection sequence watermark. Same-generation sequenced writes accept only a higher sequence; cached checkpoint values are non-comparable and fill keys without an authoritative live value. `seed` replaces a complete baseline at its watermark; `clear` drops old-generation values/watermarks but keeps observable faces alive. Subscriptions are per-key or all-key and notify only visible changes.

## Attempt-aware DSH acceptance

The focused `sessions-service.client.spec.ts` includes:

- `publishes the final Assistant message before retiring transient chunks at Step end` — starts an identified assistant attempt, streams a transient chunk, receives the durable assistant message, commits that exact attempt and only then retires transient chunks at `step/end`.
- `replaces an active assistant baseline on reconnect without duplicate chunks` — reconstructs an active attempt from the reconnect baseline without replay duplication.
- `stages a post-opening assistant settlement behind its exact active attempt` and `replaces an invalid settlement with the authoritative post-end baseline` — guard attempt identity and authoritative final state.

These are pinned DSH client tests and do not prove Atlas protocol equivalence or packaged UI behavior.

## Atlas comparison

Atlas has session message/timeline APIs, durable attempt audit, and renderer rollback projection. This batch does not establish a 1:1 DSH assistant-stream baseline/settlement protocol, source-labelled ClientSession lease lifecycle, or same-generation projection-store watermark semantics. The three atoms and four edges stay PARTIAL/OPEN. No product code changed.

## Verification

```text
pnpm exec vitest run packages/api/session-controller/tests/session.client.spec.ts packages/api/session-controller/tests/sessions-service.client.spec.ts packages/api/session-controller/tests/projection-store.client.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 3 passed (3); Tests 127 passed (127); Duration 4.37s`; exit 0.

Atlas audit-module command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-objects-091-ledger
```

Actual output: `41 passed, 5 warnings in 13.88s`; exit 0.

Full source scan:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-OBJECTS-AND-PROJECTIONS-091-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 270.6720000000205, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Post-scan check: 259/259 target units have digest-bound MAPPED decisions, zero missing; global index is 413,747 total / 407,651 unresolved and `INCOMPLETE`.

Global source closure remains INCOMPLETE until the complete indexed obligation set is resolved and audited.
