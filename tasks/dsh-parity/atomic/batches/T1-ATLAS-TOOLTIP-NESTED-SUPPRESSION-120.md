# T1-ATLAS-TOOLTIP-NESTED-SUPPRESSION-120 — Nested tooltip visibility ownership

Status: `DONE_SCOPED` for nested suppression and restoration.

## Batch contract

- **Depends on:** pinned DSH `TooltipSuppression` behavior; Atlas `Tip` pin state from T1-118 and configurable content from T1-119.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** when a nested tooltip becomes visible, hide its still-open parent; when nested tooltip closes/unmounts, restore parent if its own trigger remains active; clicking a descendant must not toggle the parent's click-pin state; non-nested behavior stays green.

## Implementation

Added a suppression context. Each visible `Tip` informs its enclosing tooltip; the child reports inactive on close or unmount. The parent preserves its own pinned/hover state while suppressing only its visible content, so it can reappear when the nested tooltip closes. The click handler now toggles only when the pointer event targets the current anchor itself; a click on a nested child no longer bubbles into the parent's pin toggle.

## Verification

The test was first corrected to exercise a nested tooltip in the parent's actual anchor subtree (rather than incorrectly placing it inside the parent's label). With the production event-target guard but before suppression, the happy-dom test failed at the intended assertion: two `data-state="instant-open"` panels were visible instead of one; exit 1.

After adding suppression:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 5 passed (5); Duration 854ms`, exit 0. The nested case verifies inner-only visibility and restoration of the still-pinned parent after inner toggle-close.

```text
npx tsc --noEmit -p tsconfig.renderer.json
```

Actual result: exit 0, no TypeScript diagnostics. Scoped `git diff --check` exited 0.

## Remaining obligations

- Focus-delay/pointer modality, custom placement flip and clipping behavior, optional portal, comprehensive child ref/handler chaining, other DSH consumers, visible desktop and full parity remain open.
- This is a focused DOM test, not a full app/Electron run and not a superiority claim.

## Rollback boundary

If rejected, revert only nested suppression and descendant click targeting in the two Tooltip code/test files. Preserve T1-118/119 behaviors and their dependency.
