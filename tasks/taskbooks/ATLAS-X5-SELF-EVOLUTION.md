# ATLAS-X5-SELF-EVOLUTION — upstream-to-approved-change pipeline

STATUS: PREPARED (future implementation taskbook; no implementation authorized by this document)
OWNER: future Sol-assigned worker
RESULT: `tasks/results/ATLAS-X5-SELF-EVOLUTION.result.md`
RESEARCH: `docs/research/2026-10-03-x-prep/05-x5-sources.md`

## User-visible goal

Atlas notices meaningful changes in its approved upstream sources and product references, maps them to current Atlas parity, drafts a reviewable taskbook, and—only after explicit approval—runs implementation in an isolated worktree, captures regression evidence, and proposes a merge. Repeated successful work may become a reviewed skill/recipe candidate through the existing approval and C4 registry flow.

## Non-goals and scope boundary

- No autonomous production checkout edits, commits to the base branch, push, merge, release, dependency install, or skill promotion.
- No second scheduler, source registry, event store, session/runtime, policy store, or skill registry.
- No unbounded crawling or model polling. Watch only explicitly allowlisted source identifiers and approved intervals.
- X5 work changes only X5-named files after its own implementation taskbook is separately authorized; it must not change Atlas core authority, Hermes pin, or user configuration during source discovery.

## Current Atlas and Hermes capability

- Atlas: scheduler in `core/atlas/scheduler/__init__.py`; durable task backend in `core/atlas/capabilities/durable/dbos_backend.py`; scheduled goal delegation and Hermes lifecycle in `core/atlas/server.py` and `core/atlas/engine/session_sync.py`; worktree services in `core/atlas/agent/subagent_worktree.py` and `core/atlas/task_artifacts.py`; current Hermes dependency pin in `core/pyproject.toml`; source record in `docs/plan/VENDORED.md`; reviewable knowledge/experience APIs in `core/atlas/memory/__init__.py`; existing single C4 `SkillManager` and `SkillRegistry` initialized from `core/atlas/server.py`.
- Hermes fork at `D:/hermes-agent`: `hermes_cli/goals.py`, `hermes_state_sessions.py`, `hermes_state_compression.py`, `cron/monitor.py`, `cron/scheduler.py`, `cron/scheduler_detached_worker.py`, `hermes_cli/service_manager.py`, and `gateway/run_goals.py` provide persistent session/goals, leases, monitor no-change suppression, scheduling and gateway/service lifecycle.
- Current confirmed Atlas dependency is `unicorn-Y/hermes-agent@e287231d7906bcce5bc373d20fb2e3e1e6427220` (MIT; dependency record in `core/pyproject.toml`). Re-derive this at implementation start. Do not treat older `VENDORED.md` rows or code comments as the current pin.

## Mature sources and exact reuse boundary

- Renovate `renovatebot/renovate`, `lib/workers/repository/updates/generate.ts`, `lib/workers/repository/updates/branchify.ts`, `lib/workers/repository/update/pr/index.ts`, and `docs/usage/faq.md`: adopt per-source diff, isolated branch, review/approval and update-proposal sequencing. License is AGPL-3.0; do not copy code into Atlas.
- OpenAI Codex `openai/codex`, `codex-rs/worktree/src/lib.rs`, `codex-rs/worktree/src/git.rs`, `docs/sandbox.md`, `docs/execpolicy.md`: adopt explicit worktree/base identity and separate command-policy/approval boundary. License is Apache-2.0 with component-specific licenses; do not port its runtime/policy engine.
- OpenHands `All-Hands-AI/OpenHands`, `src/api/conversation-service/agent-server-conversation-service.api.ts` and `...types.ts`: use as a reference for long-lived work item state and resumable task surfaces, not as Atlas's session/task authority. MIT.
- Hermes upstream/fork exact file set is recorded in `docs/research/2026-10-03-x-prep/05-x5-sources.md` and `evidence-x5-x7.json`; compare upstream to the current pinned fork before drafting a proposed vendor change.

## Implementation steps (file-level, future authorized wave only)

1. Add an allowlisted source definition through existing Atlas config/task source mechanism. A source record must hold canonical repo/product URL, source type, pinned/current identifier, last checked timestamp, approved cadence, license URL/name, and failure state. Do not create a competing registry; if no suitable current config contract exists, propose its smallest extension in the X5 task result before coding.
2. Add deterministic source adapters for GitHub commit/tag/release comparison and official changelog/document revision metadata. Store only normalized source identities and evidence in the existing durable task/event path; fetching error must remain distinct from no-change.
3. Compute stable source fingerprints and changed-file/content hashes. For vendored repos, compare the actual current fork pin and Atlas-recorded vendored file list, then classify local patches, upstream additions/removals and upstream edits separately.
4. Add a parity mapper that emits candidate fields: source id + old/new SHA/tag + date + license; changed path/hash list; affected `CORE-PARITY` row ids; exact Atlas current file paths; whether Atlas already contains the capability; gap/risk; suggested X taskbook and dependencies. It emits proposals only.
5. Add taskbook draft generation to `tasks/taskbooks/ATLAS-X5-*.draft.md` or the user-approved draft convention. Require exact files, ownership, pre/post acceptance, fake/real boundaries, blocker, proposed parity line and stop state. Keep immutable evidence alongside the draft under `docs/research/` or existing task artifacts.
6. Bind human approval to draft digest, evidence digest, exact base SHA, allowed paths, and test command. A changed base, draft, source SHA, requested file, or command invalidates approval. Surface approval using the current Atlas ask/approval path.
7. After approval, use existing `WorktreeService`/`create_subagent_worktree` to make one isolated branch at the bound base SHA; reject dirty/ambiguous base. Apply the existing Atlas permission mode and explicit command constraints; never lower the parent permission mode.
8. Run the exact fake fixture and narrow regression selection in that worktree. Store command, selection, environment-isolation identity (fake HOME/data root/repo), exit status, stdout/stderr artifact references, changed path set and final commit SHA.
9. If checks pass, create a merge proposal artifact that includes source/license, diff, changed paths, focused acceptance, failed/skipped checks, and parity delta. Stop for a human decision. No merge, push, or promotion occurs automatically.
10. If outcome is repeatedly successful, create a skill/recipe candidate using existing memory review and C4 installation/registry lifecycle. Include replay data and references; require the current owner review before candidate approval or installation.

## Data and events

Represent source observations with stable records keyed by `(source_id, observed_revision)` and tasks with existing durable task/goal identifiers. Record typed events in the existing task event/evidence channel: `source.check.started`, `source.check.failed`, `source.changed`, `source.unchanged`, `parity.proposal.created`, `taskbook.draft.created`, `approval.requested`, `approval.granted`, `approval.invalidated`, `worktree.created`, `focused_checks.finished`, `merge_proposal.created`, `skill_candidate.created`, `skill_candidate.reviewed`. Never store secrets, full private source contents, or mutable branch state as source identity.

## Backend, frontend, Windows

- Backend: adapters call allowlisted official/GitHub sources, fingerprint, map, draft and queue through existing scheduler/DBOS task paths. Add idempotency by source revision and draft digest.
- Frontend: use the existing task/approval/skill surfaces to show source evidence, diff, parity mapping, requested permission and approval scope. No new dashboard authority.
- Windows: support paths with spaces, process interruption and service restart; persist before external fetch/write. After restart resume the same idempotency key; never repeat an approval-bound mutation unless its approval and base are still valid.

## Acceptance

Fake acceptance: unchanged fake upstream produces no draft and zero model calls; changed fake upstream creates one stable observation and one draft; second poll deduplicates; fetch error becomes `failed/unknown`; Atlas/fork pin mismatch yields a mismatch proposal, not auto-correction; license/path provenance is present; approval digest or base SHA change rejects execution; approved task produces an isolated worktree only under allowed paths; synthetic check failure produces no merge proposal; pass creates a review-only proposal; no command commits/merges/pushes or updates C4; a repeated success creates only an unapproved candidate.

Real-world acceptance: owner approves one low-risk dependency/source update on an isolated branch, verifies exact source SHA/date/license and changed files, observes the scoped test result and proposal, then manually reviews and merges outside X5. Exercise suspend/restart/network loss and confirm no duplicate proposal or approval bypass. No production source changes during the acceptance run.

## CORE-PARITY proposal, dependencies, blockers

- Proposed CORE-PARITY row: `X5 upstream-change-to-approved-taskbook` — allowlisted source observation → immutable provenance → Atlas parity proposal → digest-bound human approval → isolated worktree → focused evidence → human merge proposal; no auto mutation.
- Dependencies: C1 Hermes pin/provenance completion; current Atlas task/approval API; X4 single SkillManager/SkillRegistry contract; X1 source identities if connector APIs are used. X5 must first work with GitHub/public official sources without waiting on X1.
- Blockers: unsettled canonical source allowlist/credentials; inability to bind approval to base/draft/paths/commands; incomplete C1 pin provenance. Any of these makes execution stop as `BLOCKED`/`PARTIAL`, never inferred as safe.
- Result file: `tasks/results/ATLAS-X5-SELF-EVOLUTION.result.md`.

