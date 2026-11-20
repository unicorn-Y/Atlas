# T1-SCHEDULE-WEEKLY-CRON-CARD-077I

Status: `DONE_SCOPED` for the weekly/cron TaskDetail test-source slice.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:2622-2871`; 120 semantic units.
- Test shape: 11 direct `it(...)` declarations plus four locale-parameterized declarations with eight rows (19 variants).
- Dependency: recurrence transition source slice 077H.

## Capability groups

- Weekly clock/zone carry; occurrence-based weekday initialization; full weekday-set submission; pending-save disable/failure draft handling; last-weekday toggle rule.
- Stored weekly card display and ended/read-only weekly state.
- Cron choice reveals structured rows without a request; unknown cron remains a raw row with explanatory hint.
- Complete cron payload, recurrence switch seeded from committed occurrence, and local invalid-expression rejection without remote update.

Three `PARTIAL` source edges link the tests to weekly state, cron parse/format/card hints and the timing update payload. The source map makes no execution claim.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":120,"mapped":120,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":11,"it_each":4,"unresolved_before":409045}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.73s
```

Only the Atlas audit-tool suite ran; DSH and Atlas frontend behavior were not executed.

## Remaining obligations

- Global source ledger after this slice: 413,747 total / 408,925 unresolved.
- Remaining rule-card source, DSH execution and Atlas runtime parity/superiority are open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-WEEKLY-CRON-CARD-077I.md`.
