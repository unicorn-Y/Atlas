# T1-SCHEDULE-DETAIL-NAME-INSTRUCTION-METRICS-077M

Status: `DONE_SCOPED` for the pinned text-edit and metrics test-source block.

## Scope and mapped behaviors

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:3523-3713`; 96 semantic units.
- Test shape: ten direct declarations plus three `it.each(...)` declarations/six locale rows.
- Depends on responsive detail strip map 077L.

Five groups map localized text-field labels/initial values and timing-preserving or combined Save; blank/over-limit/exact-limit name validation; required instruction and Cancel reset; rejected save plus authoritative refresh draft behavior; and ended-task read-only state with metrics projection into header, next-run and instruction display.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":96,"mapped":96,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":10,"it_each":3,"unresolved_before":408618}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.80s
```

These are ledger-tool tests only. No DSH tests or Atlas frontend runtime were executed.

## Remaining obligations

- Global source ledger after this map: 413,747 total / 408,522 unresolved.
- The metrics consumer, deletion, timing picker, source CSS and all runtime parity/superiority remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-DETAIL-NAME-INSTRUCTION-METRICS-077M.md`.
