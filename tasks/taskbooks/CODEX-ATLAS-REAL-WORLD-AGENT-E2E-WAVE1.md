# CODEX-ATLAS-REAL-WORLD-AGENT-E2E-WAVE1

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
CODE_BASE_HEAD: 71572877b782e666452893c564562001938e23ea
PREDECESSOR: CODEX-ATLAS-ENRICHMENT-DEBUG-WAVE1

## Mission

Stop building internal Agent machinery.

Use the Atlas that now exists to complete realistic end-to-end tasks.

This is ONE real-world acceptance wave.

The objective is to answer:

**Can Atlas now behave like a useful local Agent rather than a collection of individually tested capabilities?**

Do not split this into component tasks.

## 1. Real coding task

Create an isolated temporary Git repository representing a small but non-trivial project.

Through the normal Atlas Agent path, give a goal-level request such as:

> Inspect this repository, find the cause of a failing behavior, modify the implementation, run verification, and explain the result.

The Agent should choose/use capabilities naturally.

Required evidence:

- inspect repository;
- use local_file/local_shell/local_git;
- use repo-map/ast-grep or equivalent coding intelligence at least once when relevant;
- mutate source;
- automatic checkpoint before mutation;
- run tests;
- inspect git diff/status;
- final answer includes real verification evidence.

Do not script the exact tool sequence in the test.

A deterministic model/provider may be used only if it still decides among normal Atlas-exposed tools based on the goal.

## 2. Real Windows desktop task

Use a real Windows GUI workflow.

Preferred:

- create a text/data file;
- launch File Explorer and/or Notepad;
- observe screen/window state;
- open/edit/save through Computer Use;
- verify result through P18A local_file.

Use:

- Cua Driver when working;
- pywinauto semantic fallback where useful;
- existing native P18B fallback otherwise.

The success criterion is the task outcome, not backend purity.

Do not disturb unrelated existing user tabs/windows.

## 3. Real browser task

Use the strongest currently functioning route.

Priority:

1. Browser Use Agent if credentials are available;
2. Playwright MCP;
3. BrowserSession/structured fallback.

Use a deterministic local web page/app fixture so no external site account is required.

Goal-level request example:

> Open the local app, fill the form based on information from a local file, submit it, verify the page result, and report what happened.

Required:

- browser navigation;
- read local source data through Atlas;
- form/input action;
- click/submit;
- verify resulting DOM/page state.

If Browser Use remains credential-blocked, the real task may complete through Playwright MCP and Browser Use stays degraded.

## 4. Cross-capability task

Run at least one task that naturally crosses capability classes.

Preferred chain:

```
read local project/file
→ reason
→ modify/generate artifact
→ open or verify in browser/desktop GUI
→ inspect result
→ final response
```

Use normal Atlas Agent execution.

Do not manually call each capability from the test harness in a hard-coded sequence.

## 5. Delegation / CodeAct behavior

During at least one realistic scenario:

- allow the Agent to use `delegate_task` when a bounded investigation is useful;
- allow `execute_code` for mechanical multi-tool work.

Do not force both if the task genuinely does not benefit from them.

At least one of the two must be used in a real task.

## 6. Checkpoint / restore acceptance

Prove both sides:

- normal mutation automatically creates a checkpoint;
- one deliberate isolated test restores a changed file correctly.

Do not restore or alter unrelated user files.

## 7. MemoryOS learning acceptance

After a successful realistic task:

- reflection proposals should be created;
- they must remain pending/advisory;
- restart MemoryOS;
- proposals still exist;
- no protected/active fact is silently promoted.

Do not add another memory feature.

## 8. Packaged desktop/runtime acceptance

This wave must include a packaged or installed Atlas path.

At minimum verify:

- backend starts from packaged build;
- CapabilityBus loads;
- P18A local execution works;
- shared MCP bridge works;
- Computer Use is discoverable;
- browser/coding integrations are discoverable;
- normal Agent conversation can run;
- shutdown is clean.

If a full packaged real-world GUI task is practical, run it.

Do not require source checkout for packaged acceptance.

## 9. External Agent backends — opportunistic only

Retry:

- Hermes;
- Pi;
- Codex;
- Claude;
- ZCode.

Required:

- Hermes/Pi should remain working if environment still supports them.
- Codex/Claude/ZCode auth/provider blockers remain non-blocking.

Do not stop the task for login/account configuration.

Do not ask the user for secrets.

## 10. Product-level failure matrix

At the end produce one matrix:

| Scenario | Normal Agent | CLI | Coding | Browser | Computer | Checkpoint | Memory | Packaged | Result |
|---|---|---|---|---|---|---|---|---|---|

The point is to expose product-level gaps, not library-level health only.

## 11. Anti-complexity

Do NOT:

- create new architecture;
- add another Agent framework;
- add another capability registry;
- create a workflow DSL;
- create one task per failing scenario;
- redesign UI;
- globally clean Ruff debt;
- spend the wave configuring paid accounts;
- start voice/camera/mobile.

If a scenario exposes a real bug:
- fix it directly in this wave if small;
- otherwise record one root-cause item in the result and continue the other scenarios.

## 12. Verification

Run only relevant tests plus the real-world scenario harnesses.

Required:
- Agent/enrichment tests;
- P18A;
- P18B;
- P18X integration tests;
- MemoryOS touched tests;
- server/packaged tests touched;
- changed-file Ruff;
- pip check;
- git diff --check;
- process residue check.

## 13. Delivery

Write:

`tasks/results/CODEX-ATLAS-REAL-WORLD-AGENT-E2E-WAVE1.result.md`

Include:
- actual scenario prompts;
- actual tool/capability traces;
- exact files/artifacts produced;
- verification evidence;
- packaged evidence;
- remaining product-level blockers;
- external environment degradations.

Commit + push.

## Stop rule

This is one acceptance wave.

Do not create FIX1/FIX2.

If one scenario has a true external environment blocker, continue the others.

## Success

Success means Atlas completes multiple realistic goal-level tasks through its normal Agent runtime and demonstrates that CLI, coding intelligence, browser, Computer Use, checkpointing, MemoryOS, and packaging work as one product.
