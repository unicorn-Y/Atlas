# CODEX-ATLAS-P18X-BULK-UPSTREAM-INTEGRATION-WAVE1 Review

REVIEW_RESULT: PASS
DISPOSITION: ACCEPT_AS_BULK_INTEGRATION_BASELINE_AND_ADVANCE_TO_CONCENTRATED_DEBUG
IMPLEMENTATION_HEAD: c4b21e77b33e21e24501b52947c7414c30108e4f
IMPLEMENTATION_COMMITS:
- 95b0ca8907e15306cbe090a45f58c279275240c1
- c4b21e77b33e21e24501b52947c7414c30108e4f

## Why this wave passes

Wave 1 was intentionally defined as:

install/detect → register → thin adapter → one minimal smoke where the local environment permits → move on → debug the integrated system afterwards.

The implementation materially achieved that architecture instead of creating per-component micro-projects:

- one normalized CapabilityBus;
- one AgentBackend session contract;
- external process/ACP/Pi adapters;
- one API surface for integrations and external Agent sessions;
- one Settings integration panel;
- P18A/P18B/P15/P7F/P17 retained;
- packaged backend can load the integration registry;
- real smokes succeeded for pywinauto, Playwright MCP, Chrome DevTools MCP, Serena, ast-grep/Aider chain and Pi;
- 42 targeted backend tests passed;
- frontend build + 18 tests passed;
- packaged registry smoke succeeded.

This is enough to accept Wave 1 as the requested bulk-wiring baseline.

The DEGRADED worker status is accurate and is not a reason to repeat Wave 1.

## Real gaps found by independent review

### 1. ACP permission handling currently contradicts Atlas FULL_ACCESS

`core/atlas/runtime/backends.py`:

`EventClient.request_permission()` always returns `DeniedOutcome()`.

That means Codex/Claude ACP sessions may be successfully launched later but still have tool execution blocked by Atlas.

Atlas product requirement remains:

- FULL_ACCESS default;
- no per-tool user prompt by default;
- do not silently downgrade external Agent backends to denied/restricted mode.

This must be corrected in the concentrated debug wave using the ACP SDK's supported permission response/option model.

### 2. External Agent backends are mounted beside Atlas capabilities, not yet truly bridged to them

ACP session creation currently passes:

`mcp_servers=[]`

The result file also correctly notes:

> External backends do not yet receive the full P18A tool set through a shared MCP bridge.

Therefore Codex/Claude/etc. are currently external session adapters, not yet fully integrated Atlas Agents.

The next wave must create one shared Atlas capability/tool bridge rather than duplicate P18A tools inside every backend.

### 3. Hermes backend is only a guessed generic text protocol

`hermes.py` launches:

`hermes --cli chat`

through the generic line-oriented `ExternalProcessAdapter`.

The worker did not smoke this. The result explicitly says the generic stdin adapter may not match Hermes CLI protocol.

This is an implementation gap, not just an environment blocker.

Use Hermes' actual stable CLI/API/package protocol in the debug wave.

### 4. ZCode backend is not validated

`zcode app-server` is wired to the generic text adapter, while version probing already exits 1.

The protocol/start command must be inspected against the installed/current ZCode implementation and a real prompt round-trip must pass.

### 5. Browser Use is only a BrowserSession open/inspect adapter

Current adapter can:

- start browser;
- navigate;
- return text state;
- close.

It does not yet expose the high-level Browser Use Agent task path or fill/click task execution expected by the Wave checklist.

Playwright MCP is healthy and already covers deterministic DOM action. Browser Use should now be upgraded to a real `browser_task(goal)` path, not another DOM wrapper.

### 6. CUA is installed and callable, but its first useful task is not yet closed

Good evidence:

- driver connected;
- 56 tools discovered;
- Notepad observed;
- marker appeared in tab.

Open gate:

- saved file did not read back marker.

This should be debugged once. Keep existing native P18B Computer Use as fallback; do not replace working SendInput.

### 7. DBOS is installed but not integrated as durable execution yet

Current `dbos_backend.py` only reports status.

No:

- durable task;
- checkpoint;
- resume;
- crash/restart smoke.

Do not require Docker specifically. The debug wave should first detect a usable local PostgreSQL/system DB or other DBOS-supported local configuration. If unavailable without user credentials, keep DBOS degraded rather than blocking the wave.

### 8. Pi package has an npm audit high finding

Do not blindly downgrade to an older major version just because npm suggests it.

Debug wave should:

- check whether a newer compatible Pi fixes it;
- upgrade if safe;
- otherwise record the upstream vulnerability and avoid an unnecessary functional downgrade.

### 9. Generated workspace artifacts need housekeeping

Do not delete the user's unrelated DOCX.

Ignore/clean only Atlas-generated artifacts such as:

- Aider cache/history created by smoke;
- temporary package test roots;
- temporary pytest roots.

A narrow .gitignore entry is preferable to broad destructive cleanup.

## What is explicitly NOT required next

Do not:

- redo the CapabilityBus;
- replace the current backend contract;
- split into Codex-FIX / CUA-FIX / ZCode-FIX tasks;
- redesign Settings;
- rewrite native Computer Use;
- start P18C;
- start voice/mobile/camera;
- perform another broad upstream research wave.

## Review conclusion

PASS for Wave 1 as a bulk installation/wiring milestone.

The next task is one concentrated integration debug/convergence wave whose job is to turn the mounted components into a genuinely shared Atlas runtime and close the real degraded paths above.
