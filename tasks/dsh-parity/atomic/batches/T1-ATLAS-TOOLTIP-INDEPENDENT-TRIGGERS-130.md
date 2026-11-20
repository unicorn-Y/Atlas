# T1-ATLAS-TOOLTIP-INDEPENDENT-TRIGGERS-130 — Own hover and focus timing independently

Status: `DONE_SCOPED` for independent pointer-hover and keyboard-focus timers.

## Batch contract

- **Depends on:** pinned DSH Tooltip `delayMs`/`focusDelayMs` and cancellation cases; Atlas T1-121 focus modality and T1-127 default delay.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** delayed pointer hover is owned by Tip; keyboard focus opens at its independent delay and cancels the pending hover timer; blur after focus cannot let the old hover timer reopen the bubble; explicit hover delays and 0ms default remain correct.

## Implementation

Added a Tip-owned hover timer/active-pointer state alongside its existing focus timer. Trigger pointer move/leave handlers are chained and prevent Radix's internal shared hover delay from opening a second timer. The Tip applies `delayMs ?? 0` for hover, skips touch pointer movement, and cancels the hover timer on focus, click, pointer/mouse leave, disable and unmount. Keyboard focus uses its independent timer and can preserve the active hover state until pointer leave.

## Verification

Before the source change, the DSH combined timing test failed: after pointer hover scheduled a 500ms wait and keyboard focus opened immediately, `vi.getTimerCount()` remained 2 instead of returning to the initial count. The independent-focus path did not retire Radix's pending hover timer.

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result after the fix: `Test Files 1 passed (1); Tests 18 passed (18); Duration 954ms`, exit 0. The test flushes Radix's own zero-duration provider bookkeeping at 0ms before asserting the long hover timer was canceled; after blur, advancing the old delay does not reopen the panel. Explicit hover 79/80ms, default 0ms, click pin, focus, pointer modality, leave and nested cases remain in the same test file.

```text
npx tsc --noEmit -p tsconfig.renderer.json
git diff --check -- frontend/src/renderer/ui/Tooltip.tsx frontend/src/renderer/ui/Tooltip.test.tsx
```

Both exited 0.

## Remaining obligations

Happy-dom only; no real browser pointer/focus ordering or full App consumer review. Tooltip fit/flip, portal-default migration and other DSH component families remain open. No global parity/superiority claim.

## Rollback boundary

If rejected, revert only Tip-owned hover timer/state and pointer event interception in the two Tooltip files. Preserve independent focus/pin behavior and preceding batches.
