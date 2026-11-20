# T1-ATLAS-TOOLTIP-ESCAPE-131 — Escape dismissal for hover/focus and pinned states

Status: `DONE_SCOPED` for visible-tooltip Escape propagation and dismissal.

## Batch contract

- **Depends on:** pinned DSH Tooltip `shows informational tooltips on hover and focus, and consumes Escape only while open`; Atlas T1-130 independent trigger state.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** while a non-pinned focus tooltip is visible, Escape closes it, prevents default and stops bubbling; a second Escape after closure bubbles normally. Existing pinned Escape/Tab/outside dismissal stays green.

## Implementation

Moved keyboard dismissal into a visible-state capture listener instead of installing it only for click-pinned tips. Escape now clears pinned, hover, focus and pending timer state and prevents/stops the event. Tab still dismisses only click-pinned tooltips and continues to propagate. Outside pointer dismissal also clears all trigger state for a pinned tip.

## Verification

Before the fix, the DSH-aligned red test showed that an open unpinned tooltip let Escape reach the parent `onKeyDown` callback despite Radix setting `defaultPrevented`; exit 1.

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 19 passed (19); Duration 942ms`, exit 0. Renderer TypeScript and scoped `git diff --check` exited 0.

## Remaining obligations

Happy-dom only; real browser event ordering and other component families remain open. No global parity/superiority claim.

## Rollback boundary

If rejected, revert the visible-state keydown listener and its focused test only. Preserve existing outside pin dismissal and earlier trigger timing.
