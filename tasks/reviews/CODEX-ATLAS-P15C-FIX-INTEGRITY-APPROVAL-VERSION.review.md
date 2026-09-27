# CODEX-ATLAS-P15C-FIX-INTEGRITY-APPROVAL-VERSION Review

STATUS: REWORK REQUIRED

REVIEWED_HEAD: 5379dd3195ac06f0aeb93ddd23471c42cd0b1b37
PREVIOUS_BASE_HEAD: 5a193059d5c86400b6fe9937156e447551e1d978
IMPLEMENTATION_COMMIT: 5379dd3195ac06f0aeb93ddd23471c42cd0b1b37

## Decision

P15C-FIX is **not fully accepted yet**.

The three original security/integrity fixes are substantially implemented and the automated regression suite is strong. The remaining live failure is **not evidence that Atlas should weaken its hash gate**. The evidence instead points to a skills.sh provider-side integrity-metadata/snapshot consistency problem. Atlas should handle that provider failure explicitly and safely before the queue advances to P15D.

## What passed

- Missing manifest version normalizes to 0.0.0 while malformed supplied versions remain rejected.
- Server-created approval event and one-time short-lived install authorization are implemented.
- Client-supplied approved/approval_event_id claims are rejected at the HTTP install boundary.
- Approval is bound to acquisition and computed hash; expiry and replay are covered.
- WARN requires the second explicit confirmation; BLOCK cannot be approved.
- Agent skill.catalog.install remains denied and cannot mint the approval artifact.
- GitHub recursive-tree truncated responses are rejected.
- Same-identity installs are serialized and existing Registry/skill directories are preserved.
- Backend 84-test regression suite, frontend 13-test suite, production build, changed-module Ruff, and git diff --check were reported passing.
- No production skills directory was modified during live smoke testing.

## Live provider-hash finding

The worker performed a real request to:

https://skills.sh/api/download/vercel-labs/agent-skills/vercel-react-best-practices

The response contained 76 files and reported provider hash:

`ca7b0c0c6e5f2750043f7f0cd72d16ac4e2abc48f9b5500d047a4b77a2506212`

Atlas recomputed a hash over the fetched payload:

`3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357`

and correctly BLOCKed the acquisition.

This is the correct security behavior. **Do not change the gate to accept the provider hash merely because the provider returns it.**

### Why this looks provider-side

The current public skills CLI source defines `computeSnapshotHash()` as SHA-256 over sorted `path + contents` pairs:

https://github.com/vercel-labs/skills/blob/main/src/blob.ts

The same source also shows that for a complete downloaded snapshot the CLI uses `download.hash` directly; it does not independently re-hash the complete provider payload before assigning `snapshotHash`.

Public evidence also shows repeated skills.sh stale-snapshot incidents where the public download endpoint served older content than the current GitHub repository:

- https://github.com/vercel-labs/skills/issues/1433
- https://github.com/vercel-labs/skills/issues/1682
- https://github.com/vercel-labs/skills/issues/1918
- https://github.com/vercel-labs/skills/issues/2061

There is additional corroboration that the hash `3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357` is used in current public `skills-lock.json` files for the GitHub source:

- https://github.com/sanity-io/plugins/blob/main/skills-lock.json
- https://github.com/antonio-orionus/Arroxy/blob/main/skills-lock.json

Older public locks still contain `ca7b0c0c6e5f2750043f7f0cd72d16ac4e2abc48f9b5500d047a4b77a2506212`:

- https://github.com/vercel-labs/openwiki/blob/main/skills-lock.json

This is strong evidence of stale/inconsistent provider metadata, but it is not by itself a cryptographic proof of which exact snapshot the provider currently intends to attest. Therefore Atlas must continue treating the mismatch as an integrity failure until an independent source comparison succeeds.

## Important Atlas-side issue still to fix

The new Atlas `payload_sha256()` orders paths with:

`(value.casefold(), value)`

while the current skills CLI reference code uses:

`file.path.localeCompare(file.path)`

Those are not the same ordering contract in general. The current real skill happens not to expose a differing order strongly enough to explain the observed mismatch, but the implementation should not claim exact upstream algorithm compatibility without a reference test.

Add an independent reference test covering mixed-case and punctuation-bearing paths. Do not silently broaden the accepted hash set.

## Required resolution

Treat this as **provider interoperability handling**, not as permission to bypass integrity verification.

The next fix must:

1. Reproduce the live provider mismatch and preserve the evidence.
2. Independently compare the downloaded skills.sh file set/content with the public GitHub source for the same external identity.
3. If the provider payload content exactly matches the GitHub source but the provider's declared hash is stale/wrong:
   - do NOT accept the provider hash;
   - do NOT install the provider snapshot;
   - fall back to the validated GitHub acquisition;
   - record the provider-integrity mismatch as provenance/audit evidence;
   - keep the direct GitHub computed hash as the installed content hash.
4. If the provider payload differs from GitHub:
   - BLOCK the acquisition;
   - do not install either payload automatically;
   - show that the catalog snapshot is stale/inconsistent and requires reindex/provider repair.
5. If GitHub cannot be fetched or independently validated:
   - BLOCK; never bypass the provider mismatch.
6. A healthy provider hash match must continue to pass the normal hash gate.
7. Never treat the provider hash as advisory when it matches only because the code stopped checking it.

## Exact-hash compatibility

The fix must either:
- make Atlas's hash computation exactly reproduce the current skills CLI reference behavior and prove this with independent fixtures, or
- explicitly define Atlas's local content hash as a separate deterministic hash and stop claiming it is the same algorithm as skills.sh; in that design, provider hash is verified only by a separately implemented/reference-compatible verifier.

Do not add a weak or undocumented "try several hash algorithms until one matches" fallback.

## Queue status

P15D remains **BLOCKED**.

No lifecycle/update/remove/rollback/trust-management work may start until this interoperability fix is reviewed and accepted.
