# T1-ATLAS-TOOLTIP-ANCHOR-COMPOSITION-123 — Child ref and handler composition

Status: `DONE_SCOPED` for the existing Radix/React anchor-composition path.

## Batch contract

- **Depends on:** pinned DSH anchor ref and child-handler composition contract; Atlas `Tip` focus/pointer/pin behavior and Radix `Trigger asChild` composition.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`. `Tooltip.tsx` was inspected but not changed because the exercised ref and handlers already compose through React cloning and Radix Slot.
- **Acceptance:** the caller's button ref points at the rendered native trigger; caller focus, blur, click and mouse-leave callbacks each run once while tooltip behavior remains mounted.

## Verification

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 10 passed (10); Duration 853ms`, exit 0. The new happy-dom case asserts the exact native button ref and all four caller callbacks. This batch establishes only the tested anchor contract; it does not prove every React ref shape, callback-ref cleanup convention or every consumer integration.

## Remaining obligations

Focus cancellation on all DSH cancellation boundaries, native browser ref behavior, portal clipping and other tooltip consumers remain open. No full browser/Electron parity or superiority claim.

## Rollback boundary

If the test is later superseded, remove only the added composition assertion/import. No production source change was required in this batch.
