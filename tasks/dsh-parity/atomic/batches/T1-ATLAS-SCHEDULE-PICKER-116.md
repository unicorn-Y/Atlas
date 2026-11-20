# T1-ATLAS-SCHEDULE-PICKER-116 — Atlas calendar and time control

Status: `DONE_SCOPED` for the shared picker implementation and its two form integrations. This is not a claim of visual/browser parity, full schedule parity, global source closure, or superiority.

## Batch contract

- **Depends on:** pinned DSH `d743267388641bc76f17c45ce8b4c231aed1d32c`; schedule picker behavior map and CSS semantic coverage from T1-115.
- **Files changed:** `frontend/src/renderer/components/DateTimePicker.tsx`, `frontend/src/renderer/components/DateTimePicker.test.tsx`, `frontend/src/renderer/pages/AutomationPage.tsx`, `frontend/src/renderer/components/settings/RemoteTasksPanel.tsx`, this receipt, and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- **Acceptance:** Monday-first calendar, month navigation, date selection, local `YYYY-MM-DDTHH:mm` value, hour/minute columns, keyboard movement, Escape dismissal, required/optional form behavior, unchanged API payload semantics, focused component tests and renderer TS check.

## Implementation

Added a shared picker with a Monday-first month grid, bounded month navigation, date selection, hours 00–23 and minutes 00–59, arrow-key movement, Escape close/focus return, outside-pointer dismissal, selected/today states, and an accessible dialog/grid/listbox structure. A hidden native `datetime-local` control preserves required validation for the automation one-shot trigger. Empty optional remote schedules remain empty until a date is selected; the chosen time begins at midnight.

`AutomationPage` uses the picker for its required one-shot date trigger and still submits `trigger.at = form.at`. `RemoteTasksPanel` uses it for an optional run time and retains the existing `new Date(schedule).toISOString()` conversion and request fields. No API/backend changes were made.

## Verification

Red before the hour/minute columns were added:

```text
npm test -- src/renderer/components/DateTimePicker.test.tsx
```

Actual result: `1 failed, 2 passed`, exit 1. The test reached the intended missing-clock-column assertion (`17点` option absent).

Final focused test:

```text
npm test -- src/renderer/components/DateTimePicker.test.tsx
```

Actual result: `Test Files 1 passed (1); Tests 3 passed (3); Duration 338ms`, exit 0. Vite printed its existing config/esbuild deprecation warnings.

Renderer type check:

```text
npx tsc --noEmit -p tsconfig.renderer.json
```

Actual result: exit 0, no TypeScript diagnostics.

`git diff --check` on the four implementation/test files exited 0. A source contract probe confirmed both production forms use `DateTimePicker`; automation still sends `form.at`; remote tasks still convert the local schedule to UTC ISO; no `datetime-local` control remains in those two forms except the picker’s required-validation input.

## Remaining obligations

- No browser-visible or desktop-runtime interaction was performed in this batch. Calendar geometry, actual focus behavior, screen-reader behavior, host locale rendering, and full form submission in a running app remain unverified.
- The DSH task-page style rules, shared picker primitive implementations/consumers, and remaining 171 semantic units in the prior picker slice remain open.
- The global source inventory and every cross-runtime DSH obligation remain incomplete; no superiority claim is made.

## Rollback boundary

If this batch is rejected, only revert the four files listed under Files changed that contain implementation/test edits. Preserve all earlier DSH inventory, attempt-isolation, ledger, and unrelated dirty work.
