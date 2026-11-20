# T1-SESSION-LIST-CONTROL-099 — Session summaries, search and Host control stream

Status: DONE_SCOPED for pinned source mapping and DSH acceptance evidence.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped all 70 indexed units: `src/list.ts` 47 and `src/control.ts` 23.
- Two atoms cover list/search work and Host control snapshot/delta streaming; three edges separate summary scheduling, search bounds and control stream ordering.
- Atlas comparison was read-only; no production code changed.

## List and search

`ApiSessionList` validates and applies persisted Session list metadata, builds summary projection fields, and processes cold/live sessions using a bounded work slice. The scheduler accounts for skipped classification work, supports caller overrides, resets the deadline after yielding, and respects cancellation. Blank first-send sessions remain represented correctly. Search normalizes and bounds queries, caps provider calls at 100, and truncates snippets by Unicode code points rather than UTF-16 units. Provider and inspection errors remain typed instead of fabricated as empty success.

## Host control stream

`SessionControlController` emits a current baseline followed by later control deltas. `ControlQueue` preserves changes observed while the opening snapshot is assembled and ends the iterator when its source closes; the transport consumer folds the stream into one snapshot generation.

## Focused verification

```text
pnpm exec vitest run packages/api/session-controller/tests/list-scheduling.host.spec.ts packages/api/session-controller/tests/session-list-blank.host.spec.ts packages/api/session-controller/tests/session-search.host.spec.ts packages/api/session-controller/tests/transport.host.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 4 passed (4); Tests 75 passed (75); Duration 2.79s`; exit 0.

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-list-control-099-ledger
```

Actual output: `41 passed, 5 warnings in 13.83s`; exit 0.

## Atlas comparison

Atlas session search and runtime websocket/control code were read as comparators, not executed as a paired scenario. This batch does not prove same-work-slice list output, source scoping, Unicode snippet, baseline race, or reconnect/control ordering across Atlas API and desktop. Both atoms/edges remain `PARTIAL` / implementation `OPEN`; no parity or superiority claim is made.

## Full source scan

Full scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-LIST-CONTROL-099-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 268.875, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Reconciliation found 70/70 target decisions, zero missing/duplicate decisions and no digest/reference issues. Global inventory is 413,747 total / 406,847 unresolved and remains `INCOMPLETE`.
