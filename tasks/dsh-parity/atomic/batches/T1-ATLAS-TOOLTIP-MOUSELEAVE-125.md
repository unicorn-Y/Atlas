# T1-ATLAS-TOOLTIP-MOUSELEAVE-125 — Source-aligned dismissal on pointer leave

Status: `DONE_SCOPED` for unpinned mouse-leave dismissal and click-pin persistence.

## Batch contract

- **Depends on:** pinned DSH `Tooltip.tsx` mouseleave handler; Atlas T1-121 keyboard-focus state and T1-118 click-pin behavior.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, the T1-121 receipt correction, this receipt and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** mouse leave cancels pending focus and immediately withdraws an unpinned bubble even if the anchor retains focus; a click-pinned bubble remains visible when the pointer leaves.

## Implementation

The tooltip's mouse-leave handler now clears pending focus, hover and focus visibility when not click-pinned. A pinned bubble is retained. This corrects the T1-121 test that had asserted the opposite behavior; the T1-121 receipt now labels its earlier 8-test result as a superseded snapshot rather than final semantic acceptance.

## Verification

Before the source fix, the source-aligned test failed because the unpinned bubble remained open after mouse leave while focus was retained; exit 1, `1 failed, 12 passed`.

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result after the fix: `Test Files 1 passed (1); Tests 13 passed (13); Duration 973ms`, exit 0. `npx tsc --noEmit -p tsconfig.renderer.json` and scoped `git diff --check` exited 0.

## Remaining obligations

Evidence is happy-dom only. Real browser modality, the full shared tooltip-consumer set and other DSH Tooltip geometry remain open. No parity/superiority claim.

## Rollback boundary

If rejected, revert only the unpinned mouse-leave visibility reset and its source-aligned tests; retain the independent focus timer and click-pinned behavior.
