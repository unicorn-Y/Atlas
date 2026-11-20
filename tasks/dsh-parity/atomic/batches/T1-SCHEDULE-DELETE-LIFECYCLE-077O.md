# T1-SCHEDULE-DELETE-LIFECYCLE-077O

Status: `DONE_SCOPED` for the pinned deletion lifecycle test-source block.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:3924-4128`; 105 semantic units and nine direct tests.
- Depends on mock metrics/layout map 077N.

Five groups map confirmation and bounded dialog content; explicit confirmation/Cancel/Escape and stale confirmation cleanup; deletion disabled while a rule update is pending; closing only after refreshed catalog acknowledgement; and failure retry, refresh retry and no-authoritative-removal outcomes.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":105,"mapped":105,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":9,"it_each":0,"unresolved_before":408409}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.31s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.85s
```

No DSH tests or Atlas deletion UI were executed.

## Remaining obligations

- Global ledger after this map: 413,747 total / 408,304 unresolved.
- Runtime deletion and authoritative refresh parity, timing picker source and global superiority remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-DELETE-LIFECYCLE-077O.md`.
