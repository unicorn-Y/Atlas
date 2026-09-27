# CODEX-ATLAS-P15C-SKILL-CATALOG-FEDERATION Review

STATUS: REWORK REQUIRED

REVIEWED_HEAD: 4ba880359ff32d5883d7d426e31c49594d3e8821
WORKER_BASE_HEAD: 40e895be8bdf48cc78e0730bc30ccee568e206d9
IMPLEMENTATION_COMMIT: 4ba880359ff32d5883d7d426e31c49594d3e8821

## Decision

P15C is **not accepted yet**. The delivered implementation covers most of the requested architecture and has strong mocked regression coverage, but three issues are acceptance-blocking because they affect real external-skill installation and the security boundary.

Do not advance to P15D until the P15C fix task is completed and re-reviewed.

## What passed

- Local / External / All Skill Center modes are present.
- skills.sh search normalization and provider failure handling are implemented.
- Public GitHub repository + skill-path acquisition is implemented.
- Path traversal, absolute-path, size, non-text, and symlink checks have dedicated tests.
- PASS/WARN/BLOCK security evidence exists.
- Preview is read-only with respect to Registry and activation.
- Staging + cleanup + rollback are implemented.
- Registry provenance is recorded in the existing P15A Registry.
- Agent `skill.catalog.search` and `skill.catalog.inspect` are read-only.
- Agent `skill.catalog.install` explicitly refuses installation.
- Frontend tests and production build pass.
- Backend test suite reported 78 passed.
- Worker pushed `4ba880359ff32d5883d7d426e31c49594d3e8821` to origin/main and the worktree was cleaned by the monitor.

## Blocking Finding 1 — Remote hash algorithm is incompatible with skills.sh

Current `prepare_acquisition()` computes the payload digest by sorting file names and hashing only the concatenated file contents.

The current skills.sh implementation computes the snapshot hash by sorting files by path and hashing **path + contents** for every file. See:

- https://github.com/vercel-labs/skills/blob/main/src/blob.ts
- `computeSnapshotHash(files)` in the current skills.sh CLI source.

Therefore the current Atlas hash can match a single-file test while disagreeing with the real skills.sh hash for a multi-file skill.

Impact:

- A legitimate skills.sh skill with supporting files can be reported as `remote_hash_mismatch`.
- The acquisition is then BLOCKed even though the fetched snapshot is the exact skills.sh snapshot.
- Acceptance criterion 11 is therefore not actually satisfied for the real multi-file provider payload.

Required fix:

Implement the exact skills.sh snapshot-hash algorithm for the provider hash:

1. sort normalized relative file paths deterministically;
2. hash each relative path followed by that file's UTF-8 contents;
3. SHA-256 the resulting byte stream;
4. compare to the provider hash;
5. add a multi-file regression test whose expected digest is independently calculated.

Do not weaken the mismatch gate.

## Blocking Finding 2 — Explicit approval is client-asserted, not server-verifiable

The install route currently accepts:

- `approved: true`
- an arbitrary caller-supplied `approval_event_id`

The frontend itself creates that ID with `crypto.randomUUID()`.

The backend does not currently have a server-issued, one-time approval record/challenge proving that the reviewed acquisition was explicitly approved. The provenance record therefore stores a caller-provided string as an "approval event", rather than a server-created approval event.

This fails the intended acceptance requirement that installation have an auditable explicit approval and leaves the HTTP install boundary weaker than the Skill Center UX suggests.

Required fix:

Create a server-side approval state transition that is bound to:

- acquisition_id
- external_id / provider
- computed payload SHA-256
- manifest name/version
- security result
- approval timestamp
- a unique server-generated approval event ID
- one-time consumption / replay prevention
- short expiration

The final install request must require the server-issued approval artifact and reject:

- missing approval
- arbitrary client-generated approval IDs
- approval for another acquisition
- approval for changed/re-fetched payload
- expired approval
- reused approval

The Agent capability must remain unable to mint or consume that approval.

The exact transport/session mechanism is implementation-defined, but the server must be able to distinguish "a valid Skill Center approval state exists" from "the caller merely sent approved=true".

## Blocking Finding 3 — Versionless external skills are rejected

Atlas's own SkillManager intentionally defaults a missing `version` to `0.0.0`.

The P15C acquisition parser instead requires a `version` field and rejects a valid SKILL.md when it is absent.

A current public skills.sh example, `vercel-labs/skills/find-skills`, has a SKILL.md whose frontmatter contains `name` and `description` but no `version` field:

https://raw.githubusercontent.com/vercel-labs/skills/main/skills/find-skills/SKILL.md

Therefore a normal public skills.sh result can be discoverable but impossible to install through Atlas.

Required fix:

- If version is absent, normalize it to `0.0.0`, matching Atlas SkillManager behavior.
- Preserve a valid supplied version.
- Keep invalid supplied versions rejected.
- Add a regression test using a versionless external payload.
- Ensure the normalized version is shown in Preview and stored in Registry provenance.

## Validation Limitation — No live network acquisition was executed

The worker used mocked HTTP responses only.

This is acceptable as part of unit/regression coverage, but after the fixes a live smoke test is required because the current skills.sh API has distinct search and v1 detail/audit behavior. The official API documentation currently states that v1 endpoints are authenticated with Vercel OIDC, while the public CLI search path still uses `https://skills.sh/api/search`.

Official documentation:

https://www.skills.sh/docs/api

The fix validation should record the real behavior encountered rather than assuming the mocked provider contract is identical to production.

## Additional Hardening Requested

- Check the GitHub recursive tree response's `truncated` flag. Do not treat a truncated tree as a complete skill payload.
- Add a concurrent-install test or otherwise make the name/version conflict decision atomic enough that two simultaneous installs cannot silently replace the same Registry identity.
- Keep P15A/P15B regression coverage intact.
- Do not add P15D lifecycle functionality during the fix.

## Re-review Gate

P15C becomes ACCEPTED only when:

1. the three blocking findings above are fixed;
2. new regression tests prove the fixes;
3. the live smoke test is recorded;
4. backend/frontend tests and build pass;
5. Ruff and `git diff --check` pass;
6. the worker pushes the final commit and verifies local HEAD == origin/main;
7. the monitor re-checks the final tree and result record.

Until then: **P15D is blocked by queue discipline.**
