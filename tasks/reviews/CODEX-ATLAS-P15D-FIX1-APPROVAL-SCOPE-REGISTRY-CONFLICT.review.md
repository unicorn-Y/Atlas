# CODEX-ATLAS-P15D-FIX1-APPROVAL-SCOPE-REGISTRY-CONFLICT Review

STATUS: ACCEPTED

REVIEWED_HEAD: ba1e56de6d627bbbee428143d369536824a28e9d
PREVIOUS_REVIEW: tasks/reviews/CODEX-ATLAS-P15D-SKILL-LIFECYCLE-AND-TRUST.review.md
IMPLEMENTATION_COMMIT: 01d1282c4eabbfdcc3ff2cc8151b28cdfd6bd148
RESULT_COMMIT: ba1e56de6d627bbbee428143d369536824a28e9d

## Decision

P15D-FIX1 is ACCEPTED.

The rework addresses all acceptance-blocking findings from the P15D review. P15D can now be considered accepted and the queue may advance to the next bounded Skill capability task.

## Verified fixes

### 1. Exact lifecycle approval scope

The server-side approval record now binds the applicable full transition scope:

- action
- skill name
- current version
- current content hash
- target content hash
- acquisition ID for update/downgrade
- target trust state
- target pin policy
- rollback event ID
- rollback snapshot hash
- reason
- creation/expiry
- unique approval event ID
- one-time consumption

The execution routes recompute the applicable scope and compare it against the persisted approval before executing.

### 2. Server-held Skill Center decision boundary

Lifecycle approval minting is no longer a generic action/name/version assertion.

The current flow is:

Skill Center session credential
-> server-held lifecycle decision
-> one-time server approval
-> lifecycle execution

Electron generates the Skill Center session token, the main process exposes it only to the trusted Atlas main-frame UI, and lifecycle decision/approval endpoints require that credential plus a trusted origin.

The Agent capability registry still does not expose lifecycle approval mint/consume authority.

### 3. Rollback exact-event binding

Rollback approval now binds both:

- exact source event ID
- snapshot hash

Execution also rechecks the current skill identity/version/content hash under the lifecycle lock.

The added HTTP test verifies event A cannot authorize event B even when both snapshots have the same hash.

### 4. Registry conflict hardening

The lifecycle update commit path no longer uses silent ON CONFLICT DO UPDATE behavior for a different-version target.

An existing target name+version now produces a deterministic conflict before a replacement is committed. Same-version content replacement remains allowed only for the current record and requires stable source identity.

The tests cover:

- different hash
- different source/provider
- disabled historical target

and verify the pre-existing Registry record and filesystem remain unchanged.

### 5. Audit hash correctness

Trust and pin transitions now capture the pre-transition content hash before mutation.

Audit events record:

- previous_hash = pre-transition hash
- resulting_hash = post-transition hash

The regression coverage checks the before-hash values.

## Validation evidence

Worker-reported validation at ba1e56de6d627bbbee428143d369536824a28e9d:

- P15A/P15B/P15C/P15D regression: 125 passed
- lifecycle approval/mismatch/replay/rollback/Registry targeted coverage: 33 passed
- frontend: 14 passed
- production build: passed
- Ruff: passed
- git diff --check: passed
- isolated HTTP smoke: passed
- Registry conflict smoke: passed
- LOCAL_HEAD == origin/main: verified by worker
- git status: clean

The implementation was also inspected directly at the remote HEAD for the approval, Server, Registry, lifecycle, Electron IPC, frontend flow, and added regression tests.

## Non-blocking validation notes

- Vite reports a bundle-size advisory.
- Pytest reports a Windows shared-cache permission warning; isolated test runs passed.
- Live external provider update was not required for this bounded fix; P15C provider verification remains unchanged.

## Queue decision

P15D-FIX1 is complete and accepted.

Advance to:
CODEX-ATLAS-P15E-SKILL-DEPENDENCY-AND-DISTRIBUTION

Do not start P16 or the later learning/generated-tool work in this task.
