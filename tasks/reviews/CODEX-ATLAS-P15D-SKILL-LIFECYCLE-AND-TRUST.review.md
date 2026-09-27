# CODEX-ATLAS-P15D-SKILL-LIFECYCLE-AND-TRUST Review

STATUS: REWORK REQUIRED

REVIEWED_HEAD: 04eced0a200c0590dbf394af4237ff3f669d352e
WORKER_BASE_HEAD: d21fe194a41150f003c35ae8c608496f18ccffc5
IMPLEMENTATION_COMMIT: b9e00ec
RESULT_COMMIT: 04eced0a200c0590dbf394af4237ff3f669d352e

## Decision

P15D is NOT accepted yet.

The implementation covers most of the requested lifecycle surface and has substantial regression coverage, but approval-scope and Registry-integrity issues are acceptance-blocking. Do not advance to P15E/P16 until the bounded P15D fix is completed and re-reviewed.

## What passed

- P15A Registry is extended additively; no second installed-skill registry was introduced.
- Lifecycle metadata persists and legacy installed records receive lifecycle initialization.
- Lifecycle history has SQLite update/delete guards and records provenance/hash/result/error/actor/reason/approval references.
- Update, downgrade, rollback and remove use staged filesystem transitions and same-name in-process serialization.
- Rollback snapshots are content-hashed and corrupt/missing snapshots are blocked without replacing the current payload.
- Filesystem drift is detected and blocks unsafe lifecycle operations.
- Dependency state distinguishes satisfied/missing/incompatible/unknown without auto-install.
- Revoked/blocked trust is enforced at Agent capability activation and the HTTP activation route.
- Agent lifecycle capability surface is read-only; no lifecycle approval/update/remove/rollback capability was registered.
- P15C acquisition verification is reused rather than replaced, and no provider-hash bypass was introduced.
- Frontend exposes lifecycle/trust/pin state, review/confirmation flows, rollback history and drift status.
- Reported validation: backend 120 passed, frontend 14 passed, build/Ruff/git diff check passed, and isolated HTTP smoke covered approval replay plus downgrade.

## Acceptance-blocking findings

### 1. Approval is not bound to the exact lifecycle target

The persisted approval record binds action/name/version/content_hash and, for update/downgrade, acquisition_id. It does NOT bind the exact requested lifecycle target.

Current consequences:

- A token issued for trust can be consumed with a different trust_state because the target state is supplied only to the execution route.
- A token issued for pin is not bound to the selected pin policy, exact versus hash.
- A rollback approval is not bound to event_id; the execution route supplies the rollback event separately. The token only binds the snapshot hash.
- The server therefore proves “an approval for some trust/pin/rollback action exists” rather than “this exact transition was approved.”

Required fix:

- Bind approval to the complete transition scope.
- Trust: bind target trust state.
- Pin/unpin: bind target pin policy.
- Rollback: bind exact rollback event_id and snapshot hash.
- Update/downgrade: retain acquisition_id plus incoming version/hash and current version binding.
- Consume must compare every bound field and reject scope mismatch.
- Add negative tests for each mismatched target.

### 2. Approval issuance is still a generic HTTP authority

POST /api/skills/lifecycle/approve directly creates a valid server approval from caller-supplied action/name/version/reason and optional transition data. There is no server-side trusted UI decision/session binding in this route.

This means the server cannot distinguish an explicit Skill Center user decision from an arbitrary local HTTP caller requesting an approval.

The Agent capability registry does not expose approval, which is good, but that alone does not establish the required authority boundary at the HTTP approval surface.

Required fix:

- Reuse an existing trusted Atlas approval/controller/session authority if one exists.
- Otherwise add only the minimal server-held UI/session binding needed for this P15D flow.
- The approval record must reference the server-side decision/request identity and exact transition scope.
- Direct lifecycle execution without a valid server-issued approval must remain denied.
- Agent capability code must neither mint nor consume user approval.
- Do not create a second independent long-term approval authority if an existing one can be reused.

### 3. Existing same-name/version Registry records can be silently overwritten

SkillRegistry.commit_lifecycle_update uses ON CONFLICT(name,version) DO UPDATE.

When the incoming lifecycle target already has a Registry record, this can replace that record metadata/source instead of producing a conflict. This is especially unsafe for a disabled historical version or a record with different provenance/hash.

Required fix:

- Before committing a lifecycle transition, inspect any existing target name+version record.
- If it is the same logical record and same content/provenance, allow the intended no-op/reconciliation path.
- If target hash, source identity, provider, or provenance differs, return a deterministic conflict and do not overwrite the existing record.
- Preserve both sides in lifecycle history/provenance.
- Add tests for same version + different hash, same name/version + different source, target version already present as disabled history, repeated identical transition, and conflict leaving filesystem and Registry unchanged.

### 4. Audit previous_hash is captured after mutation

transition_trust and transition_pin mutate lifecycle metadata before constructing the audit event, then pass the mutated content_hash as previous_hash.

Therefore the audit event can report the resulting hash as the previous hash.

Required fix:

- Capture before_hash before any lifecycle mutation.
- Event previous_hash must be the exact pre-transition value.
- Event resulting_hash must be the post-transition value.
- Add regression tests for trust and pin transitions with before/after hash assertions.

This is an audit-integrity blocker because the history is explicitly intended to be authoritative lifecycle evidence.

## Validation limitations

- The reported P15D smoke was isolated and did not perform a live skills.sh/GitHub update. This is not itself a blocker because P15C owns provider verification and the P15D task only requires a temporary/test Skill smoke.
- The worker result says six pytest temporary directories remained untracked locally; the monitor reports they were subsequently cleaned. The remote commit contains none of them. Final re-review should still verify the local worktree is clean.
- Vite's 564.50 kB bundle advisory is non-blocking.

## Re-review gate

P15D becomes ACCEPTED only when:

1. exact approval target scope is persisted and checked;
2. trusted UI/server decision binding is enforced, or the existing Atlas approval authority is reused;
3. Agent cannot mint or consume lifecycle approval;
4. rollback approval is bound to the exact event_id and snapshot hash;
5. same-name/version lifecycle conflicts cannot overwrite existing records silently;
6. provenance/history is preserved on conflict;
7. previous_hash records the actual pre-transition hash;
8. negative tests cover scope mismatch, replay, wrong rollback event, wrong pin/trust target, and Registry conflict;
9. P15A/P15B/P15C regression tests remain passing;
10. backend/frontend tests, build, Ruff and git diff check pass;
11. isolated HTTP smoke verifies the complete server approval to lifecycle execution path with exact target binding;
12. worker verifies LOCAL_HEAD == origin/main;
13. no P15E/P16 or unrelated feature work is started.

## Queue decision

P15D remains REWORK REQUIRED.

Next task: CODEX-ATLAS-P15D-FIX1-APPROVAL-SCOPE-REGISTRY-CONFLICT

P15E/P16 remain blocked until this fix is reviewed and accepted.
