# T1-SCHEDULE-SAVED-HISTORY-077C

Status: `DONE_SCOPED` for the `saved-history task binding` source slice only.

## Scope and mapped behavior

- Pinned DSH checkout: `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`, head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:1176-1258`, 28 semantic units.
- Four `it.each(...)` declarations contain 9 parameter rows total: two locales for saved prompt, two for absent saved prompt, success/rejection for old-task completion, and Rules/close/unmount for a late failure after leaving Records.
- Dependencies: TaskManagerPage harness map 077A and catalog behavior map 077B.

The cases cover saved run prompt versus current instruction; rendering an HTML-looking saved prompt as text; no fallback or empty record content when prompt is absent; suppressing old-task success/error after selection changes; and ignoring pending history errors after leaving Records or unmounting.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":28,"decisions":28,"mapped":28,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":0,"it_each":4,"global_unresolved_before":409666}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.85s
```

The DSH suite and Atlas runtime were not executed. This is not an implementation parity result.

## Remaining obligations

- Global source ledger after this mapping: 413,747 total / 409,638 unresolved.
- Task detail scenarios, DSH execution, Atlas history runtime and superiority remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-SAVED-HISTORY-077C.md`.
