# CODEX-ATLAS-INTEGRATION-DEBUG-WAVE1

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
CODE_BASE_HEAD: c4b21e77b33e21e24501b52947c7414c30108e4f
PREDECESSOR: CODEX-ATLAS-P18X-BULK-UPSTREAM-INTEGRATION-WAVE1

## Mission

Do ONE concentrated convergence/debug wave.

Do not create per-component FIX tasks.

Wave 1 successfully mounted the upstream components. This wave makes the important ones genuinely usable together inside Atlas.

Priority is real integration, not architecture polish.

## 1. Make external Agent backends actually part of Atlas

### 1A. Fix ACP FULL_ACCESS behavior

Current bug:
`ACPBackend.EventClient.request_permission()` always returns `DeniedOutcome()`.

Change default Atlas ACP behavior to the ACP-supported allow/selected permission outcome appropriate to the request.

Requirements:

- default = FULL_ACCESS;
- no user prompt for each tool;
- do not deny normal tool execution;
- if the ACP protocol supplies multiple permission options, select the broadest normal allow option rather than inventing a custom response;
- keep explicit restricted mode possible only if Atlas config later opts into it.

Test the permission callback independently.

### 1B. Add ONE shared Atlas tool/capability bridge for external Agents

External Agent sessions must be able to access Atlas capabilities without reimplementing them per backend.

Preferred shape:

`Atlas Capability/Tool Bridge -> MCP -> external Agent session`

At minimum expose:

- P18A local execution tools;
- native/selected Computer Use;
- useful coding capabilities;
- Atlas MCP access or selected registered MCP tools.

For ACP backends, stop creating sessions with an always-empty `mcp_servers=[]`.

Pass the Atlas bridge/server descriptor supported by the ACP SDK.

Do not create a second tool implementation.

Smoke:
- external backend receives/list tools from Atlas bridge;
- one external Agent uses one Atlas local tool through that bridge when auth/backend availability permits.

If a backend cannot accept MCP, keep its own supported integration path; do not block all backends.

## 2. Fix/verify Agent backends as a group

### Codex

- preserve ACP adapter;
- use existing local auth if present;
- do not ask user interactively during automated run;
- if not authenticated, keep status `misconfigured`, but ensure code path is otherwise complete;
- after authentication is available, no additional code change should be required.

### Claude

- use official Claude Agent SDK and/or validated Claude ACP wrapper;
- diagnose `CLIConnectionError`;
- distinguish missing auth/CLI from code/protocol error;
- if auth is absent, remain degraded without blocking wave.

### Hermes

Do not assume generic line protocol.

Inspect actual installed Hermes CLI/package/API.

Use the simplest stable integration that supports:

- start/session;
- prompt;
- streamed or final response;
- cancel/close if available.

Run one real prompt smoke.

### Pi

Keep working RPC integration.

Check current safe compatible release for the npm audit issue.

Upgrade only if compatible; do not downgrade functionality just to silence audit.

### ZCode

Inspect the actual installed/current ZCode CLI/runtime.

Fix:
- version detection;
- start command;
- protocol mapping.

Run one real prompt round-trip.

ZCode currently also serves as the user's external monitor/dispatcher. Do not disrupt that running workflow; use isolated test process/session.

## 3. CUA: close one real useful Windows workflow

Do not redesign Computer Use.

Keep:

- Cua primary candidate;
- native P18B fallback;
- pywinauto semantic helper.

Fix the existing Notepad chain:

`launch -> observe -> type unique marker -> save to isolated temp file -> P18A local_file exact readback -> close`

Pass once.

If CUA's current tool path cannot reliably save, use pywinauto semantic action or native P18B fallback through the common Computer Use selection layer.

The goal is a working hybrid backend, not purity.

## 4. Browser Use: expose the actual Agent task capability

Current adapter only opens/navigates/reads state.

Add a thin high-level path using upstream Browser Use Agent API:

`browser_task(goal, optional start_url/model/session options)`

Do not duplicate Playwright actions.

Smoke on deterministic local page:
- goal asks Agent to fill a field, click a button, and report changed result;
- verify the page effect.

If model credentials are unavailable, keep Browser Use Agent path degraded but preserve the working BrowserSession adapter and Playwright MCP path.

## 5. DBOS: make it real if local DB permits

Current adapter only reports status.

Try the simplest supported local DBOS setup already available on the machine.

Do not require Docker if a local PostgreSQL/system database is available.

Implement minimal:

- start durable task;
- checkpointed steps;
- resume state query.

Smoke:
- A executes once;
- B executes once;
- intentional interruption;
- resume;
- completed steps not duplicated.

If database authentication/config cannot be resolved from existing machine configuration without user secrets, mark DBOS `misconfigured` and continue. Do not block the wave.

## 6. Integration status must reflect reality

CapabilityBus/API should distinguish:

- installed;
- available;
- authenticated/configured;
- connected;
- smoke-verified if practical.

Do not report an Agent backend as ready solely because `--version` works.

Do not build a large new health framework; add only fields/state necessary to avoid false-ready status.

## 7. Workspace housekeeping

- Do not delete the user's unrelated DOCX.
- Ignore/clean only generated Aider/test/package artifacts.
- No broad recursive deletion outside known generated paths.

## 8. Concentrated real smokes

After fixes, run one matrix, not separate taskbooks:

| Component | Discover | Start | Real Call | Atlas Bridge | Packaged | Result |
|---|---|---|---|---|---|---|
| Codex | | | | | | |
| Claude | | | | | | |
| Hermes | | | | | | |
| Pi | | | | | | |
| ZCode | | | | | | |
| CUA | | | | | | |
| Browser Use | | | | | | |
| Playwright MCP | | | | | | |
| DevTools MCP | | | | | | |
| Serena | | | | | | |
| ast-grep | | | | | | |
| Repo Map | | | | | | |
| DBOS | | | | | | |

External auth-only blockers are acceptable DEGRADED outcomes.

Code/protocol placeholders are not.

## 9. Regression / packaging

Run:

- P18X tests;
- P18A local execution;
- P18B Computer Use;
- MCP;
- relevant server tests;
- frontend tests/build if touched;
- Ruff;
- pip check;
- git diff --check;
- packaged backend integration registry;
- process cleanup for processes started by this wave.

Do not run unrelated giant test matrices unless a change touches them.

## 10. Delivery

Write:

`tasks/results/CODEX-ATLAS-INTEGRATION-DEBUG-WAVE1.result.md`

Include:
- exact fixed blockers;
- real-call evidence;
- remaining environment/auth-only blockers;
- final integration matrix;
- exact dependency changes;
- npm audit state;
- packaged state.

Commit and push.

## Stop rule

This remains one wave.

Do not create FIX1/FIX2.

If Codex/Claude remain unauthenticated, record that and finish the rest.

If one optional component remains blocked by credentials, do not hold the whole task.

## Success

Success means Atlas has moved from “17 integrations registered” to “the important integrations actually talk through a shared Atlas runtime”, with only genuine environment/auth blockers left.
