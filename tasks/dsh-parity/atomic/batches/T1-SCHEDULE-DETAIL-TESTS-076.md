# T1-SCHEDULE-DETAIL-TESTS-076

Status: `DONE_SCOPED` for the pinned TaskDetail client-test source obligations only. This is a source map, not a test execution or Atlas parity result.

## Scope and dependency

- Pinned DSH checkout: `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`, head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-detail.client.spec.tsx`.
- Dependency: production behavior map `T1-SCHEDULE-TASK-DETAIL-075`.
- The queue had called this a 42-case suite. Direct source count finds 43 `it(...)` declarations; this report and subsequent queue entry use 43.

## Capability coverage

All 403 indexed semantic units are mapped to eight test-obligation groups:

| Group | Units | Covered behavior |
|---|---:|---|
| Test fixture/contracts | 90 | Catalog/Session/workspace fixtures, Remote callbacks, mount helpers and timing/menu test helpers |
| Refresh integration | 55 | Clean refresh, staged interval/kind, edited text, stale save response and failed refresh retry |
| Draft merge | 48 | Clean/newer records, kind transitions, field-level timing merge, weekly label/day consistency and remote rename |
| Menus/time zones | 58 | Initial weekday seed, outside-pointer dismissal, search focus and shared/partial zone selection |
| Weekday memory | 74 | Task-scoped seed, weekday retention across rule-kind detours, refresh retirement and cancel reset |
| Save generations | 18 | Deferred save while returning to a task and ignoring a response for a no-longer-current task |
| Interval/errors | 31 | Interval step/floor, empty-value floor and refusal/unknown-save feedback |
| Cron editor | 29 | Frequency/Time dismissal, committed occurrence seeding and current-shape no-op selection |

The ledger also records three test-source interaction edges to production, helper contracts and UI primitives. Each edge remains `PARTIAL`: an assertion's existence does not prove that pinned tests execute or that Atlas behaves equivalently.

## Integrity and test evidence

Bounded validation checked the pinned source digest, unit-to-decision coverage, duplicate IDs, dangling capability/edge references and the actual test declaration count:

```json
{"source_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","index_digest":"e50e2af8b804f8db1b58f93cb532641547c3c0e7343822c0ae5219366eedf4be","actual_digest":"e50e2af8b804f8db1b58f93cb532641547c3c0e7343822c0ae5219366eedf4be","digest_match":true,"source_units":403,"decisions":403,"mapped":403,"duplicate_decision_ids":0,"missing_source_units":0,"missing_refs":0,"actual_it_declarations":43}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.31s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.80s
```

This validates the Atlas ledger tooling, not the DSH test suite. The 43 DSH tests were not run. The full source AST scan was not retried; batch 074A records its TypeScript child failing at the approximately 4 GiB heap limit. No Atlas UI/runtime or real-model turn was exercised.

## Remaining scope

- The TaskManagerPage test suite, TaskDetail dependencies, CSS/default/style behavior, DSH test execution and Atlas runtime comparisons remain separate work.
- Global source ledger after this mapping: 413,747 units total, 410,145 unresolved. Task 1 remains open; no superiority claim is made.
