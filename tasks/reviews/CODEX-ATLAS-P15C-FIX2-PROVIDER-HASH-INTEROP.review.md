# CODEX-ATLAS-P15C-FIX2-PROVIDER-HASH-INTEROP Review

STATUS: ACCEPTED WITH LIMITATIONS

REVIEWED_HEAD: 11a3345ef2d1b84b6ffae5b9e48bfb469772c14e
WORKER_BASE_HEAD: f0cd84b40a94e3f17263326c5de77f54724526bb
IMPLEMENTATION_COMMIT: 11a3345ef2d1b84b6ffae5b9e48bfb469772c14e

## Decision

P15C-FIX2 is accepted. P15D is unblocked.

The implementation addresses the previous P15C integrity and approval blockers without weakening the security boundary.

The key acceptance point is that a skills.sh provider hash mismatch is still treated as an integrity failure. Atlas only proceeds when the provider payload is independently reproduced from the public GitHub source at an immutable commit and the complete selected Skill file set and contents are byte-for-byte equivalent. The install then uses the GitHub-verified payload, creates a fresh acquisition/approval path, and preserves the provider mismatch in provenance.

## Verified implementation

### 1. Provider hash verification is separated from Atlas local hashing

Atlas now keeps its own deterministic local content hash separate from the skills CLI provider reference hash.

The provider reference verifier executes the public skills CLI algorithm with Node:

- path + UTF-8 contents
- paths ordered by Node localeCompare
- SHA-256 over the concatenated stream
- fail closed if Node/reference verification is unavailable

The current public skills CLI still implements computeSnapshotHash as path.localeCompare followed by path and contents hashing.

### 2. Provider mismatch fallback is fail-closed

For a provider hash mismatch:

- GitHub source is resolved independently.
- The source commit SHA and root tree SHA are recorded.
- A recursive tree with truncated=true is rejected.
- The selected Skill files are fetched by immutable commit SHA.
- Symlink, unsafe path, size and UTF-8 checks remain enforced.
- Provider and GitHub normalized file sets/content are compared exactly.
- Different content or unavailable GitHub source remains BLOCK.
- Identical content produces a GitHub-verified fallback acquisition.
- The provider hash is never silently accepted.

This matches the real-world stale-snapshot failure mode documented in the skills ecosystem.

### 3. Approval boundary remains intact

The fallback does not grant installation permission.

A fallback acquisition must:

- obtain a new acquisition record;
- pass a new Preview;
- obtain a new server-issued approval;
- pass the WARN second-confirmation gate where applicable;
- reject authorization created for another acquisition;
- reject replay after consumption.

The existing agent-facing install capability still cannot mint approval.

### 4. Provenance is complete

Successful fallback installation records:

- provider hash;
- provider reference-computed hash;
- mismatch flag;
- fallback reason;
- GitHub source;
- GitHub commit revision;
- root tree SHA;
- installed/computed local hash;
- approval event;
- installation timestamp/path;
- security gate result.

This distinguishes catalog provenance from the actual verified installation source.

### 5. Live smoke result

The worker performed a real skills.sh search and a real 76-file download.

Observed:

- provider hash: ca7b0c0c6e5f2750043f7f0cd72d16ac4e2abc48f9b5500d047a4b77a2506212
- Node reference-computed hash: 3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357
- Atlas local hash: 3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357
- GitHub commit: 063bee94c3f4df8453406c830b0a7df0f286027c
- GitHub root tree: f94978e8351f77b2d84911fac5d3dd9d51408af9
- 76-file provider payload and GitHub payload: identical
- final path: GitHub fallback
- WARN confirmation: passed
- Skill Center installation: passed into a temporary test directory
- production skills directory: not modified

The result also reports 17 multi-file live search candidates, none with a provider/reference hash match. No fabricated healthy provider case was used; the healthy path is covered by an independent reference-matching fixture and normal approval/install test.

## Validation

- Backend: 95 tests passed.
- Frontend: 13 tests passed.
- Production build: passed.
- Modified-file Ruff: passed.
- git diff --check: passed.
- Full core Ruff still reports unrelated pre-existing diagnostics in unmodified modules.
- Final worker HEAD equals origin/main at 11a3345ef2d1b84b6ffae5b9e48bfb469772c14e.

## Limitation

No healthy multi-file skills.sh provider sample was available in the live search batch. This is not a blocker because the taskbook explicitly permits retaining BLOCK when the live provider has no healthy sample, provided the healthy path is covered by a matching fixture. The live mismatch path was actually exercised end-to-end.

## Queue decision

P15C-FIX2 is accepted.

P15D — Skill Lifecycle & Trust Management is now READY.

P15D must remain separate from P15C acquisition integrity: do not weaken P15C verification, approval, provenance, or no-auto-execution rules while implementing lifecycle operations.
