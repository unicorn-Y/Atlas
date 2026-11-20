# T1-SESSION-HISTORY-TRANSPORT-093 — Host history and client transport

Status: DONE_SCOPED for pinned source mapping and DSH acceptance evidence.

## Scope and coverage

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped 108 indexed units: 71 in `packages/api/session-controller/src/history.ts` and 37 in `packages/api/session-controller/src/client/transport.ts`.
- Two atoms cover Host history authorization/paging/serialization and Client remote page/follow/control adaptation. Three interaction edges cover Host page-to-journal, Client event cursor/reconnect, and control baseline/deltas.
- Atlas source files `core/atlas/engine/session_sync.py` and `core/atlas/api/runtime_ws_router.py` were read only for comparison; no Atlas production code changed.

## Host history controller (`src/history.ts`, 71 units)

`SessionHistoryController.page` validates the request and address, then resolves the authorized source before reading either a cold history or an active session journal. It validates cursor/window bounds, pages durable event records, preserves source-event references attached to appended messages, aligns history pagination to message/turn boundaries, serializes the header and event records, and includes the current assistant-stream baseline where opted in. Address validation distinguishes ordinary sessions from subagent descriptors and does not invent missing descriptor metadata. Helper contracts include scalar cursor conversion, max-message/turn-window validation, address-to-session resolution, not-found classification, pagination and wire record construction.

`session-history-journal.host.spec.ts` includes cold/opening/live race cases, foreign/buffered frame filtering, FIFO ordering, revision restart and gap behavior, contiguous message-aligned pages, source-reference ownership, malformed cursor/window rejection and source failure classification.

## Client transport (`src/client/transport.ts`, 37 units)

The client adapts remote page and follow methods into address-bound journal streams. It validates returned wire events before publication, preserves payloads and envelopes, advances only the durable event cursor, replaces the retained window on reconnect, detects sequence and assistant-revision gaps, and maps Host control baseline/deltas into a single observable snapshot stream. Failure paths retain typed stream errors and distinguish termination before or after the opening baseline.

`transport.host.spec.ts` covers initial cursor/live follow, ownership unload, replacement snapshots, subscribe-before-cold-read races, buffered events, source-opening boundaries, replay/live sequence gaps and source validation. `transport.client.spec.ts` covers unchanged envelope/payload preservation, assistant baseline opt-in, invalid ordering/gap rebaseline, scalar range validation, journal address binding, reconnect window replacement, pagination failures, and control baseline/delta termination.

## Atlas comparison and limits

The DSH source contract is Host-authorized durable history plus replay/live journal stitching and a Client remote adapter with cursor-safe replacement. Atlas has SessionDB history and WebSocket event routes, but this batch did not run a paired mixed-source, reconnect, subagent-address and cursor-gap trace across Atlas API, SDK and desktop. Both atoms/three edges remain `PARTIAL` and implementation `OPEN`; no Atlas parity or superiority claim is made.

## Verification

Focused command:

```text
pnpm exec vitest run packages/api/session-controller/tests/session-history-journal.host.spec.ts packages/api/session-controller/tests/transport.host.spec.ts packages/api/session-controller/tests/transport.client.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 3 passed (3); Tests 292 passed (292); Duration 7.92s`; exit 0.

Audit-module command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-history-transport-093-ledger
```

Actual output: `41 passed, 5 warnings in 13.87s`; exit 0.

Full scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-HISTORY-TRANSPORT-093-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 269.8280000000086, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Reconciliation found 108/108 target decisions, zero missing, zero duplicates and no digest/reference issues. Global inventory is 413,747 total / 407,450 unresolved and remains `INCOMPLETE`.
