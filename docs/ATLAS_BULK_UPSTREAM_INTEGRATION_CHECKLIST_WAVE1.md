# Atlas Bulk Upstream Integration Checklist — Wave 1

STATUS: EXECUTION BASELINE
DATE: 2026-09-28

## 0. Goal

One integration wave. No per-feature task splitting.

The objective is to make Atlas able to discover, start, call, stop, and minimally use a curated set of mature upstream Agent/Computer-Use/Browser/Coding/Durable components first, then debug them as one integrated system.

The rule is:

```
select mature upstream
→ install
→ register
→ thin adapter
→ smoke
→ move on
→ after everything is wired, do concentrated debugging
```

Do NOT require every component to be production-perfect before wiring the next component.

## 1. Non-goal: do not install every project from research

The research document contains many overlapping frameworks. Atlas should not install five competing full Agent frameworks into the same runtime just because they are interesting.

Wave 1 contains only components that add distinct capability or are first-tier Agent backends worth exposing.

Use three buckets:

- A: integrate now into Atlas runtime.
- B: expose as external Agent backend now.
- C: mine later for individual features; do not embed whole framework now.

---

# 2. Bucket A — integrate now

## A1. Existing Atlas FULL_ACCESS local execution

Source: Atlas P18A.

Keep and expose as canonical native tools:

- PowerShell
- cmd
- executable + argv
- process lifecycle
- filesystem
- Git
- arbitrary local paths
- stdout/stderr streaming
- cancellation
- background/detached

Do not replace.

Acceptance:
- registered in CapabilityBus
- visible to all compatible Agent backends
- callable from Atlas Native Agent
- callable from external Agent adapter through bridge where feasible

---

## A2. Cua Driver — primary desktop Computer Use backend

Upstream:
- trycua/cua

Purpose:
- screenshot
- window targeting
- accessibility/UIA
- click/type/scroll
- element targeting
- coordinate targeting
- background window control where supported
- SDK/CLI/MCP surface

Integration target:
- `core/atlas/capabilities/computer/cua_backend.py`
- existing `computer_use.py` remains fallback

Adapter contract:

```
observe()
list_windows()
get_accessibility_tree()
click()
double_click()
right_click()
drag()
scroll()
type_text()
hotkey()
focus_window()
```

Policy:
- primary backend = Cua Driver when available
- fallback = Atlas native ComputerUseRuntime
- semantic Windows fallback may use pywinauto

Smoke:
- Notepad launch
- observe
- type marker
- click/save
- local_file verify

---

## A3. pywinauto — Windows semantic UI fallback

Purpose:
- UIA control tree
- semantic buttons/inputs
- window/control focus
- invoke/select
- control rectangle
- automation id / class / control type

Keep adapter thin.

Do not build a custom UIA framework.

Use when:
- Cua element route unavailable
- native coordinate action is less reliable

---

## A4. Browser Use — free-form browser Agent

Upstream:
- browser-use/browser-use

Purpose:
- high-level browser task execution
- agent/controller/browser/dom separation
- multi-step web workflows

Atlas adapter:

```
browser_task(goal, profile/session, optional start_url)
browser_stop(run_id)
browser_status(run_id)
```

Do not merge Browser Use Agent loop into Atlas core.
Run it as a capability/service.

Smoke:
- open local/static test page
- inspect page
- fill input
- click
- return result

---

## A5. Playwright MCP — structured browser automation

Purpose:
- reliable DOM/accessibility actions
- forms
- navigation
- selectors
- lower token cost than vision

Register as bundled/recommended MCP.

Smoke:
- launch
- tools discovered
- navigate to deterministic local page
- input/click
- verify DOM state

---

## A6. Chrome DevTools MCP — browser debugging

Purpose:
- console
- network
- performance
- page/runtime inspection

Register as MCP.

Smoke:
- attach/open Chromium
- list page
- inspect console/network on deterministic test page

---

## A7. Serena — semantic coding intelligence

Purpose:
- symbol search
- reference search
- LSP-backed navigation
- symbol-level editing

Expose through MCP or native adapter.

Smoke on temporary repo:
- find symbol
- find references
- inspect symbol
- perform one semantic edit if supported
- run P18A test afterwards

---

## A8. ast-grep — AST search/rewrite

Purpose:
- structural search
- structural replacement
- safer bulk refactor

Install CLI and expose via Atlas local execution/coding capability.

Smoke:
- deterministic test repo
- AST search
- dry-run rewrite
- apply rewrite
- verify diff

---

## A9. Aider / Repo Map capability

Purpose:
- compact repository map
- architect/editor patterns

Do not make Aider a primary Atlas Agent.

Wave 1 goal:
- install/enable a repo-map helper or wrap Aider repo-map capability
- expose `repo_map(path, budget)`

Smoke:
- medium fixture repo
- produce symbol/dependency map
- result usable by Atlas Agent

If direct internal reuse is unstable, keep Aider as external helper/CLI rather than copying its internals.

---

## A10. DBOS — durable execution foundation

Purpose:
- durable workflow
- step checkpoint
- resume after process crash/restart

Wave 1 scope:
- install DBOS
- create Atlas durable adapter
- do NOT migrate all current tasks immediately

Adapter:

```
start_durable_task()
checkpoint_step()
resume_task()
get_task_state()
cancel_task()
```

Smoke:
- step A writes marker
- step B writes marker
- intentional crash/interruption
- resume
- A/B not duplicated
- task completes

---

## A11. ACP client / external Agent host layer

Purpose:
Atlas should become a host for external first-tier agents when a stable ACP-compatible surface exists.

Wave 1:
- add protocol abstraction
- no giant protocol redesign
- support external Agent process lifecycle + streamed events

Contract:

```
start_session()
send()
stream_events()
cancel()
resume()
close()
```

If a specific backend does not expose ACP, use its official SDK/CLI/app-server protocol behind the same Atlas adapter contract.

---

# 3. Bucket B — external Agent backends to expose now

These are NOT copied into Atlas core.

Each backend gets a thin adapter implementing the same minimum session contract.

## B1. OpenAI Codex backend

Preferred integration path:
1. stable Codex app-server/protocol if available;
2. official/local CLI process bridge;
3. no copying the whole Rust core.

Minimum features:
- new session
- prompt
- streamed text/tool/progress
- cancel
- resume where exposed
- cwd/project
- model/config pass-through where exposed

Smoke:
- temporary repo
- ask Codex backend to inspect repo
- make one controlled edit
- verify through Atlas P18A

---

## B2. Claude Agent SDK backend

Use official SDK.

Minimum:
- start
- send
- streaming
- tool events
- cancel
- resume
- fork if SDK exposes it
- subagent/hook metadata when practical

Smoke:
- deterministic local repo task
- one tool workflow
- stop/resume

Do not copy proprietary Claude Code internals.

---

## B3. Hermes Agent backend

Integration style:
- external process/service or direct package if stable
- keep Hermes tools isolated behind adapter

Minimum:
- session
- prompt
- streamed output
- delegation event if exposed
- execute_code path if exposed
- memory/session search bridge may be added later

Smoke:
- terminal/file task
- one execute_code or normal tool flow

---

## B4. Pi backend

Purpose:
- embeddable/minimal Agent core
- SDK/RPC style backend

Minimum:
- session
- tool call
- event stream
- cancel
- persistence/resume if exposed

Smoke:
- file task through Atlas bridge

---

## B5. ZCode backend

Purpose:
- first-tier multi-surface coding harness
- desktop/browser/terminal runtime reference

Minimum:
- start CLI/runtime
- session/prompt
- stream
- cancel
- cwd
- tool events

Do not copy full desktop UI.

---

# 4. Bucket C — do not embed whole framework in Wave 1

These projects are valuable, but installing all of them into Atlas core would create duplicate runtimes.

Mine specific features later.

## C1. Cline SDK
Mine:
- agents/core split
- hub daemon
- schedules
- teams

## C2. Microsoft Agent Framework Harness
Mine:
- Provider composition
- BackgroundAgents
- Todo
- Plan/Execute
- Compaction
- telemetry

## C3. Pydantic AI Harness
Mine:
- System Reminder
- Trajectory Judge
- Capability Creation
- durable integration patterns

## C4. Gemini CLI
Mine:
- Shadow Git
- checkpoint/restore
- extension bundle
- A2A server

## C5. Letta
Mine:
- Memory Blocks
- Git-backed MemFS
- Reflection Agent
- memory→skill promotion

## C6. Agent-S / OpenCUA / UI-TARS / UFO
Mine:
- GUI planning
- grounding
- action schema
- screenshot history
- semantic Windows UI
Use only if Cua/native computer backends lack required behavior.

## C7. OpenHands
Mine:
- remote Agent server
- sandbox/runtime architecture

## C8. Goose
Mine:
- Recipes
- ACP provider patterns
- MCP Apps

---

# 5. Minimal Atlas integration architecture

Wave 1 should add only the minimum glue required to mount everything.

```
core/atlas/
├── runtime/
│   ├── backends.py
│   ├── capability_bus.py
│   └── external_process.py
│
├── agents/
│   ├── native.py
│   └── backends/
│       ├── codex.py
│       ├── claude.py
│       ├── hermes.py
│       ├── pi.py
│       └── zcode.py
│
├── capabilities/
│   ├── computer/
│   │   ├── cua_backend.py
│   │   ├── native_backend.py
│   │   └── uia_backend.py
│   ├── browser/
│   │   └── browser_use.py
│   ├── coding/
│   │   ├── serena.py
│   │   ├── repo_map.py
│   │   └── ast_grep.py
│   └── durable/
│       └── dbos_backend.py
```

Do not perform a full package reorganization if it delays integration.
Equivalent minimal paths are acceptable.

---

# 6. Capability registry

Every integrated component must report a normalized status.

Example:

```json
{
  "id": "computer.cua",
  "kind": "computer_backend",
  "available": true,
  "version": "...",
  "source": "trycua/cua",
  "status": "ready|missing_dependency|misconfigured|failed",
  "capabilities": ["observe", "click", "type", "uia"]
}
```

Minimum categories:

- agent_backend
- local_execution
- computer_backend
- browser_backend
- coding_backend
- durable_backend
- mcp_server

Expose one API endpoint / internal registry query to list all.

---

# 7. Installation strategy

## Python dependencies

Install into Atlas environment only where direct import is intended:
- pywinauto
- browser-use
- DBOS integration package
- other small Python SDKs required by selected adapters

## Node tools

Use bundled Node runtime from P16 for bundled MCP/Node integrations where practical.

Examples:
- Playwright MCP
- Chrome DevTools MCP
- Serena if distributed that way
- other MCP servers

Do not depend silently on arbitrary global Node.

## External Agent CLIs

Codex / ZCode / Pi / Hermes:
- detect installed binary/package
- optionally install using documented upstream method
- record exact version
- adapter must clearly report unavailable if not installed

Do not vendor huge upstream repos into Atlas unless necessary.

---

# 8. Configuration

Add one integration section, not one settings page per project.

Example:

```yaml
integrations:
  agents:
    codex:
      enabled: true
    claude:
      enabled: true
    hermes:
      enabled: true
    pi:
      enabled: true
    zcode:
      enabled: true

  computer:
    primary: cua
    fallback: native
    semantic: pywinauto

  browser:
    browser_use: true
    playwright_mcp: true
    devtools_mcp: true

  coding:
    serena: true
    ast_grep: true
    repo_map: true

  durable:
    dbos: true
```

Default local Atlas permission remains FULL_ACCESS.

---

# 9. UI — minimal only

Do not build full management UI in Wave 1.

Add one compact Integration/Capabilities view or API-backed panel showing:

| Integration | Type | Installed | Connected | Version | Last error |
|---|---|---:|---:|---|---|

Actions:
- refresh
- connect/start if needed
- disable/enable
- view error

No redesign.

---

# 10. Wave 1 execution order

This is ONE task. The order below is only installation sequencing, not separate approval gates.

## Stage 0 — baseline
- pull latest main
- record HEAD
- snapshot current dependencies/config
- keep P18A/P18B partial tests

## Stage 1 — integration skeleton
- Capability registry
- AgentBackend interface
- External process/session adapter
- common status/error shape

## Stage 2 — install all Bucket A dependencies/tools
- Cua Driver
- pywinauto
- Browser Use
- Playwright MCP
- Chrome DevTools MCP
- Serena
- ast-grep
- Aider/repo-map helper
- DBOS

Do not stop to perfect each.

## Stage 3 — register all Bucket A capabilities
- computer
- browser
- coding
- durable
- MCP

## Stage 4 — wire all Bucket B Agent backends
- Codex
- Claude Agent SDK
- Hermes
- Pi
- ZCode

Minimum contract only.

If one backend has an environment/license/account blocker, mark it BLOCKED and continue integrating the others.
Do not stop the whole wave for one backend.

## Stage 5 — minimal smokes for every integration
Each integration gets ONE deterministic smoke.

Goal:
- prove Atlas can call it
- do not exhaustively test it

## Stage 6 — one cross-capability end-to-end
Example:

```
Atlas Native or external Agent
→ P18A local_exec creates temp repo
→ Serena inspects symbol
→ ast-grep changes code
→ local test
→ Browser Use opens generated local app
→ Cua observes desktop
→ DBOS records task step
→ final result
```

Not every integration must appear in the same E2E; use 2–3 scenario chains if simpler.

## Stage 7 — packaged Atlas smoke
Confirm integrated registry loads in packaged Atlas.
Only components designed to be bundled must be bundled.
External CLI backends may remain external dependencies if clearly detected.

## Stage 8 — commit and stop
- result file
- exact installed versions
- upstream SHAs/versions where relevant
- list ready/degraded/blocked
- push
- clean status

After this Wave completes, start a separate Concentrated Debug Wave.

---

# 11. Debug Wave — after everything is wired

Do NOT create one FIX task per component.

Create one debug matrix:

| Component | Install | Discover | Start | Basic call | Cross-call | Packaged | Error |
|---|---|---|---|---|---|---|---|

Then fix in priority order:

1. integration cannot start
2. integration corrupts Atlas runtime
3. cross-capability tool/event mismatch
4. packaged build blocker
5. degraded feature
6. UX polish

Debug by root cause groups:
- dependency
- process lifecycle
- protocol/event mapping
- environment/path
- packaging
- auth/config
- model/provider

---

# 12. Hard anti-complexity rules

1. No per-integration architecture document.
2. No per-integration taskbook.
3. No waiting for full verification before wiring the next integration.
4. No reimplementing upstream capability just to avoid adding a dependency.
5. No merging five Agent cores into one codebase.
6. External agents stay external behind adapters.
7. Atlas Native Agent remains usable throughout.
8. One shared Capability registry.
9. One shared AgentBackend contract.
10. One shared event normalization layer.
11. One bulk result file.
12. One concentrated debug wave afterwards.

---

# 13. Definition of “integrated” for Wave 1

An integration counts as wired when:

- dependency/tool is installed or correctly detected;
- version is known;
- Atlas registry reports it;
- adapter can start/connect;
- one real call succeeds;
- failure is surfaced cleanly;
- it can be disabled without breaking Atlas.

It does NOT need every advanced upstream feature in Wave 1.

---

# 14. Wave 1 desired end state

After this task Atlas should be able to say:

```
Agent Backends
✓ Atlas Native
✓ Codex
✓ Claude Agent SDK
✓ Hermes
✓ Pi
✓ ZCode

Computer
✓ Cua Driver
✓ Atlas Native fallback
✓ pywinauto semantic UI

Browser
✓ Browser Use
✓ Playwright MCP
✓ Chrome DevTools MCP

Coding
✓ Serena
✓ ast-grep
✓ Repo Map

Durable
✓ DBOS

Core
✓ P18A FULL_ACCESS
✓ P15 Skills
✓ P7F MCP
✓ MemoryOS bridge retained
```

If some external Agent backend cannot be activated because the local account/API/CLI is unavailable, its adapter still counts as integrated if:
- detection works;
- config surface exists;
- missing dependency/auth status is explicit;
- other integrations continue.

---

# 15. What comes after Wave 1

Only two next jobs:

## Job A — Concentrated Integration Debug

Fix all red/degraded cells from the matrix.

## Job B — Capability Enrichment

Mine Bucket C features in bulk:

- Claude-style hooks/subagents
- Codex-style compaction/session protocol
- Pydantic trajectory judge/system reminders
- Gemini shadow Git
- Letta reflection/memory promotion
- Hermes execute_code/delegation
- ZCode/Gemini plugin bundle
- Cline hub/schedules

Again: one enrichment wave, not one task per feature.

---

# 16. Source/License log

Every integrated upstream must record:

- repo
- version/tag/commit
- license
- install method
- copied/adapted source path if any
- Atlas adapter path

No unattributed code copying.

---

# 17. Success criterion

Wave 1 succeeds when Atlas is no longer a mostly hand-written isolated Agent stack, but a working host/router over mature upstream capabilities.

The target is not architectural elegance.

The target is:

**install first, wire first, prove minimal real calls, then debug the integrated system as a whole.**
