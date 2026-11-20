# T1-ATLAS-TOOLTIP-UNPIN-129 — Retire pin state when click mode is removed

Status: `DONE_SCOPED` for the `openOnClick` prop transition.

## Batch contract

- **Depends on:** pinned DSH Tooltip `drops a click pin when disabled or when click opening is removed`; Atlas T1-118 click-pin and T1-125 mouse-leave semantics.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** after a pin, removing `openOnClick` retires pin state; mouse leave closes the remaining unpinned hover state; reenabling click mode and clicking pins again; the native trigger node is not remounted.

## Implementation

The existing effect already cleared pin/hover state on `disabled`. It now also clears `pinned` when `openOnClick` becomes false. The `Tip` and anchor remain mounted; only state changes.

## Verification

Valid red with the source-aligned sequence: after toggling `openOnClick` off, mouse-leaving and restoring it, the next click left `.pop` closed because stale `pinned=true` caused the click to unpin. The first draft had over-asserted immediate disappearance while hover remained active; corrected to the upstream sequence before treating it as a product red.

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result after the fix: `Test Files 1 passed (1); Tests 17 passed (17); Duration 939ms`, exit 0. The test checks the same button identity across both prop transitions.

```text
npx tsc --noEmit -p tsconfig.renderer.json
git diff --check -- frontend/src/renderer/ui/Tooltip.tsx frontend/src/renderer/ui/Tooltip.test.tsx
```

Both exited 0.

## Remaining obligations

Happy-dom only; DSH Tooltip consumer routes, browser pin/focus behavior and full global parity remain open.

## Rollback boundary

If rejected, revert the `openOnClick` transition reset and its test only; preserve disabled reset and prior Tooltip behavior.
