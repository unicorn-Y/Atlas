# CODEX-ATLAS-PRODUCT-GAPS-CLOSEOUT-WAVE1 Result

## Delivery

- Actual post-pull `BASE_HEAD`: `f01de4d34105dd55a15710aed3e544f2af51fdfa` (the taskbook's recorded `CODE_BASE_HEAD` was older).
- Scope stayed within the assigned desktop, integrations, packaged responsiveness, normal-Agent browser, and message-metadata gaps.
- Commit and `origin/main` verification are recorded below after delivery.

## Root causes fixed

1. The five normal `computer_*` tools used the native `ComputerUseRuntime`, while Cua Driver was only registered as a separate capability. Startup now injects Cua into that same runtime. Targeted observation and semantic/background operations use Cua first; cached snapshot elements can use pywinauto UIA when Cua value setting fails. Global/screen operations retain native behavior. The model still sees the existing five tool families, and the Cua tool schema is inspected at runtime so unsupported arguments are filtered and missing required arguments are reported.
2. Native focus activation can be denied by Windows. `_focus_window` now reports that failure honestly. The target-addressed Cua/UIA path succeeds without pretending foreground activation succeeded. Background delivery is first; foreground retry is limited to an explicit foreground request and the same action after a recognized background-unavailable result.
3. `/api/integrations` synchronously ran potentially slow capability CLI probes on the FastAPI event loop, starving follow-up API requests in the packaged app. Status probing and toggles now run in a worker thread, capability results are cached briefly, toggles invalidate the cache, and explicit UI refresh uses `?refresh=true`.
4. `MemoryStore.get_conversation_messages()` selected no metadata column and callers received encoded JSON. It now selects and decodes metadata; invalid, empty, or non-dict legacy values return `{}`.

## Notepad target-addressed edit/save evidence

- P18A read the isolated source facts, then `notepad.exe` opened the exact temporary target document.
- Cua observation identified PID `30536`, HWND `11278348`, editor role `Document`, and snapshot `s00000001`.
- Targeted semantic Cua editing and File-menu save completed. P18A reread the exact target file and confirmed the intended content (`p18a_exact_readback: pass`).
- The exact test tab was located by its UIA `TabItem` and its own child close button; only that test tab was closed. The pre-existing `atlas-cua-probe.txt` tab and Notepad process were preserved.
- The real desktop flow above used the target-addressed Computer Use runtime directly. An extra opt-in `AgentOrchestrator`→Notepad harness attempt failed before any Notepad action: its deterministic provider received a tool-less auxiliary request (`model`, `messages`, `max_tokens`) and could not emit the scripted `local_file` call. That harness was not accepted as passing and was removed; full normal-Agent orchestration through Notepad remains unverified. This does not invalidate the separately completed desktop target/edit/save/readback flow or the normal-Agent browser acceptance.

## Packaged responsiveness and clean-user acceptance

- Prior timeout root cause: synchronous integration CLI discovery blocked the async server loop after the health check, causing follow-up HTTP reads to time out.
- The first acceptance invocation exposed a test harness path mismatch: its default resources path was relative to `core/tests`, while the build output lives under `frontend/windows-release`. The acceptance was rerun with `ATLAS_P17A_RESOURCES_DIR=D:\Atlas\frontend\windows-release\win-unpacked\resources\atlas`; no product behavior was bypassed.
- Final source was rebuilt with `npm run dist:win`; the installer SHA-256 is `69f93d51afaf7dd849934b420b1da5a506124068f52557a90b3ca467e01a5a30`.
- Against that final package, `test_clean_packaged_daily_usability_twice` passed: **1 passed in 104.55s**. It completed conversation and restart/history checks, shared MCP/runtime checks, graceful shutdown, and the test's Atlas backend/Node residue checks.
- A separate process query after acceptance found no process whose executable or command line referenced the packaged Atlas release path.

## Normal-Agent browser trace

`ATLAS_P18X_RUN_AGENT_BROWSER_E2E=1 pytest tests/test_agent_browser_acceptance.py::test_normal_agent_reads_local_facts_and_completes_playwright_form` passed (**1 passed in 8.16s**). The real `AgentOrchestrator.run()` used a deterministic local provider, P18A `local_file` to read the source facts, and the existing Playwright MCP to navigate, inspect the form, fill fields, submit, inspect the DOM result, and report completion. The form fixture verified the submitted name and email. No browser dependency was added.

## Regression evidence

- Combined scoped regression run: **240 passed, 2 skipped in 70.58s** across Computer Use, Agent/enrichment/capabilities, local execution, P18X integrations, MemoryStore/quality, server, and release acceptance/build-script tests.
- Skips were the release-acceptance scenarios that require their separate installer opt-in. The packaged clean-user scenario was run separately and passed as reported above.
- The combined Agent/enrichment run covered normal coding, checkpoint-before-mutation/restore, and MemoryOS reflection candidate governance. The predecessor's isolated acceptance also verified pending proposals survived restart; no active fact is silently promoted.
- Hermes minimal prompt returned `PONG` (exit 0); Codex CLI ephemeral read-only prompt returned `PONG` (exit 0).
- `pip check`: no broken requirements.
- `git diff --check`: passed.
- Ruff passed on the clean changed Python implementation and new acceptance files. The full changed-file Ruff invocation still reports legacy diagnostics on untouched lines in `core/atlas/memory/__init__.py`, `core/tests/test_memory.py`, and one pre-existing line in `core/tests/test_computer_use.py`; no new diagnostics remain in the modified lines.

## Final product matrix

| Scenario | Result | Evidence |
|---|---|---|
| Normal Agent coding | PASS | Scoped Agent/local-execution suite included in 240-pass regression run |
| Normal Agent browser | PASS | Real `AgentOrchestrator.run()` + Playwright MCP local-form acceptance, 1 passed |
| Windows desktop edit/save | PASS | Exact Notepad target, Cua semantic edit/save, P18A exact readback, exact test-tab close |
| Hybrid target-addressed Computer Use | PASS | Cua-first target routing, snapshot handles, UIA fallback, native global path and truthful focus semantics covered by regression tests and desktop E2E |
| Checkpoint restore | PASS | Agent enrichment restore regressions passed |
| Memory reflection persistence | PASS | Candidate-governance regression passed; prior isolated restart acceptance retained |
| Packaged conversation/restart | PASS | Final clean-user packaged acceptance passed twice through conversation/restart-history flow |
| Packaged shutdown/residue | PASS | Graceful shutdown and residue checks passed; follow-up process query found no packaged Atlas/Node process |

## Environment-only notes

- The user's external Gemini token remains invalid; acceptance used the taskbook's local deterministic provider.
- Hermes emitted its existing warning that a prior update had not restarted running gateways, but the requested minimal prompt still returned `PONG`.
- Release build emitted existing optional-module warnings for Redis/OCI collection, a Vite large-chunk warning, and unsigned-package notices; the build completed and generated the installer manifest.
- Temporary verification directories remain untracked at `_tmp/` and `data/pytest-tmp/`; the shell policy rejected the requested recursive cleanup. They are excluded from the commit. The pre-existing untracked product-comparison `.docx` was also preserved and excluded.

## Commit and remote verification

This result is included in the task delivery commit. After pushing, `origin/main` will be checked against the local `HEAD`.
