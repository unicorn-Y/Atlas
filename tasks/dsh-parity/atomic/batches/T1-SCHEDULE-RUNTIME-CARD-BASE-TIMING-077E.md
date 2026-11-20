# T1-SCHEDULE-RUNTIME-CARD-BASE-TIMING-077E

Status: `DONE_SCOPED` for the pinned TaskDetail rule-header/runtime-card source slice only.

## Scope and behavior

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:1622-1871`, 110 semantic units.
- Test declarations: 13 direct `it(...)` plus one `it.each(...)` with two locale rows (15 variants).
- Depends on 077D Task manager detail source mapping.

Six groups map (1) heading/compact next-run/deletion-only overflow, (2) aligned interval-row control, (3) overflow Escape/focus restoration, (4) Repeat Escape without closing detail, (5) one-shot date/time edits and payload fidelity, and (6) interval choices/display units/submission in seconds. Three partial interaction edges point to header controls, menu/focus primitives and timing serialization.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":110,"decisions":110,"mapped":110,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":13,"it_each":1,"unresolved_before":409470}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.80s
```

No DSH test or Atlas UI/runtime execution occurred.

## Remaining obligations

- Global source ledger: 413,747 total / 409,360 unresolved after these 110 source mappings.
- Remaining runtime-card scenarios, DSH execution and Atlas parity/superiority remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-RUNTIME-CARD-BASE-TIMING-077E.md`.
