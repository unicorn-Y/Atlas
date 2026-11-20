# T1-SCHEDULE-CRON-ASYNC-STATE-077K

Status: `DONE_SCOPED` for the pinned card async/state test-source slice.

## Scope and mapped obligations

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:3122-3371`; 121 semantic units.
- Test shape: 11 direct declarations and four `it.each(...)` declarations/eight rows.
- Depends on cron editor mapping 077J.

The five groups record committed-occurrence seeding and raw-expression preservation; Escape/focus return; pending-save disabled state; localized conflicts, failure and Cancel behavior; stale success/rejection after task switch or unmount; and ended/read-only plus task-zone time display.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":121,"mapped":121,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":11,"it_each":4,"unresolved_before":408807}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.86s
```

Only the audit-tool tests were run; no DSH or Atlas frontend behavior was executed.

## Remaining obligations

- Global ledger after this map: 413,747 total / 408,686 unresolved.
- Remaining card, edit/delete/metrics and all Atlas runtime superiority work remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-CRON-ASYNC-STATE-077K.md`.
