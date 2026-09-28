# CODEX-ATLAS-ENRICHMENT-DEBUG-WAVE1

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
CODE_BASE_HEAD: 2b0fdf39873ccf3c9cd4136572f18edc041326b9
PREDECESSOR: CODEX-ATLAS-CAPABILITY-ENRICHMENT-WAVE1

## Mission

Do one short convergence pass on the enrichment capabilities already implemented.

No new broad features.

No per-capability FIX tasks.

The goal is to move the new capabilities from "implemented" to "correctly connected in the normal Atlas Agent path".

## 1. Fix System Reminder goal source

Current issue:

`_think_node()` derives reminder goal from the last message content.

Change it to use the per-run canonical original goal:

`state["runtime"].goal`

Fallback only if that is absent.

Smoke:
- multi-tool run;
- last message is a ToolMessage;
- reminder still contains original user goal, not tool output.

## 2. Make context maintenance automatically trigger in normal runs

Reuse existing:

- `ContextMaintenance.should_compact()`
- `ContextMaintenance.compact()`
- before_compact/after_compact hooks

Do not create a new compaction subsystem.

Before a model call, when configured threshold is reached:

1. build a compact resume-critical context from the current run/conversation;
2. create the maintenance snapshot;
3. add a concise maintenance summary/system message for the continuing turn;
4. emit a `context_compacted` event.

Preserve:
- original goal;
- project/task state if available;
- unresolved plan steps;
- user constraints;
- active process/tool references if available;
- memory references if available;
- session summary.

Do not delete historical conversation rows from MemoryOS.

Do not make real long-context tests expensive; deterministic synthetic history is fine.

## 3. Persist reflection proposals into MemoryOS governance

Current reflection output contains useful structured candidates but some are event-only.

Add the thinnest governed persistence path.

Rules:

- no direct promotion;
- no protected-state auto activation;
- candidates/proposals remain pending/advisory;
- preserve source conversation/run/evidence;
- deduplicate conservatively.

At minimum support persistence of:

- reusable experience;
- project_state;
- decision;
- non-sensitive preference/fact proposal.

If existing MemoryOS tables have a better matching governed proposal type, use it rather than creating another parallel memory database.

Smoke:
- completed synthetic task creates reflection proposals;
- proposals are queryable after restart;
- active facts/protected state remain unchanged until existing approval/governance action.

## 4. Give trajectory reviewer a minimal runtime config path

Keep default disabled.

Add config fields sufficient for:

- enabled;
- backend/model identifier or callback factory selection.

Do not build UI.

If no reviewer backend is configured:
- continue normally.

If enabled:
- reviewer path already in `_execute_tools_node` should run.

Smoke:
- disabled -> zero reviewer calls;
- enabled deterministic reviewer -> corrective guidance reaches next model turn.

## 5. Preserve all existing enrichment features

Do not rewrite:

- HookBus;
- DelegationService;
- CodeActRuntime;
- ShadowGitCheckpointStore;
- plugin bundle discovery;
- shared P18X runtime.

Only fix real integration gaps.

## 6. One combined normal-Agent E2E

Run one deterministic normal `AgentOrchestrator.run()` scenario proving composition:

```
user goal
→ hooks
→ tool call
→ automatic checkpoint before mutation
→ CodeAct or delegation
→ enough turns to trigger reminder
→ optional reviewer correction
→ context maintenance trigger
→ final response
→ governed reflection proposals
```

Not every operation needs a paid external model.

Use deterministic fake/local model streams where appropriate, but the path must be the normal Agent graph, not direct helper calls only.

## 7. Regression

Run:

- enrichment tests;
- Agent tests;
- P18A local execution;
- P18X integration tests;
- MemoryOS tests directly touched;
- P15 Skills tests if touched;
- server tests if API/config touched;
- changed-file Ruff;
- pip check;
- git diff --check.

The known unrelated metadata test may remain documented if unchanged.

## 8. Environment integrations

At the end only, opportunistically retry:

- Codex;
- Claude;
- Browser Use;
- ZCode;
- DBOS.

If environment/config still blocks them, report degraded and continue.

Do not spend the wave on account setup.

## 9. Delivery

Write:

`tasks/results/CODEX-ATLAS-ENRICHMENT-DEBUG-WAVE1.result.md`

Record:
- the four convergence fixes;
- combined E2E evidence;
- MemoryOS persistence evidence;
- regressions;
- remaining environment degradations.

Commit + push.

## Anti-complexity

Do NOT:

- create another Agent runtime;
- create a new memory database;
- add a workflow DSL;
- add plugin marketplace UI;
- add reviewer UI;
- split into FIX1/FIX2;
- redo Computer Use/Browser/DBOS;
- start voice/camera/mobile.

## Success

Success means the enrichment capabilities are no longer isolated helpers: the normal Atlas Agent run actually uses the correct goal reminders, automatic context maintenance, optional live reviewer, checkpointed tool execution, and governed memory reflection.
