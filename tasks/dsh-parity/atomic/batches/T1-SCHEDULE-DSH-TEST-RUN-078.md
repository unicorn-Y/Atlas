# T1-SCHEDULE-DSH-TEST-RUN-078

Status: `DONE_SCOPED` for the exact pinned DSH TaskManagerPage test execution.

## Scope

- Read-only DSH checkout: `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`, pinned head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Executed only `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx`, which was source-mapped in batches 077A–077P.
- No DSH source was edited. The test file remained clean in `git status --short -- packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx`.

## Actual command and output

From the pinned DSH repo root:

```text
pnpm exec vitest run packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx --reporter=dot --no-file-parallelism
```

```text
RUN  v4.1.11 D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness

Test Files  1 passed (1)
      Tests  272 passed (272)
   Start at  11:37:11
   Duration  17.27s (transform 2.27s, setup 53ms, import 3.73s, tests 11.97s, environment 1.29s)
```

Vitest emitted three `vite-tsconfig-paths` migration notices. No install or snapshot update was run.

## Evidence boundary

This is an actual DSH unit/component test run. It does not exercise Atlas, prove Atlas parity, measure a real browser/electron session, or establish superiority. The source ledger remains 413,747 total / 408,217 unresolved and the TaskManagerPage capability comparisons remain open.
