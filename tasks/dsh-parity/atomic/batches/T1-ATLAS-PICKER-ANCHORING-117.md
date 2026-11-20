# T1-ATLAS-PICKER-ANCHORING-117 — Anchored portal behavior for Atlas schedule picker

Status: `DONE_SCOPED` for source-guided positioning/dismissal logic and pure/component unit evidence. Real-browser viewport behavior remains unverified.

## Batch contract

- **Depends on:** T1-115's pinned DSH primitive/source slice and T1-116's shared Atlas date/time picker.
- **Files changed:** `frontend/src/renderer/components/DateTimePicker.tsx`, `frontend/src/renderer/components/DateTimePicker.test.tsx`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** Fixed body portal; anchor coordinates clamped to viewport; resize, capture-phase nested scroll and panel size changes trigger remeasurement; trigger and portal panel count as inside for pointer dismissal; Escape closes and restores trigger focus; test geometry includes top/bottom and start/end and too-large panel bounds.

## Source evidence and change

Pinned DSH `useAnchoredPosition` measures anchor/panel rectangles, uses fixed viewport coordinates, clamps to margins, listens to capture-phase scroll and window resize, and observes panel size changes with `ResizeObserver`. `useDismissOnOutsidePointer` treats both the trigger root and an optional portaled panel as inside. The primitives are consumed by 9 production files across Tooltip, context meter, statistics dialog, job/plugin/model menus, schedule menus/picker, and document font notice. Atlas's new DateTimePicker had been using an in-tree absolute panel and did not account for nested scrolling or panel dimension changes.

The Atlas picker now portals to `document.body`, computes fixed coordinates from the trigger and panel boxes, clamps to 12px viewport margins, and remeasures on capture-phase scrolling, window resize, and `ResizeObserver`. Pointer dismissal checks both the trigger subtree and portal subtree. The geometry helper handles panels larger than the viewport by anchoring at the margin instead of yielding negative coordinates.

## Verification

Red for the missing anchoring and portal-target helpers:

```text
npm test -- src/renderer/components/DateTimePicker.test.tsx
```

Actual result: `2 failed, 3 passed`, exit 1. Both failures reached missing behavior: `computeAnchoredPosition` and `isInsidePopover` were not implemented.

After the change:

```text
npm test -- src/renderer/components/DateTimePicker.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 5 passed (5); Duration 353ms`, exit 0. Existing Vite config/esbuild warnings remain.

```text
npx tsc --noEmit -p tsconfig.renderer.json
```

Actual result: exit 0, no TypeScript diagnostics. `git diff --check` over the two code/test files exited 0.

## Remaining obligations

- No browser run measured actual portal coordinates, nested page scrolling, visual viewport behavior, screen-reader navigation, or `ResizeObserver` delivery. Unit geometry and source wiring are not live UI proof.
- This implements only the anchored primitive behavior used by the Atlas picker. It does not establish Atlas equivalents for all nine DSH consumers or close the remaining DSH primitive consumer source units.
- Full source closure, cross-runtime parity and superiority remain open.

## Rollback boundary

If rejected, revert only the anchoring/portal changes and associated tests in the two listed frontend files. Preserve T1-116's calendar/time implementation and all earlier work.
