# T1-SESSION-ATTEMPT-STREAM-WIRE-092 — assistant stream and wire contract

Status: DONE_SCOPED for pinned source mapping and DSH acceptance evidence.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- The current source index contains 93 semantic units across four files: 14 Host accumulator, 22 ClientAssistantStream, 16 wire validator, and 41 event-source units. A preliminary 67 count was a parser-boundary error and was discarded before any ledger writes.
- All 93 decisions bind the indexed unit digest and reference one of four atoms and four interaction edges.
- Atlas product files were not changed in this mapping batch.

## Contract crosswalk

### Host assistant-stream accumulator (`src/assistant-stream.ts`, 14 units)

`SessionAssistantStreamAccumulator` folds revisioned start/chunk/end frames into the history-side assistant baseline. A new lifecycle replaces stale state; a revision discontinuity clears the active attempt; chunk identity and index are checked before the baseline is advanced; the snapshot is cached by revision and stream identity. The Host consumer is `src/history.ts`, which embeds the baseline in the session history/follow journal. `assistant-stream.host.spec.ts` exercises stale lifecycle replacement, gap rejection and snapshot caching.

### Client assistant stream (`src/client/sessions/assistant-stream.ts`, 22 units)

`ClientAssistantStream` reconciles transient frames and durable `assistant/message` / `assistant/attempt` entries by attempt ID, turn, step, sequence and append surface. It stages durable settlement behind the exact stream end, requests rebaseline on index/identity/duplicate-settlement mismatch, preserves successful non-interrupted chunks until the owning step boundary, and retires only the matching attempt. Reconnect replacement reconstructs the active baseline. The direct test suite covers these cases; `session.ts` publishes through the event source, and the `sessions-service` tests verify the externally visible order.

### Session wire validation (`src/client/session-wire-event.ts`, 16 units)

`assertSessionWireEvent` validates the current wire envelope, scalar sequence/time, ignorable marker, surface metadata and event-specific payload while preserving payloads. `src/client/transport.ts` calls it on history records, follow events and transport results before client publication. Durable event-range/existence authority remains Host-owned; the client guard does not invent history truth.

### Mutable event source (`src/client/contract/events.ts`, 41 units)

The event window is a persistent leaf/concat structure with lazy materialization, identity-stable snapshots, and synchronous subscription notification. `replace`, `prepend` and `append` preserve their respective history-window contracts. `settleAssistant` filters only transient entries bearing the exact settled attempt ID and inserts an optional durable entry in sequence order. The Session bridge calls this during assistant publication/retirement; `client-contract.client.spec.ts` covers window and scoped-retirement semantics.

## Consumer and integration boundaries

- Host history assembly → assistant baseline → transport history/follow frames is represented by `EDGE-T1-DSH-HOST-STREAM-HISTORY-092`.
- Transport wire validation → client event projection is represented by `EDGE-T1-DSH-WIRE-TRANSPORT-092`.
- Transient stream + exact durable settlement → Session event source publication/retirement is represented by `EDGE-T1-DSH-CLIENT-SETTLEMENT-092` and `EDGE-T1-DSH-EVENT-ATTEMPT-RETIREMENT-092`.
- These edges establish the pinned DSH behavior and its tests. They do not establish Atlas parity, renderer behavior under a real model, packaged desktop behavior, or superiority.

## Focused verification

Command:

```text
pnpm exec vitest run packages/api/session-controller/tests/assistant-stream.host.spec.ts packages/api/session-controller/tests/assistant-stream.client.spec.ts packages/api/session-controller/tests/session-history-journal.host.spec.ts packages/api/session-controller/tests/transport.client.spec.ts --reporter=dot --no-file-parallelism
```

Actual result from the focused run: `Test Files 4 passed (4); Tests 283 passed (283); Duration 7.76s`; exit 0. Exact relevant cases include:

- `SessionAssistantStreamAccumulator`: `replaces stale lifecycles, rejects frame gaps, and caches each baseline`.
- Client stream: `publishes a successful message at stream end and retires its chunks at its Step end`; `rebaselines known attempts on chunk or terminal index mismatch`; `settles abandonment only when no durable settlement remains pending`.
- Transport: `opts into assistant notifications and publishes the reconnect baseline plus live frame`; `rebaselines after a transient assistant revision gap without advancing the durable cursor`; `preserves current envelopes and payloads without normalization across every journal path`.
- Host journal cases exercise baseline-before-frame order, foreign/buffered frame filtering, mixed FIFO ordering, and resumed source handling.

## Atlas comparison

The mapped DSH contract is exact-attempt transient/durable reconciliation plus a client-only event window, validated wire ingress and reconnect baseline. Atlas has related kernel attempt audit, WebSocket events and renderer projection, but this batch did not run a paired Atlas trace over the same attempt and reconnect fixtures. All four atoms and edges remain `PARTIAL` / implementation `OPEN`; no `SUPERIOR` claim is made.

## Audit and scan

Audit-module command/result and full-scan runner output are recorded below. The completed scan reconciled all 93 target decisions and global index/completion metadata.

### Audit module

Command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-stream-092-ledger
```

Actual output: `41 passed, 5 warnings in 13.91s`; exit 0.

### Full source scan

Command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-ATTEMPT-STREAM-WIRE-092-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 272.81200000000536, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Reconciliation found 93/93 target decisions, zero missing, zero duplicates, no digest/reference issues. The global inventory is 413,747 total / 407,558 unresolved and remains `INCOMPLETE`.

