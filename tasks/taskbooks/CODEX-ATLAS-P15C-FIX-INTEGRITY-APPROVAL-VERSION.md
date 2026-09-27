# CODEX-ATLAS-P15C-FIX-INTEGRITY-APPROVAL-VERSION

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15C-SKILL-CATALOG-FEDERATION
CODE_BASE_HEAD: 4ba880359ff32d5883d7d426e31c49594d3e8821

## Objective

修复 P15C 验收发现的三个真实阻塞问题，使“外部找到 → 预览 → 安全检查 → 明确授权 → 原子安装 → Registry → Discovery”真正可用于生产。

**本任务只修 P15C，不进入 P15D。**

## Blocking Fix A — skills.sh Remote Hash Compatibility

Current P15C hashes sorted file contents only. This is not the current skills.sh snapshot-hash algorithm.

The skills.sh CLI computes its snapshot hash as:

1. sort files by relative path using the provider's deterministic ordering;
2. for each file, update the SHA-256 with the relative path;
3. update the SHA-256 with the file contents;
4. return the hex digest.

Reference:

https://github.com/vercel-labs/skills/blob/main/src/blob.ts

### Required implementation

- Add one canonical Atlas helper for external payload hashing.
- Hash normalized relative POSIX paths + UTF-8 contents exactly as above.
- Use the same helper for:
  - computed_sha256;
  - remote hash verification;
  - provenance.
- Keep remote-hash mismatch as BLOCK.
- Do not silently ignore remote hash.
- Add tests with:
  - one file;
  - two or more files where path inclusion changes the digest;
  - remote hash match;
  - remote hash mismatch.
- The expected multi-file digest must be independently calculated in the test, not produced by calling the same implementation helper twice.

## Blocking Fix B — Server-Verifiable Explicit Approval

The current HTTP install endpoint accepts caller-generated `approved=true` + arbitrary `approval_event_id`. Replace this with a real server-side approval state transition.

### Required behavior

After inspection, the server keeps a pending acquisition containing at least:

- acquisition_id
- provider/external_id
- computed_sha256
- name/version
- security result
- created_at
- expiry
- current approval state

The Skill Center's explicit user action must cause the server to create an approval event containing:

- server-generated approval_event_id
- acquisition_id
- computed_sha256
- approved_at
- approval state
- one-time install authorization

The final install operation must consume that server-issued authorization.

Reject:

- no approval;
- arbitrary client-supplied approval_event_id;
- approval for a different acquisition;
- approval for changed payload/hash;
- expired approval;
- replayed/consumed authorization;
- BLOCK skills;
- WARN without the second explicit warning confirmation.

### Session/UI boundary

Use the existing desktop web UI architecture. The exact implementation is up to the worker, but the server must not treat a random UUID supplied by the browser as proof of approval.

If a session/cookie/CSRF binding is introduced, keep it local-only, short-lived, and free of persistent secrets.

### Agent boundary

- `skill.catalog.search`: allowed.
- `skill.catalog.inspect`: allowed.
- `skill.catalog.install`: must continue to refuse.
- Agent invocation must not be able to mint the UI approval artifact.
- Add a direct test proving an Agent cannot mint/consume approval.

### Audit

Registry provenance must store the server-created approval event ID and timestamp.

Do not store raw passwords, API keys, bearer tokens, or long-lived session secrets in Registry.

## Blocking Fix C — Versionless Skills

Atlas SkillManager already treats missing `version` as `0.0.0`.

P15C acquisition must do the same:

- missing version → `0.0.0`;
- valid supplied version → preserve it;
- malformed supplied version → reject.

Regression fixture:

https://raw.githubusercontent.com/vercel-labs/skills/main/skills/find-skills/SKILL.md

That fixture currently has no version field.

Preview must show the normalized version. Registry provenance must contain it.

## Additional Hardening

### GitHub tree truncation

When using the recursive Git Trees API, inspect the response's `truncated` flag.

If truncated:

- do not claim the skill payload is complete;
- either fetch the required subtree deterministically or reject with an explicit incomplete-tree error;
- never install from a potentially incomplete tree.

GitHub documents a maximum response size for recursive trees and explicitly signals truncation.

### Concurrent conflict safety

Two simultaneous installs of the same external identity must not silently overwrite one another.

At minimum:

- make the name/version conflict decision atomic;
- preserve existing Registry data;
- never replace an existing skill directory during normal P15C install;
- add a regression test for duplicate/concurrent install attempts.

## Live Smoke Test

After implementation, perform a real network smoke test. Mock-only verification is not sufficient for this fix.

Minimum:

1. real skills.sh search using the provider search endpoint;
2. select one public result and inspect its detail/payload;
3. verify whether v1 detail/audit requires authentication in the current environment;
4. if detail is unavailable due provider authentication, verify the documented GitHub fallback path;
5. inspect a real versionless skill;
6. inspect a real multi-file skill and verify remote hash == Atlas computed hash;
7. verify public GitHub acquisition of a real repository/path;
8. do not install anything into the production Atlas skills directory during smoke testing unless the test uses an isolated temporary skills directory.

Record exact endpoints, result status, and any provider limitations in the result file.

Current official API documentation:

https://www.skills.sh/docs/api

## Tests

Required new/updated tests:

- exact skills.sh multi-file hash compatibility;
- hash mismatch BLOCK;
- versionless normalization to 0.0.0;
- invalid version rejection;
- server-side approval creation;
- arbitrary approval ID rejection;
- approval acquisition/hash binding;
- approval expiry;
- approval replay rejection;
- Agent cannot mint/consume approval;
- WARN second confirmation;
- BLOCK rejection;
- GitHub tree truncation handling;
- concurrent/conflicting install safety;
- existing P15A/P15B regression;
- frontend approval flow updated to the new server-side contract.

## Acceptance Criteria

1. A real multi-file skills.sh payload with a provider hash passes exact hash verification.
2. A modified payload fails hash verification and is BLOCKed.
3. A versionless public Skill installs with normalized version `0.0.0`.
4. A malformed supplied version is rejected.
5. Installation without server-created approval is impossible.
6. Client-generated arbitrary approval_event_id is rejected.
7. Approval is bound to the exact reviewed acquisition and hash.
8. Approval is one-time and expires.
9. WARN requires the explicit second confirmation.
10. BLOCK can never install.
11. Agent search/inspect work; Agent install remains denied and cannot mint approval.
12. Registry provenance contains the server-created approval event ID/timestamp.
13. GitHub tree truncation cannot result in an incomplete install.
14. Duplicate/concurrent installation cannot silently overwrite an existing skill.
15. Real network smoke test is recorded.
16. Backend and frontend tests pass.
17. Production build passes.
18. New/modified Python code passes Ruff.
19. `git diff --check` passes.
20. No secrets/tokens are persisted in Registry or acquisition records.
21. No automatic execution, activation, dependency installation, MemoryOS write, or P15D lifecycle work is introduced.

## Delivery

- Read `LUNA_WORKER.md`.
- Pull `origin/main`.
- Record actual starting HEAD.
- Execute only this fix task.
- Write:
  `tasks/results/CODEX-ATLAS-P15C-FIX-INTEGRITY-APPROVAL-VERSION.result.md`
- Commit implementation + result.
- Push to `origin main`.
- Verify local HEAD == origin/main.
- Stop. Do not start P15D.

## Queue Intent

If this fix passes review, the next stage is:

**P15D — Skill Lifecycle & Trust Management**

Only then may the queue advance to update/remove/rollback/trust/version pinning/provenance history/dependency state.
