# T1-ATLAS-TOOLTIP-PIN-DELAY-126 — Delayed-hover/pin dismissal interaction

Status: `DONE_SCOPED` for the tested delayed-hover and click-pin sequence.

## Batch contract

- **Depends on:** pinned DSH Tooltip delayed-hover/pin interaction; Atlas Radix delay and T1-118 pin behavior.
- **Files changed:** `frontend/src/renderer/ui/Tooltip.test.tsx`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`; production code was not changed because the sequence already behaved correctly.
- **Acceptance:** a delayed pointer hover does not open early; clicking pins immediately; mouse leave retains the pin; Escape dismisses it; expiry of the preexisting hover delay does not reopen it.

## Verification

```text
npm test -- src/renderer/ui/Tooltip.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 14 passed (14); Duration 1.06s`, exit 0. This verifies the ordered interaction in happy-dom using fake timers. It does not exercise real pointer movement or browser timing.

## Remaining obligations

Default hover timing, actual browser input, fit/flip/clipping and all consumer routes remain separate. No global parity or superiority claim.

## Rollback boundary

If rejected, remove only the new delayed-hover/pin interaction test; no production source change was made.
