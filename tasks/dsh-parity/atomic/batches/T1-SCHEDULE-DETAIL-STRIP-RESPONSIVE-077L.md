# T1-SCHEDULE-DETAIL-STRIP-RESPONSIVE-077L

Status: `DONE_SCOPED` for the pinned frequency-line and linked-session-strip test-source slice.

## Scope

- Pinned DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- File `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:3372-3522`, 68 semantic units.
- Four direct test declarations and two `it.each(...)` declarations/four locale rows.
- Depends on cron-card async-state source map 077K.

Three capability groups cover omission of host-equivalent zone and localized ICU display for non-host zone in frequency line; Rules-only linked Session control, responsive icon/tooltip and accessibility separation from scroll/destructive actions; and tab scrolling without visible scrollbar. Three partial test edges connect to zone formatting, linked-session layout and tab primitives.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":68,"mapped":68,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":4,"it_each":2,"unresolved_before":408686}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.31s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.81s
```

No DSH UI or Atlas UI was executed.

## Remaining obligations

- Global source ledger after this map: 413,747 total / 408,618 unresolved.
- Later TaskDetail edit/delete/metrics tests and runtime parity remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-DETAIL-STRIP-RESPONSIVE-077L.md`.
