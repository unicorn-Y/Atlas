# T1-SCHEDULE-PAGE-TEST-HARNESS-077A

Status: `DONE_SCOPED` for TaskManagerPage test harness and linked-session tests at lines 1–614. This is source mapping only.

## Scope

- Pinned DSH: `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`, head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source slice: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:1-614`; 211 semantic units, three direct `it(...)` declarations, and one `it.each(...)` declaration with five rows (eight executed variants total).
- Dependencies: TaskDetail production map 075 and TaskDetail test-source map 076. No DSH checkout source was modified.

## Mapped contract groups

Six groups cover fixture defaults; cleanup/timezone/frozen-clock setup; the mounted page owner; semantic DOM and layout queries; timing/rule/save/delete interactions; and the remote catalog plus linked-session UI behavior. The last group maps the three actual cases: linked-session label with/without a catalog title and navigation updates as session metadata/archive state changes.

The ledger includes edges from the test harness to TaskManagerPage, Session/workspace state and timing controls. These are partial test-source edges, not runtime proof.

## Evidence

Bounded integrity check against the pinned source:

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":211,"decisions":211,"mapped":211,"duplicate_decision_ids":0,"missing_source_units":0,"missing_refs":0,"direct_it_declarations":3,"it_each_declarations":1,"it_each_rows":5,"executed_variants":8,"global_total":413747,"global_unresolved_before":410145}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.31s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.78s
```

The DSH test suite and Atlas UI were not run. No runtime parity or superiority is claimed.

## Remaining obligations

- Global source ledger: 413,747 total / 409,934 unresolved after applying these 211 mappings.
- Remaining TaskManagerPage scenarios, DSH/Atlas execution, CSS and full cross-component coverage remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-PAGE-TEST-HARNESS-077A.md`.
