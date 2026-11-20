# T1-ATLAS-TOOLTIP-FOCUS-MODALITY-121 — Keyboard focus timing and pointer modality

Status: `DONE_SCOPED` for keyboard focus delay and pointer-driven focus suppression.

## Batch contract

- **Depends on:** pinned DSH `Tooltip.tsx` and its `input-modality.ts` pointer/keyboard signal; Atlas tooltip pin, delay, lazy-label and nested suppression work from T1-118 through T1-120.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** keyboard focus uses an independent `focusDelayMs`; pointer-origin focus does not open a focus-only tooltip; blur and mouse leave cancel a pending focus show; DSH's unpinned mouse-leave and click-pinned persistence semantics are preserved.

## Implementation

Added document-level last-input tracking for pointerdown and non-composing keydown. The tooltip now suppresses Radix's shared focus-delay path and owns a separate focus trigger/timer, while Radix continues to own hover state. Child focus, blur, click and mouse-leave handlers are chained. Blur/click/disable/unmount cancel pending focus timers.

## Verification

Before the implementation, the focus-delay and pointer-origin cases both failed because Radix opened the bubble immediately on focus. A later mouse-leave cancellation assertion also failed while the pending timer remained active.

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Initial actual result: `Test Files 1 passed (1); Tests 8 passed (8); Duration 935ms`, exit 0. A later source-to-test audit found that this first version's mouse-leave assertion contradicted DSH: it kept an unpinned bubble visible while focused. That assertion is superseded by T1-125, which adds the source-aligned unpinned-withdrawal and pinned-persistence checks and records a final 13-test pass.

```text
npx tsc --noEmit -p tsconfig.renderer.json
git diff --check -- frontend/src/renderer/ui/Tooltip.tsx frontend/src/renderer/ui/Tooltip.test.tsx
```

Both exited 0 for the initial 8-test snapshot. The mouse-leave behavior is corrected and reverified in T1-125.

## Remaining obligations

This is a focused happy-dom DOM test, not browser/Electron input evidence. DSH optional portal behavior, exact fit/flip/clip semantics, full child ref/handler contract and non-picker tooltip consumers remain open. No full tooltip parity or superiority claim.

## Rollback boundary

If rejected, revert only independent focus state, focus timer, pointer modality tracking and the new tests in the two Tooltip code/test files. Preserve T1-118 through T1-120 behavior and reports.
