# CODEX-ATLAS-CAPABILITY-ENRICHMENT-WAVE1 Review

REVIEW_RESULT: PASS
DISPOSITION: ACCEPT_AND_ADVANCE_TO_ONE_ENRICHMENT_DEBUG_WAVE
IMPLEMENTATION_HEAD: 2b0fdf39873ccf3c9cd4136572f18edc041326b9

## Independent review conclusion

Capability Enrichment Wave 1 is accepted.

The worker did not create nine isolated mini-frameworks. The implementation stayed compact:

- `core/atlas/agent/enrichment.py`
- `core/atlas/agent/checkpoints.py`
- existing `AgentOrchestrator`
- existing MemoryOS
- existing P15 Skill system
- one read-only plugin bundle parser

That is consistent with the speed-first / reuse-first direction.

## Confirmed real capabilities

### 1. Hooks are in the normal Agent path

The normal `AgentOrchestrator` now emits lifecycle hooks around real model/tool/response execution.

Confirmed hook points include:

- before_model
- after_model
- before_tool
- after_tool
- before_response
- after_response
- agent_stop

Subagent hooks and compact hooks also exist.

The regression test runs an actual model-turn simulation plus a real MCP tool call and verifies hook order.

### 2. Delegation is a real disposable Agent session

`DelegationService` uses the existing `AgentBackendHost`.

It:

- creates an independent session;
- sends a bounded goal;
- collects evidence;
- closes the child session;
- emits subagent lifecycle hooks.

This is the desired Claude/Hermes-style disposable delegation, not a new multi-agent framework.

### 3. CodeAct is real

`CodeActRuntime` starts a bounded Python child process and exposes the canonical Atlas tool bridge.

The smoke performs three real P18A operations and returns one compact result.

This is materially useful and should be preserved.

### 4. Shadow Git checkpoint/restore is real

The checkpoint store:

- uses Atlas-owned storage outside the user's repository;
- scopes files explicitly;
- avoids modifying the user's real `.git`;
- can restore exact file content;
- leaves unrelated files unchanged.

Normal `local_file` mutations now create checkpoints before mutation.

### 5. Trajectory reviewer is actually connected to tool execution

When enabled, the reviewer receives recent execution events after tool work and may inject concise corrective guidance into the next model turn.

Reviewer failures do not stop the main task.

Evidence is also written through the existing reflection store.

### 6. Memory reflection respects governance

The implementation does not directly promote facts or protected state.

Normal Agent completion runs the reflection path and emits structured reflection output.

The existing MemoryOS extraction/governance flow still controls actual memory promotion.

### 7. Plugin bundle groundwork is intentionally small

`atlas-plugin.json` discovery supports:

- skills
- commands
- MCP servers
- hooks
- agents
- optional UI metadata

Plain P15 Skills remain compatible.

No marketplace/runtime activation framework was prematurely built.

### 8. Validation is sufficient for this milestone

- new enrichment tests: 12 passed;
- related regressions: 354 passed / 1 pre-existing failure / 2 skipped;
- changed-file Ruff: pass;
- pip check: pass;
- git diff --check: pass.

The single MemoryStore metadata test failure is outside the changed implementation and does not justify blocking this feature wave.

## Real gaps found by independent review

These are small convergence gaps and belong in ONE debug wave.

### A. System Reminder uses the wrong goal source

Current reminder construction uses:

`state["messages"][-1].content`

After several tool rounds, the last message may be a ToolMessage or generated state, not the original user goal.

Use:

`state["runtime"].goal`

as the canonical goal.

### B. Context compaction exists but is not yet an automatic normal-run maintenance path

`ContextMaintenance.should_compact()` and `compact()` are implemented and exposed, but normal Agent execution does not yet automatically trigger the maintenance snapshot when context exceeds threshold.

The debug wave should add a minimal automatic trigger before model execution.

Do not implement a second context system.

### C. Reflection-generated structured proposals are not all persisted into the MemoryOS candidate queue

The current reflection bridge returns new structured candidates such as:

- experience
- project_state
- decision
- preference

but only the pre-existing `extract_conversation_candidates()` path is guaranteed to create real pending MemoryOS rows.

Therefore the new reflection output is partly advisory/event-only.

The debug wave should persist eligible reflection proposals into an existing governed/pending proposal mechanism without auto-promotion.

Protected state rules must remain intact.

### D. Trajectory reviewer is injectable but not yet operationally configurable

The runtime path exists, but the normal Atlas config does not yet provide a simple switch/backend/model callback factory.

Add only a small config path:

- disabled by default;
- backend/model optional;
- deterministic test callback remains supported.

Do not build a reviewer UI.

### E. Plugin bundle is discovery-only, which is correct for this wave

No defect here.

Do not activate plugin commands/hooks/agents yet in the debug wave unless trivial.

The next major plugin activation work can happen after the Agent runtime is proven in a real combined scenario.

## Environment degradations remain non-blocking

Do not hold the queue for:

- Codex login;
- Claude Windows CLI shim;
- Browser Use missing/rejected gateway credentials;
- DBOS DB configuration;
- ZCode provider configuration.

## Review decision

PASS.

Proceed to one concise Enrichment Debug Wave.

Do not create feature-specific FIX tasks.
