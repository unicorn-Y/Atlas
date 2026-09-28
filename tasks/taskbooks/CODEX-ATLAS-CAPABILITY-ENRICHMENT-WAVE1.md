# CODEX-ATLAS-CAPABILITY-ENRICHMENT-WAVE1

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
CODE_BASE_HEAD: c4d17f4ce9e48b1692252c4e4bbeec3a7739270b
PREDECESSOR: CODEX-ATLAS-INTEGRATION-DEBUG-WAVE1

## Mission

Do one bulk capability-enrichment wave.

The installation/debug foundation is accepted.

Now add the highest-value mature Agent behaviors from first-tier projects in ONE pass.

Do not split into feature-specific taskbooks.

Do not redesign Atlas core.

Use direct SDK/library/upstream patterns where practical.

## Core rule

For each capability:

```
reuse mature implementation/pattern
→ thin Atlas adapter
→ one real smoke
→ continue
```

Do not stop to perfect one item before wiring the rest.

## 1. Hooks lifecycle — Claude/Gemini/ZCode style

Add one normalized Atlas hook bus.

Minimum hook points:

- before_model
- after_model
- before_tool
- after_tool
- before_compact
- after_compact
- before_response
- after_response
- agent_stop
- subagent_start
- subagent_end

Requirements:

- hooks are optional;
- failures are isolated and visible;
- normal FULL_ACCESS tool execution is not converted into approval prompts;
- existing MemoryOS/Skill logic is not rewritten.

Use hooks as the mounting point for later MemoryOS reflection/guards.

Smoke:
- register one hook;
- run a normal Agent turn/tool call;
- prove ordered hook events.

## 2. Subagent/delegation — Claude/Hermes style

Add ONE disposable subagent capability.

Minimum:

`delegate_task(goal, context?, tool_profile?)`

Requirements:

- independent context/session;
- bounded lifetime;
- returns result/evidence to parent;
- can use Atlas shared tool bridge;
- no persistent multi-agent chat framework;
- no team orchestration UI.

Prefer reusing an existing backend/session abstraction rather than creating another Agent runtime.

Smoke:
- parent delegates a small repo investigation;
- subagent uses one Atlas tool;
- result returns to parent.

## 3. CodeAct / execute_code — Hermes style

Add a code-orchestrated tool path for mechanical multi-step work.

Goal:

```
LLM decides workflow once
→ Python executes several Atlas tools
→ compact result returns
```

Requirements:

- expose Atlas tool bridge to the execution environment;
- preserve FULL_ACCESS by default;
- capture stdout/stderr/result;
- bounded process lifecycle;
- no new sandbox requirement;
- no need for LLM round-trip per mechanical tool call.

Smoke:
- execute code that performs at least 3 tool operations;
- return one compact result.

## 4. Context maintenance — Codex/OpenCode style

Add minimal maintenance pipeline, not a new Agent.

Capabilities:

- session summary snapshot;
- project/task state snapshot;
- compact trigger;
- title/summary maintenance if already cheap.

Before compaction, preserve:

- goal;
- current project state;
- unresolved work;
- important user constraints;
- active process/tool state references;
- useful memory refs.

Mount through `before_compact` / `after_compact` hooks.

Do not replace the current conversation store.

Smoke:
- create long synthetic context;
- compact;
- prove goal/project/unresolved state survives.

## 5. System reminders — Pydantic Harness style

Add lightweight reminders during long tasks.

Examples:

- current goal;
- do-not-do constraints;
- verification requirements;
- FULL_ACCESS policy;
- current plan state.

Requirements:
- no giant prompt injection;
- configurable cadence/trigger;
- avoid repeating every turn.

Smoke:
- long synthetic turn sequence;
- reminder appears at configured point;
- no duplicate spam.

## 6. Trajectory reviewer — Pydantic Harness style

Add an OPTIONAL live reviewer path.

This is not mandatory for every task.

Contract:

`review_trajectory(recent_events, goal) -> continue | corrective_guidance`

Requirements:

- separate model/backend configurable;
- default disabled for speed;
- when enabled, can inject concise corrective guidance;
- no automatic task cancellation unless a hard runtime failure occurs;
- store review evidence.

Smoke with deterministic reviewer:
- worker trajectory intentionally drifts;
- reviewer emits correction;
- parent receives correction.

## 7. Shadow Git checkpoint — Gemini CLI style

For coding/file tasks, add independent task snapshot/restore.

Requirements:

- do NOT pollute user's repo;
- use Atlas-owned shadow storage;
- snapshot relevant workspace state before mutation;
- restore task changes on request;
- do not touch unrelated user files.

Minimum API/capability:

- create_checkpoint
- list_checkpoints
- restore_checkpoint

Smoke:
- checkpoint temp repo;
- modify file;
- restore;
- exact original content returns.

## 8. Memory reflection/promotion bridge — Letta/Hermes style

Do NOT replace MemoryOS.

Add a thin reflection stage that can propose:

- fact memory;
- project state;
- decision;
- preference;
- reusable experience/skill candidate.

Keep existing governance:
- proposals/candidates may require existing review path where appropriate;
- no silent protected-state promotion.

Use:
- session history;
- task result;
- reviewer evidence.

Smoke:
- synthetic completed task;
- reflection emits at least one structured candidate;
- candidate reaches existing MemoryOS candidate/governance path.

## 9. Skill/Plugin bundle groundwork — ZCode/Gemini style

Do not rewrite P15 registry.

Extend manifest/schema minimally so one future plugin may declare:

- skills;
- commands;
- MCP servers;
- hooks;
- agents/subagents;
- optional UI metadata.

Wave 1 only needs:
- schema/manifest;
- discovery;
- normalized registry representation.

Do not build marketplace UI.

Smoke:
- one fixture plugin bundle;
- discover all declared components;
- existing plain Skill remains compatible.

## 10. Agent backend retry of known degraded integrations

Do not spend the wave on auth.

At end only:

- retry Claude direct SDK path if local environment permits;
- retry Codex if authentication appeared;
- retry ZCode if provider config appeared;
- retry Browser Use if gateway credential changed;
- retry DBOS if database config appeared.

If still blocked, report degraded and continue.

## 11. One unified enrichment smoke

Run one or a few deterministic scenarios proving the pieces compose.

Preferred scenario:

```
checkpoint
→ parent Agent starts task
→ hook fires
→ delegate small investigation
→ execute_code performs mechanical tool work
→ reminder fires
→ optional trajectory reviewer corrects drift
→ task completes
→ reflection proposes memory/experience
→ restore checkpoint in isolated fixture
```

Not every step needs a real paid model.
Deterministic/local test providers are acceptable for lifecycle tests.

## 12. Anti-complexity rules

Do NOT:

- replace AgentBackend contract;
- introduce a second CapabilityBus;
- create a workflow DSL;
- build a multi-agent team framework;
- add per-component settings pages;
- create one taskbook per capability;
- redo Computer Use;
- redo Browser Use;
- redo DBOS setup;
- start voice/mobile/camera;
- globally fix unrelated Ruff debt.

## 13. Verification

Run only relevant regressions:

- Agent/core/session tests;
- P18X integration tests;
- P18A local execution;
- MemoryOS tests touched by reflection;
- Skills/P15 tests touched by plugin schema;
- server tests;
- frontend only if changed;
- Ruff changed files;
- pip check;
- git diff --check;
- packaged backend smoke if packaging/runtime files changed.

## 14. Delivery

Write:

`tasks/results/CODEX-ATLAS-CAPABILITY-ENRICHMENT-WAVE1.result.md`

Include:
- capability matrix;
- upstream inspiration/source for each capability;
- exact files;
- smoke evidence;
- remaining degraded integrations;
- any dependency/license changes.

Commit + push.

## Stop rule

This remains ONE wave.

No FIX1/FIX2.

If one enrichment capability hits a true blocker, mark it degraded and continue the rest.

## Success

Success means Atlas gains mature Agent behavior—not just more installed packages—while preserving the shared runtime created by P18X.
