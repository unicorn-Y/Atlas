# T1-SCHEDULE-TASK-MANAGER-DETAILS-077D

Status: `DONE_SCOPED` for Task manager details test-source obligations only.

## Scope and case accounting

- Pinned source: `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`, head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- File slice: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:1259-1621`, 168 semantic units.
- Contains 14 direct `it(...)` declarations and four `it.each(...)` declarations with eight data rows (22 case variants total).
- Dependency: saved-history source map 077C.

## Exact behavior groups

- Selected detail remains stable as authoritative catalog state marks a task inactive or filters its row; ended tasks without receipts do not gain invented receipt/next-run values.
- Same-task refresh preserves Delivery history and updates the latest receipt independently from the next target.
- Linked Session label/navigation stays distinct from scrolling and destructive controls; Session ID is fallback when a title or original Session is absent; query loading/retry stays in selected detail.
- Keyboard focus, full-instruction visibility, close/Escape, nested dropdown Escape ownership and focus recovery.
- Injected locale changes labels without translating saved data; next-run displays the device zone; row icon has the requested glyph while decorative glyph remains non-semantic.

Four `PARTIAL` interaction edges connect the test block to the page, saved history, Session state and focus/keyboard controls. These edges describe assertions, not successful execution.

## Integrity and ledger test evidence

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":168,"decisions":168,"mapped":168,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":14,"it_each":4,"global_unresolved_before":409638}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.31s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.87s
```

The DSH tests and Atlas frontend were not executed. No runtime parity is claimed.

## Remaining obligations

- Global source ledger after this mapping: 413,747 total / 409,470 unresolved.
- Remaining TaskDetail page tests, DSH execution, Atlas UI and cross-component superiority remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-TASK-MANAGER-DETAILS-077D.md`.
