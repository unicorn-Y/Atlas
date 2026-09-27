# CODEX-ATLAS-P15D-FIX1-APPROVAL-SCOPE-REGISTRY-CONFLICT Result

STATUS: IMPLEMENTED; VALIDATION PASSED
WORKER: Luna
BASE_BRANCH: main
BASE_HEAD: 392dcc2f564a7e9f24036e222ab893f22def0dad
IMPLEMENTATION_COMMIT: 01d1282c4eabbfdcc3ff2cc8151b28cdfd6bd148

## Delivered

- Added persistent, one-time server-side lifecycle decision records in the existing Skill Registry SQLite database. Lifecycle approval issuance now requires the exact unconsumed decision ID.
- Bound each approval to action, skill name, current version and hash, target content hash, acquisition ID, trust target, pin target, rollback event ID and snapshot hash, reason, creation/expiry, unique approval event ID, and one-time consumption. Lifecycle execution recomputes and compares its full applicable scope.
- Added an Electron-generated random Skill Center session token. The main process passes it to its backend child and exposes it only through a main-frame IPC handler for the Atlas file UI or configured local dev origin. Decision and approval minting require this token and a trusted UI origin; generic HTTP requests without the session token fail closed. Agent capabilities remain unable to mint or consume approvals.
- Bound rollback approvals to the exact source event and snapshot hash, then rechecked the current skill hash under the lifecycle lock before changing files.
- Removed Registry `ON CONFLICT DO UPDATE` behavior from lifecycle updates. An existing different-version target conflicts, and same-version replacement requires the existing record identity to remain unchanged. Conflicts retain Registry rows/history and leave the filesystem unchanged.
- Captured pre-mutation hashes for trust and pin events. Kept P15C provider hash verification unchanged.
- Updated Skill Center lifecycle actions to create a server-held decision before requesting its one-time approval.

## Validation

- P15A/P15B/P15C/P15D skill regression suites: **125 passed**.
- Lifecycle approval, mismatch, replay, rollback binding, and Registry conflict tests: **33 passed** within the regression run.
- Frontend Vitest: **14 passed** across 4 files.
- Frontend production build: **passed**. Vite reports a bundle-size advisory for the 565.18 kB JavaScript chunk.
- Ruff on modified Python modules and tests: **passed**.
- `git diff --check`: **passed**.
- Isolated HTTP smoke used a temporary Skill and temporary SQLite Registry. It verified direct approval rejection without a server-held decision/session, trust/pin target mismatch rejection, one-time replay rejection, and rollback event A rejection for event B despite equal snapshot hashes.
- Registry conflict smoke verified different-hash, different-source/provider, and disabled historical targets preserve the filesystem and pre-existing Registry record/history.
- Pytest's cache plugin reported a Windows access-denied warning for the shared `core/.pytest_cache`; isolated basetemp runs completed successfully. Task-created basetemp directories were removed and were not committed.

## Scope

No P15E/P16 or unrelated provider work was started. Live external provider update was not required by this taskbook.
