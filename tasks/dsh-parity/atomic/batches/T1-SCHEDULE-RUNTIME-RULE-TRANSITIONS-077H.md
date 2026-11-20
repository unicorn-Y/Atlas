# T1-SCHEDULE-RUNTIME-RULE-TRANSITIONS-077H

Status: `DONE_SCOPED` for the pinned recurrence/transition test-source slice only.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:2372-2621`; 109 semantic units.
- Shape: 14 direct `it(...)` declarations and two `it.each(...)` declarations with four data rows (18 variants).
- Depends on zone/search map 077G.

Four capability groups record time precision and refresh merge; ending-task and recurrence choice transitions; complete timing-update payload and explicit failure copy; and recurrence option order/Monday-Friday weekday persistence. Three partial interaction edges connect the assertions to catalog refresh, timing update results and recurrence state.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":109,"mapped":109,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":14,"it_each":2,"unresolved_before":409154}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.31s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.89s
```

These are audit-tool tests only; no DSH or Atlas UI execution occurred.

## Remaining obligations

- Global source ledger after this slice: 413,747 total / 409,045 unresolved.
- Remaining recurrence, card, DSH execution and Atlas parity/superiority remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-RUNTIME-RULE-TRANSITIONS-077H.md`.
