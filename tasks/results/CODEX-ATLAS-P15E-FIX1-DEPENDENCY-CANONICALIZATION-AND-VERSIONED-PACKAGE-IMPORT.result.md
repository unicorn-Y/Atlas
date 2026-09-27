# CODEX-ATLAS-P15E-FIX1 Result

BASE_HEAD: `6dd1a3d24bed0286a7b34b72089b14a2d5636345`
SCOPE: Bounded P15E rework only

## Delivered

- Skill dependencies now share one canonical `{kind, name, requested}` representation across structured mappings, named constraints, legacy requirements, package comparison, Registry metadata, preflight, and activation.
- Package review distinguishes new imports, exact name/version conflicts, and same-name version update candidates. Exact versions remain protected from overwrite.
- Same-name version updates and downgrades use the existing lifecycle decision, server-issued one-time approval, acquisition hash, and current hash binding. Failed updates preserve the installed Registry entry and files.
- Skill Center displays the three package states and sends update candidates through the existing lifecycle update route.

## Validation

- P15A-P15E regression modules: **154 passed**.
- Frontend tests: **15 passed**.
- Production build: **passed** (existing Vite chunk-size warning remains).
- Ruff on changed Python files: **passed**.
- `git diff --check`: **passed**.
- Isolated package HTTP/API smoke via `httpx.ASGITransport` and temporary Registry/skills directories: **passed**. Covered dependency preflight and activation, exact-version conflict protection, approved update and downgrade, approval replay/retarget rejection, and failed-update preservation.

## Boundary

P15E remains subject to its separate review. P16 and E01-E04 were not started.
