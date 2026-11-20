# T1-ATLAS-TOOLTIP-CLICK-WITHDRAW-128 — Click dismissal while focused

Status: `DONE_SCOPED` for the ordered click/focus/hover behavior.

## Batch contract

- **Depends on:** pinned DSH Tooltip click-withdrawal and re-hover cases; Atlas T1-121 focus channel and T1-127 default hover timing.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`; production code was not changed because the sequence passed once the test dispatched the native pointer-out boundary.
- **Acceptance:** a hovered and keyboard-focused unpinned tooltip closes on anchor click, remains closed after mouse/pointer leave, and opens again on a fresh pointer hover.

## Verification

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 16 passed (16); Duration 992ms`, exit 0. The test uses fake timers and dispatches both mouseout and the pointerout event React/Radix use to reset the pointer-hover trigger before fresh hover. An earlier draft used a non-bubbling pointerleave event and failed to reset Radix's internal pointer-move gate; that was a test-event mismatch, not a product failure, and the final test uses pointerout.

`npx tsc --noEmit -p tsconfig.renderer.json` and scoped `git diff --check` exited 0.

## Remaining obligations

Happy-dom event evidence only; real desktop/browser click ordering and all Tooltip consumer routes remain open. No parity/superiority claim.

## Rollback boundary

If rejected, remove only the click/withdraw/re-hover test. No production source change was made.
