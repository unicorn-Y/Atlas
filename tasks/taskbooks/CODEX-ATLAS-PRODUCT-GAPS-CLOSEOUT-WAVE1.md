# CODEX-ATLAS-PRODUCT-GAPS-CLOSEOUT-WAVE1

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
CODE_BASE_HEAD: eb6a659180e044cde381c98d5e709870e5756a48
PREDECESSOR: CODEX-ATLAS-REAL-WORLD-AGENT-E2E-WAVE1

## Mission

Fix the real product gaps exposed by the first real-world E2E wave, then rerun acceptance.

This is ONE closeout task.

Do not split desktop / packaged / browser / metadata into separate tasks.

Do not add new architecture.

## 1. Make normal Atlas Computer Use hybrid and target-addressed

Current problem:
the normal Agent still receives the native foreground-oriented `ComputerUseRuntime`, while Cua Driver is only separately registered as a capability.

Fix the normal `computer_*` execution path so mature target-addressed Cua/UIA behavior is actually used.

### Required behavior

Keep the existing five model-facing families:

- computer_observe
- computer_window
- computer_mouse
- computer_keyboard
- computer_clipboard

Do NOT expose the entire raw Cua tool catalog to the LLM.

Use a thin hybrid router/adapter or the smallest equivalent change.

Routing intent:

1. Window-targeted semantic/background action -> Cua Driver first.
2. UIA semantic fallback -> pywinauto where useful.
3. Screen/global coordinate action -> existing native ComputerUseRuntime.
4. If Cua reports background action unavailable and the task permits foreground interaction -> retry only that action with foreground delivery.
5. Keep native SendInput as fallback.

Inspect the installed Cua Driver tool schema at runtime rather than guessing unsupported arguments.

### Model-facing target fields

Extend the existing computer tool schema only as needed for target-addressed actions.

Useful optional fields may include:

- window_id
- pid
- snapshot_id
- element_index
- delivery_mode

Do not create duplicate Cua-specific model tools unless an upstream constraint makes it unavoidable.

### Observation

For a target window, prefer a Cua window state when available so the Agent can receive:

- screenshot;
- accessibility tree;
- snapshot/element handles.

Desktop/global screenshot may continue through native capture.

## 2. Close the real Notepad workflow safely

Use an isolated temporary file.

Goal-level flow:

```
read source facts
→ open the exact temporary document
→ identify the exact Notepad window/document/editor target
→ edit through target-addressed semantic/background action
→ save
→ P18A local_file exact readback
→ close ONLY the test document/tab
```

Requirements:

- do not close unrelated user Notepad windows/documents;
- clean up task-created desktop-note tabs from the prior/this test if they can be identified safely;
- do not rely on "whatever window is foreground";
- background first;
- foreground only for a specific action if required;
- verify the exact temp file content after save.

If modern Notepad reuses an existing process, target the exact window/document/editor through UIA/Cua rather than assuming a new process owns a unique top-level HWND.

## 3. Make Windows regression reflect product reality without faking success

Keep native Computer Use regression coverage.

Do not fake `focus` success if Windows denies foreground activation.

Instead:

- retain a unit/regression for native focus success/failure semantics;
- preserve native SendInput click/type/clipboard coverage;
- add/convert the product-level Windows E2E to prove target-addressed hybrid input succeeds even when foreground activation is denied.

If a small improvement to native `_focus_window` (for example attaching the target input thread as well) makes activation reliable, implement it, but do not depend on undocumented hacks as the sole product path.

## 4. Fix packaged backend responsiveness

Root cause candidate to verify:
`/api/integrations` synchronously runs external CLI probes on the FastAPI event loop.

### Required change

At minimum:

- run `CapabilityBus.status()` / external process probes off the event loop using a worker thread;
- add a small cache of the last registry result to avoid launching every CLI probe on repeated UI refreshes;
- preserve explicit refresh/toggle behavior;
- keep errors visible.

No new health daemon.

### Regression

Create a deterministic test where one capability probe intentionally blocks/sleeps.

While `/api/integrations` is probing, prove another endpoint such as:

- /api/health
- /api/settings/configuration
- /api/conversations

remains responsive.

This test should fail on the old implementation and pass after the fix.

## 5. Rerun full packaged acceptance

After the responsiveness fix:

- npm run dist:win;
- run the opt-in packaged clean-user acceptance;
- complete conversation + restart/history assertions;
- verify shared MCP/runtime path;
- verify graceful shutdown;
- verify no Atlas backend/Node residue.

The test must proceed beyond health and no longer fail on follow-up HTTP reads.

Use the existing local deterministic provider. Do not depend on the user's invalid external Gemini token.

## 6. Prove browser through the normal Atlas Agent

Use the deterministic local web form fixture.

Run through normal `AgentOrchestrator.run()`.

The model/provider should select Atlas-exposed browser tools (prefer Playwright MCP) to:

- open page;
- read source data from a local file;
- fill fields;
- submit;
- verify DOM result;
- report completion.

Do not count direct `agent-browser` CLI driving as this acceptance.

No new browser dependency.

## 7. Fix MemoryStore message metadata

This is a small persistent regression.

Update `get_conversation_messages()` to return stored metadata.

Requirements:

- select the metadata column;
- decode JSON to dict;
- invalid/empty legacy value safely becomes {};
- `test_message_with_metadata` passes.

Do not perform any MemoryOS redesign.

## 8. Preserve known-good scenarios

Re-run and preserve:

- normal Agent coding E2E;
- checkpoint/restore;
- MemoryOS pending proposal persistence;
- Hermes minimal PONG;
- Codex minimal PONG when available.

Do not spend time on Claude/ZCode/DBOS/Pi environment setup.

## 9. Final product matrix

Report:

| Scenario | Result | Evidence |
|---|---|---|
| Normal Agent coding | | |
| Normal Agent browser | | |
| Windows desktop edit/save | | |
| Hybrid target-addressed Computer Use | | |
| Checkpoint restore | | |
| Memory reflection persistence | | |
| Packaged conversation/restart | | |
| Packaged shutdown/residue | | |

The closeout target is green for the product-owned scenarios.

External account/provider degradations may remain separate.

## 10. Verification

Run relevant suites:

- test_computer_use;
- Agent/enrichment;
- P18A;
- P18X integrations;
- Memory tests including metadata;
- server;
- release acceptance/build scripts;
- frontend tests/build if touched;
- changed-file Ruff;
- pip check;
- git diff --check;
- process residue.

Do not deselect the metadata test after fixing it.

## 11. Delivery

Write:

`tasks/results/CODEX-ATLAS-PRODUCT-GAPS-CLOSEOUT-WAVE1.result.md`

Include:

- exact root causes fixed;
- Cua/native/UIA routing used;
- Notepad target/save/readback evidence;
- packaged timeout root cause/evidence;
- normal-Agent browser trace;
- clean regression counts;
- remaining environment-only degradations.

Commit + push.

## Anti-complexity

Do NOT:

- create another Computer Use API;
- expose 56 raw Cua tools to the LLM;
- create a new registry;
- build a workflow DSL;
- redesign Settings;
- add new Agent frameworks;
- create FIX1/FIX2;
- start voice/camera/mobile.

## Success

Success means the product-owned failures from REAL-WORLD-AGENT-E2E-WAVE1 are closed:

- real target-addressed Windows edit/save works;
- packaged Atlas remains responsive and completes conversation/restart acceptance;
- browser task runs through normal Atlas Agent;
- metadata regression is gone.

Only genuine external account/provider configuration blockers may remain degraded.
