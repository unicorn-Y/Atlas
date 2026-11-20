# T1-SCHEDULE-PAGE-CATALOG-TESTS-077B

Status: `DONE_SCOPED` for the pinned TaskManagerPage catalog test-source block only. No DSH tests or Atlas UI were executed.

## Scope

- Pinned DSH checkout: `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`, head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source slice: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:615-1175`, `describe('Task manager catalog')`.
- 268 indexed semantic units, 20 direct `it(...)` declarations and four `it.each(...)` declarations spanning ten parameter rows (30 case variants total).
- Depends on 077A test harness map and TaskDetail source map 075. The DSH checkout is read-only.

## Test obligations mapped

1. Starts a Session instead of showing a page creation form.
2. Uses the mock content column, heading, search and rows layout.
3. Lists cross-session active records by target time without unsupported actions.
4. Uses stored task titles for list rows and selected detail.
5. Uses shared exact frequency units in list and detail.
6. States row frequency/next time without exposing its Session.
7. Updates remaining-time text as the clock advances.
8. Formats remaining time in each locale.
9. Searches complete instruction and Session ID case-insensitively.
10. Matches stored task name/instruction without exposing Session label.
11. Combines search and status filter and clears no-match state.
12. Clears a status-only exclusion from its filter group.
13. Distinguishes empty, loading and failed catalog reads.
14. Keeps prior rows during a later loading/error state.
15. Opens Rules for the selected task and separates rule fields from deliveries.
16. Hides task name/next-run on Delivery records and restores them on Rules.
17. Loads history independently of catalog loading/failure.
18. Moves tab focus with arrows/Home/End without intercepting Tab.
19. Resets to Rules after changing task or reopening closed details.
20. Keeps Rules and deletion usable when the original Session is unavailable.

The six capability groups and three `PARTIAL` source edges link these assertions to the page component, timing helpers and Session state. They document contracts, not execution.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":268,"decisions":268,"mapped":268,"duplicate_decision_ids":0,"missing_units":0,"missing_refs":0,"direct_it_declarations":20,"it_each_declarations":4,"it_each_rows":10,"executed_variants":30,"unresolved_before":409934}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.31s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.73s
```

These tests validate ledger tooling only. Neither the 20 DSH cases nor Atlas frontend behavior were executed.

## Remaining obligations

- Global source ledger: 413,747 total / 409,666 unresolved after this 268-unit mapping.
- Saved-history, task details, remaining page scenarios, DSH execution and Atlas parity/superiority remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-PAGE-CATALOG-TESTS-077B.md`.
