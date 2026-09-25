# CODEX-ATLAS-P7B-TRUE-STREAMING

STATUS: READY  
WORKER: Luna  
BASE_BRANCH: main  
REVIEWED_PREDECESSOR: CODEX-ATLAS-P7A-RUN-ISOLATION  
PREDECESSOR_HEAD: 57a88a6ea631a5ff850c767e9d549ac40940609f

## Goal

Make `AgentOrchestrator.run()` genuinely stream events while the LangGraph run is still executing.

Do only this stage. Do not work on Electron backend auto-start, history UI, MCP configuration, API keys, Markdown, settings, packaging, MemoryOS, or other P7/P8 work.

## Current verified problem

In `core/atlas/agent/__init__.py`:

- `run()` still calls `self._graph.ainvoke(...)`.
- It waits for the graph to finish.
- Only after completion does it iterate `result["pending_events"]`.
- When MCP tools are available, `_think_node()` uses `acompletion(..., stream=False)`.

Therefore the UI cannot receive genuine early `message.delta` events.

P7A already moved cancel/pause/approval hooks into per-run `AgentRunContext`. Preserve that isolation.

## Required implementation

### 1. Per-run event queue

Extend `AgentRunContext` with a per-run `asyncio.Queue`.

Do not put an event queue on `self`.

Each call to `run()` must have its own queue.

### 2. Emit events immediately

`_think_node()` and `_execute_tools_node()` must publish runtime-facing legacy events to the per-run queue when they happen:

- text delta -> `{"type":"chunk", ...}`
- parsed tool call -> `{"type":"tool_call", ...}`
- tool completion -> `{"type":"tool_result", ...}`
- approval request -> existing approval flow remains compatible

Do not wait for graph completion to expose these events.

### 3. Make run() producer/consumer

Recommended structure:

- create per-run context + queue
- create an internal async task that executes the graph
- while that task is running, `run()` consumes queue items and `yield`s them immediately
- on completion, persist the final assistant response exactly once
- emit `done`
- use a sentinel or equivalent termination mechanism
- clean up the graph task if the consumer is cancelled

Do not leak background tasks.

### 4. Streaming must work even when tools are registered

Remove the behavior:

`if tools: stream=False`

Normal assistant text must stream even when the model was given tool definitions.

Handle streamed tool-call fragments correctly.

Aggregate tool-call fragments by their stream index/id, including fragmented JSON arguments, then construct the final LangChain `AIMessage(tool_calls=...)`.

Malformed tool-call JSON must produce a controlled error or safe fallback; it must not crash unpredictably.

### 5. Preserve final state

Streaming must not break:

- full assistant response persistence in `MemoryStore`
- tool loop behavior
- Runtime Protocol 1.2 mapping in `core/atlas/server.py`
- approval flow
- cancel/pause controls
- resume/replay behavior at server level

Do not change the wire protocol in this task.

## Required tests

Use mocks/fakes only. Do not call a paid API.

### A. True early streaming

Add a fake async model stream:

- emit text chunk A
- await a short delay
- emit text chunk B
- await a short delay
- emit text chunk C

Consume `AgentOrchestrator.run()`.

Prove that chunk A can be received before the fake model stream / graph has completed.

A test that only checks final event order is insufficient.

Suggested test name:

`test_run_yields_chunk_before_graph_completion`

### B. Tool-call fragment reconstruction

Simulate streamed tool-call fragments such as:

- fragment 1: id/name
- fragment 2: arguments `{"path":`
- fragment 3: arguments `"README.md"}`

Assert the agent reconstructs:

`{"path":"README.md"}`

and invokes the fake MCP tool with the correct arguments.

### C. Keep P7A isolation covered through run()

P7A code is accepted, but its new tests call `_execute_tools_node()` directly.

Add at least one real `AgentOrchestrator.run()` concurrency test proving two simultaneous runs keep their per-run control contexts separate. Prefer covering cancel or approval.

This is a required verification follow-up; do not redesign P7A.

### D. Existing suite

Run:

`cd D:\Atlas\core`
`python -m pytest tests/test_agent.py -v`
`python -m pytest tests -q`

If an external MCP-only test fails because of a known environment dependency, report it explicitly. Do not hide failures.

## Scope guard

Allowed primary files:

- `core/atlas/agent/__init__.py`
- `core/tests/test_agent.py`

Touch another file only if technically necessary to preserve current runtime behavior, and explain why in the result.

Do not modify frontend UI in this task.

## Git delivery

Before commit:

- `git status --short`
- `git diff --check`
- inspect `git diff`

Do not commit secrets or local config.

Commit message:

`feat: stream agent events during execution`

Push:

`git push origin main`

Then verify local HEAD equals remote main HEAD.

## Result file

Create:

`tasks/results/CODEX-ATLAS-P7B-TRUE-STREAMING.result.md`

It must contain:

- RESULT: PASS / PARTIAL / BLOCKED / FAIL
- BASE_HEAD
- FINAL_HEAD
- REMOTE_HEAD
- CHANGED_FILES
- TEST_COMMANDS_AND_RESULTS
- EARLY_STREAMING_TEST: PASS/FAIL
- TOOL_FRAGMENT_TEST: PASS/FAIL
- RUN_CONTEXT_INTEGRATION_TEST: PASS/FAIL
- KNOWN_ISSUES

Commit and push the result file as part of the final delivery.

## PASS gate

PASS only if all are true:

1. first text chunk is observable before graph completion;
2. text still streams when tools are registered;
3. streamed tool-call fragments reconstruct correctly;
4. final assistant response is saved once;
5. existing Runtime behavior is not broken;
6. at least one `run()`-level concurrent context isolation test passes;
7. required tests pass;
8. code + result are committed and pushed;
9. remote main HEAD equals final local HEAD.
