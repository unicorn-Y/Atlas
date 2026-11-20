# T1-ATLAS-TOOLTIP-DEFAULT-DELAY-127 — DSH zero-delay hover default

Status: `DONE_SCOPED` for the shared TooltipProvider default and explicit per-tip override.

## Batch contract

- **Depends on:** pinned DSH `Tooltip` default `delayMs=0`; Atlas shared `TooltipProvider` and T1-119 per-tip hover delay.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.tsx`, `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** default pointer hover becomes visible after only Radix's initial zero-millisecond timer; explicit `delayMs={80}` still honors the 79/80ms boundary; all existing Tooltip cases remain green.

## Implementation

Changed the shared Radix provider's `delayDuration` and `skipDelayDuration` from 400/150ms to 0/0ms. This applies to every current `TooltipProvider` consumer, matching DSH's default hover delay. Per-tip `delayMs` still overrides the shared default. Radix schedules the very first open through a zero-duration timer, so the DOM test flushes that timer at 0ms rather than requiring it in the same pointer event stack.

## Verification

Valid red before changing the provider: the default-hover assertion found no `.pop` after the pointer event with Atlas's former 400ms provider delay (exit 1).

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 15 passed (15); Duration 971ms`, exit 0. This includes the explicit 79/80ms per-tip override.

```text
npx tsc --noEmit -p tsconfig.renderer.json
```

Actual result: exit 0, no diagnostics.

## Remaining obligations

This changes the default timing for all App consumers and has only focused happy-dom validation; no full desktop visual/accessibility session was run. The first open is scheduled at 0ms by Radix rather than synchronously. No global parity or superiority claim.

## Rollback boundary

If consumer behavior is rejected after visual review, restore provider defaults while preserving per-tip delay support and tests. No other source files were changed.
