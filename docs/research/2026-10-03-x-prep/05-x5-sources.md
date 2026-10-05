# X5 sources: controlled self-evolution

Research date: 2026-10-03. Clones are isolated under `D:/Atlas-x-prep-sources/`; no source was copied into Atlas.

## Design conclusion

X5 should be an approval pipeline over existing Atlas Git/taskbook/skill and memory-review authorities. It must never silently edit a production checkout, promote a skill, or merge itself. Treat each detected upstream or product change as evidence that may produce a proposed taskbook; only explicit owner approval can authorize an implementation worktree. Passing focused acceptance creates a merge proposal, not a merge.

## Capability-to-source map

| Capability | Best source and exact files | What to take | Atlas already has / thin connection |
|---|---|---|---|
| Detect vendored source drift | Hermes upstream `hermes_state_sessions.py`, `hermes_state_compression.py`, `hermes_cli/goals.py`, `cron/monitor.py`; Atlas pin in `core/pyproject.toml`, provenance in `docs/plan/VENDORED.md` | Compare exact pinned commit and owned file blobs; report changed, removed, added, and locally patched files with diffstat and content hashes. | Atlas already pins Hermes in `core/pyproject.toml` and has `VENDORED.md`. Re-read both at execution start; current confirmed dependency pin is `unicorn-Y/hermes-agent@e287231d7906bcce5bc373d20fb2e3e1e6427220`. Older VENDORED entries and source comments are historical evidence only, not authority. |
| Watch dependency versions and open an update proposal | Renovate `lib/workers/repository/updates/generate.ts`, `lib/workers/repository/updates/branchify.ts`, `lib/workers/repository/update/pr/index.ts`, `docs/usage/faq.md` | Keep its separation of discovery, branch generation, per-update PR, and explicit dashboard approval. Do not vendor Renovate or adopt its AGPL implementation into Atlas. | Atlas Git/taskbook flow is the implementation authority. The thin adapter stores source/version/diff evidence and drafts a taskbook in the existing taskbook location. |
| Track upstream capability changes | GitHub releases/tags/commit compare plus official changelog/RSS/API endpoints for only allowlisted repos/products | Persist source URL, checked-at, observed head/tag, previous head/tag, and immutable diff identity. Fetch details only after identity changes. | Reuse `AtlasScheduler` and existing task event/runtime paths; do not create another poller or event store. Product pages from X1–X7 source maps become allowlisted watch definitions. |
| Map upstream change to Atlas parity | Atlas `docs/plan/CORE-PARITY.md`, source pin, taskbook and result conventions; OpenHands `src/api/conversation-service/agent-server-conversation-service.api.ts` as a reference for durable work item surfaces | Produce a structured candidate with source evidence, affected parity row(s), current Atlas implementation files, gap, risk, and suggested owner taskbook. | This remains advisory. Atlas memory already has explicit review methods for knowledge refinements/proposals (`core/atlas/memory/__init__.py`); route learned experience through those approvals rather than a new self-evolution store. |
| Generate a buildable taskbook | Atlas taskbook conventions; OpenHands agent-server conversation service for resumable work item boundaries | Generate a draft that names exact source files, Atlas files, ownership, data/events, fake/real acceptance, dependency/blocker, CORE-PARITY proposal, and stop conditions. | Save as a draft in the existing `tasks/taskbooks/` tree and link its evidence. No model call for unchanged source fingerprints. |
| Isolated implementation and regression | OpenAI Codex `codex-rs/worktree/src/lib.rs`, `codex-rs/worktree/src/git.rs`, `docs/sandbox.md`, `docs/execpolicy.md`; Atlas `core/atlas/agent/subagent_worktree.py`, `core/atlas/task_artifacts.py` | Reuse the principle of a separate Git worktree and explicit command approval/sandbox contract. Do not copy Codex runtime or permission engine. | Atlas already creates subagent worktrees and task artifact worktrees. Start from the exact base SHA, reject dirty/ambiguous base, record file ownership and allowed test command; implement only after taskbook approval. |
| Human approval, test evidence, merge proposal | Renovate dependency dashboard approval and PR lifecycle; Atlas existing approval/taskbook/result workflow | Require a recorded approval bound to taskbook digest, base SHA, owned paths, and requested action. Test pass can unlock proposal creation but never auto-merge. | Reuse Atlas approval callback and task result; source/check/test evidence remains attached to the worktree/task. |
| Successful experience → reusable skill candidate | Atlas `core/atlas/memory/__init__.py` approved-goal-knowledge/experience review and existing C4 `SkillManager`/`SkillRegistry` | Create only a skill/recipe candidate with run evidence, references/assets, scope, and replay example. | Explicitly reuse C4 as the only registry and memory review as the only promotion gate. No auto-install, auto-enable, or second skill registry. |

## Current source checkouts

| Repository | Commit (commit date) | License | Local source root | Exact files examined |
|---|---|---|---|---|
| [Renovate](https://github.com/renovatebot/renovate) | `ae4be1695755a20b1fe88fc94f23e2bf83d23e8d` (2026-10-02) | AGPL-3.0 (`license`) | `D:/Atlas-x-prep-sources/Renovate` | `lib/workers/repository/updates/generate.ts`; `lib/workers/repository/updates/branchify.ts`; `lib/workers/repository/update/pr/index.ts`; `docs/usage/faq.md` |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | `a8c8fb377761fc7c562f19db1d9da75bba413cb9` (2026-10-02) | MIT | `D:/Atlas-x-prep-sources/OpenHands` | `src/api/conversation-service/agent-server-conversation-service.api.ts`; `src/api/conversation-service/agent-server-conversation-service.types.ts` |
| [OpenAI Codex](https://github.com/openai/codex) | `50b4c5e58c1b89f3d1b74155cc1cc1716c2be208` (2026-10-02) | Apache-2.0 (`LICENSE`; repository contains separately licensed components) | `D:/Atlas-x-prep-sources/Codex` | `codex-rs/worktree/src/lib.rs`; `codex-rs/worktree/src/git.rs`; `docs/sandbox.md`; `docs/execpolicy.md` |
| [Hermes Agent upstream](https://github.com/NousResearch/hermes-agent) | `84892e5bd6652f7b04f3a76366d78953fe81ee68` (2026-10-02) | MIT | `D:/Atlas-x-prep-sources/HermesAgentUpstream` | `hermes_cli/goals.py`; `hermes_state_sessions.py`; `hermes_state_compression.py`; `cron/monitor.py`; `cron/scheduler.py`; `cron/scheduler_detached_worker.py`; `hermes_cli/service_manager.py`; `gateway/run_goals.py` |

Atlas consumes the forked Hermes dependency at `D:/hermes-agent`, currently pinned by `core/pyproject.toml` to `e287231d7906bcce5bc373d20fb2e3e1e6427220` (MIT, upstream remote `NousResearch/hermes-agent`; fork remote `unicorn-Y/hermes-agent`). The upstream clone above is a fresh comparison reference, not the current dependency pin. Do not update either pin as a side effect of preparation.

## Official implementation references

- Renovate automatically creates one branch/PR per update and can require approval for every update through `dependencyDashboardApproval`: [Renovate FAQ](https://docs.renovatebot.com/faq/), [dependency dashboard approval](https://docs.renovatebot.com/configuration-options/#dependencydashboardapproval).
- Codex documents sandbox and command approval as separate controls: [Codex sandbox](https://developers.openai.com/codex/security), [Codex exec policy](https://developers.openai.com/codex/exec-policy/). X5 adopts the review boundary, not a parallel Atlas permission model.
- Atlas memory promotion and goal-knowledge review code is present in `core/atlas/memory/__init__.py` (`review_goal_knowledge_refinement`, `review_goal_knowledge_proposal`, `review_goal_experience`); this existing review authority remains mandatory.

## X5 proposed operating contract

1. Watch only an allowlist whose canonical source and check interval are approved. A failed fetch is `unknown/error`, never “no change”.
2. Compare source fingerprints first. Identical source fingerprint yields a quiet result and zero model calls.
3. For a changed source, retain raw source metadata, commit/tag, date, license, changed file list and patch/diff hashes; then classify by deterministic rules. Use a model only on a real change when deterministic mapping cannot classify it.
4. Draft a taskbook and parity proposal. Never edit `CORE-PARITY.md`, the production pin, skills, or source files automatically.
5. Approval is bound to taskbook hash, base SHA, source evidence, owned paths, and the permitted worktree/test commands. Revocation, base drift, or taskbook edits invalidate approval.
6. Create a dedicated branch/worktree; run only taskbook-scoped fake regression and required focused tests. Record exact command, exit status, selected tests, and artifact hashes.
7. Produce a merge proposal and stop. A human reviews code, evidence, provenance/license and parity before merge; there is no auto-merge path.

