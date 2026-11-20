# T1-SCHEDULE-TIMING-PICKERS-BASELINE-114

## Scope

Dependency: T1-SCHEDULE-TIMING-PICKERS-077P's source map of 87 clock/calendar picker behavior units.

Files read or run:

- `D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx`
- this report
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`

The DSH checkout was not modified. Verified commit: `d743267388641bc76f17c45ce8b4c231aed1d32c`. The pinned test file SHA-256 is `4aae9ebd778cc7bca23d1c696aa8a5f1598514dba2aad5fd815e68633f0ab97e`.

## Verification

```text
& .\node_modules\.bin\vitest.cmd run packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx
RUN  v4.1.11 D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness
Test Files  1 passed (1)
Tests  272 passed (272)
Duration  16.64s (transform 2.29s, setup 54ms, import 3.56s, tests 11.82s, environment 990ms)
VITEST_EXIT_CODE=0
process exit code: 0
```

Vitest emitted three repeated `vite-tsconfig-paths` deprecation notices. The DSH test/source paths were clean in the post-run scoped `git status` check.

## Limits / next

This is a pinned upstream automated baseline only. It does not prove Atlas picker behavior, browser-visible interaction, CSS/layout parity, or superiority. Next: map the actual DSH production clock/calendar helpers and styling and start the Atlas counterpart against those semantics. Global source inventory and the superiority gates remain open.
