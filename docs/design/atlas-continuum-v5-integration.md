# Atlas Continuum · Electron/React integration preview

This is a **source integration**, not another standalone HTML mockup. It adds a
native `ContinuumView` to Atlas's renderer. It uses the existing Zustand store,
backend adapter, Run WebSocket lifecycle, input/approval actions, and device
control authority. It does not invent a new runtime or persist fake task data.

## Install against an Atlas checkout

```powershell
py install_continuum.py D:\Atlas --dry-run
py install_continuum.py D:\Atlas
cd D:\Atlas
npm ci
npm run dev
```

Open **Atlas ONE** from the classic sidebar. Within Continuum, **经典界面** returns
to the existing chat. No application backend files are modified.

The installer refuses an unknown or already-patched version of App.tsx or
Sidebar.tsx instead of applying a partial patch. It backs up both files as
`.tsx.continuum-bak` before writing. For Git users, `git diff` shows everything.

## Scope

- Real conversation selection and message send use `useAtlasStore`.
- Run lifecycle and live events are **not duplicated**: only state projection
  and UI actions are added; approvals, run pause/resume, and agent turns go
  through the existing adapter.
- Projects, scheduled goals, and automations are listed using their own REST
  endpoints. They are not assigned fake relation IDs.
- Memory is populated from `/api/facts`. No provenance is invented.
- Computer takeover uses the existing backend state machine and success report.
- Users can change attention without cancelling a Run.

## Current implementation limits

- Neither GitHub CI nor Windows Electron has been run by this environment;
  TSX syntax transpilation and installer fixture checks are performed locally.
- Does not replace the entire classic design; deep operations still link to the
  original views.
- Global Run enumeration across restarted processes is not solved by this UI:
  the live store only knows Runs loaded by the current client session.
- Goal/project/conversation relations are not synthesized from names or dates.
- Full rich Markdown, file attachments, terminal, browser recording and screen
  streaming stay in the classic view at this stage.
- Extra memory provenance and historically complete Run replay need backend work.

This preview is meant for a dedicated development branch / checkout and should
not be assumed to be production-ready before a Windows integration run.
## Source branch

This integration lives at `feature/continuum-native-v5-20261106`. Open `Atlas ONE` from the legacy sidebar; `main` is left unchanged.
