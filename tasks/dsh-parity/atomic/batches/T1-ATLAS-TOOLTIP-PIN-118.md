# T1-ATLAS-TOOLTIP-PIN-118 — Click-pinned informational tooltips

Status: `DONE_SCOPED` for click-pin, dismissal, and disabled behavior using the existing Radix tooltip. Remaining DSH Tooltip capabilities are still open.

## Batch contract

- **Depends on:** pinned DSH `Tooltip.tsx` behavior map; Atlas existing Radix tooltip wrapper.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, new `frontend/src/renderer/ui/Tooltip.test.tsx`, `frontend/package.json`, root `package-lock.json`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** pin informational tooltip by click; second click toggles it; Escape, Tab, and outside pointer dismiss; `aria-describedby` follows visibility; disabled suppresses an open hint; default uncontrolled Radix hover behavior remains the existing path; renderer typecheck passes.

## Implementation

Extended `Tip` with optional `openOnClick` and `disabled`. Existing calls retain the unchanged uncontrolled Radix path. Pinned tips use controlled Radix open state; a second click unpins. While pinned, capture-phase keyboard dismissal handles Escape/Tab and document pointerdown closes only when the target is outside both trigger and portaled content. A disabled hint is hidden immediately and pending pin state is cleared. Radix continues to provide portal content and active `aria-describedby` wiring.

The current test environment had no DOM package. Added `happy-dom` as a frontend dev dependency and a file-local Vitest environment directive for actual DOM/portal behavior. `npm install --workspace @atlas/frontend --save-dev happy-dom` completed with `added 6 packages, removed 55 packages, changed 4 packages`; the package manifest and lockfile diff contain only the `happy-dom` entry and its lock entries. npm reported 41 audit findings (5 low, 11 moderate, 24 high, 1 critical); no audit fix was run.

## Verification

Initial ReactTestRenderer attempt was an environment failure, not product evidence: `2 failed` because `window` was undefined in Radix's DOM event wrapper. It was replaced with the actual DOM test harness before interpreting red/green.

Valid happy-dom red:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `2 failed`, exit 1. Both tests reached the missing click-pin behavior: the tooltip was absent after the click.

Green:

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 2 passed (2); Duration 843ms`, exit 0.

```text
npx tsc --noEmit -p tsconfig.renderer.json
```

Actual result: exit 0, no TypeScript diagnostics. `git diff --check` on Tooltip source/test and package manifests exited 0.

## Remaining obligations

- DSH Tooltip shortcut keycaps, lazy label resolver, custom hover/focus delays, maximum-width and flip fitting, child ref/handler chaining under all component types, nested tooltip suppression, and pointer-modality-specific behavior have not been closed by this batch.
- No full Electron/browser runtime was used. All other DSH consumer families and global source/superiority obligations remain open.

## Rollback boundary

If this batch is rejected, revert only the two Tooltip files and this batch's isolated `happy-dom` manifest/lock entries. Preserve all previous picker, anchoring, task-parity, and unrelated work.
