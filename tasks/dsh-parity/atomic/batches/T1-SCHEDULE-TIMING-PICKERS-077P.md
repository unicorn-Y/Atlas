# T1-SCHEDULE-TIMING-PICKERS-077P

Status: `DONE_SCOPED` for the final TaskManagerPage clock/calendar picker test-source block.

## Scope and behavior

- Pinned DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:4129-4366`; 87 semantic units.
- Test shape: 13 direct declarations and one two-locale `it.each(...)` declaration (15 variants).
- Depends on deletion source map 077O.

Five groups record clock-column opening/staged value/selection/keyboard/scroll; clock Escape/outside dismissal, focus and minute-to-second submission; calendar dismissal and read-only gating; month/date marking and keyboard navigation; and Escape/focus plus accessible labels.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":87,"mapped":87,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":13,"it_each":1,"unresolved_before":408304}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.85s
```

These validate ledger tooling only; DSH tests and Atlas UI/runtime were not run.

## Remaining obligations

- Global source ledger after this slice: 413,747 total / 408,217 unresolved.
- Runtime picker parity, CSS and the broader schedule API/helper/runtime obligations remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-TIMING-PICKERS-077P.md`.
