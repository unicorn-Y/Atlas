# T1-ATLAS-TOOLTIP-PORTAL-122 — Optional in-tree tooltip content

Status: `DONE_SCOPED` for explicit in-tree and portal rendering modes.

## Batch contract

- **Depends on:** pinned DSH `Tooltip` portal contract and Atlas Radix `Tooltip.Root`/`Tooltip.Content` ownership.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** explicit `portal={false}` renders content in the tooltip trigger tree; default behavior remains portaled to preserve existing Atlas consumers; prior tooltip tests remain green.

## Implementation

Extracted the Radix content element once and render it through `T.Portal` only when requested. Added `portal?: boolean`, defaulting to `true` to preserve Atlas's previous always-portal behavior; `portal={false}` provides the DSH in-tree mode for consumers that can tolerate ancestor clipping/stacking contexts.

## Verification

Valid red before the source change: the test requested `portal={false}` but the content was absent from the trigger container because Atlas always used `T.Portal`.

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 9 passed (9); Duration 955ms`, exit 0. `npx tsc --noEmit -p tsconfig.renderer.json` and scoped `git diff --check` exited 0.

## Remaining obligations

The default remains Atlas-compatible portal mode and therefore differs from DSH's default `portal=false`; consumer-by-consumer default migration is not included. No full browser clipping, stacking-context or Electron verification. Complete child-ref/handler composition and other tooltip consumers remain open; no global parity/superiority claim.

## Rollback boundary

If rejected, revert only the `portal` prop/content branch and its focused test. Preserve prior Tooltip behaviors and reports.
