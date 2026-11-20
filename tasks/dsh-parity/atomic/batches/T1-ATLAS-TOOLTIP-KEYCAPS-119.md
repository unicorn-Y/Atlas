# T1-ATLAS-TOOLTIP-KEYCAPS-119 — Tooltip keycaps, lazy labels and fit controls

Status: `DONE_SCOPED` for the selected DSH Tooltip options, on top of T1-118 pin/dismiss behavior.

## Batch contract

- **Depends on:** pinned DSH `Tooltip.tsx` and `ShortcutKeys.tsx`; T1-118 Atlas `Tip` click-pin behavior and happy-dom test environment.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** label resolver is not called while hidden; visible tooltip renders supplied shortcut keys and accessible description; per-tip hover delay overrides provider delay; max-width, alignment and gap are passed through; existing pin/dismiss/disabled tests remain green.

## Implementation

`Tip` now accepts a string/ReactNode or lazy label resolver, `shortcutKeys`, `delayMs`, `maxWidth`, `align`, and `gap`. Resolver evaluation is limited to open state. Shortcut keys render as keycaps, while Radix's `aria-describedby` text combines the resolved label and shortcut sequence. `delayMs` is per-root and falls back to the existing provider default when omitted. Existing geometry defaults are preserved (`bottom`, `center`, 6px gap); max width is optional.

## Verification

Valid red before implementation:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `1 failed, 2 passed`, exit 1. The test showed the lazy resolver returned as a React child rather than resolved text.

After implementation:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 4 passed (4); Duration 817ms`, exit 0. Tests cover hidden/visible resolver calls, keycaps and accessible description, max-width, 79/80ms hover-delay boundary, pin toggle, Escape/Tab/outside dismissal, and disabling while open.

```text
npx tsc --noEmit -p tsconfig.renderer.json
```

Actual result: exit 0, no TypeScript diagnostics. `git diff --check` scoped to the two Tooltip files exited 0.

## Remaining obligations

- DSH `focusDelayMs`, pointer-modality handling, nested tooltip suppression, optional non-portal rendering, anchor child ref/handler chaining under all child types, and exact side-flip/clipping behavior are not closed here.
- No full browser/Electron session or every Tooltip consumer was exercised. Global source inventory, parity and superiority remain incomplete.

## Rollback boundary

If rejected, revert only the selected option support and tests from the two listed Tooltip files. Preserve T1-118 click pin/disabled behavior and its dev test environment dependency.
