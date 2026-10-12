# Atlas Whole-Project Audit - 2026-10-12

## Scope and Boundaries

Read-only product audit. Existing repairs and user edits were preserved. No production service was started, restarted, reloaded, or reconfigured. No foreground window was operated. Only audit helpers and this report were added under `_shots`.

Inventory covered 623 owned production code files in core/atlas, core/scripts, frontend/src, backend-adapter/src and scripts. All 401 owned Python files parsed successfully. Static analysis and targeted entry-point review were combined with isolated unit tests; this is not a claim that every line was manually reviewed or that every possible defect has been found. Vendor implementations were not exhaustively audited. Live model and desktop tests were excluded to preserve the foreground and production data.

## Confirmed Findings

### P1 - Closing an external agent leaves its process running

Location: `core/atlas/runtime/external_process.py:136-149`.

`close()` removes the session from `_sessions` before calling `cancel()`. The latter looks the session up in the same registry and therefore cannot find or terminate the child. A real isolated Python child sleeping for 60 seconds reproduced `close_returned=true`, `session_removed=true`, and `process_still_running=true`. The test child was explicitly killed and awaited afterward.

Impact: closing an external text-agent session can report success while work continues in the background. Terminate the captured process before removing its registry entry, and add a real-process lifecycle regression test.

### P1 - read_tool_history raises instead of returning history

Location: `core/atlas/kernel/loop.py:1973`.

The read_tool_history dispatch branch iterates `messages`, a local variable not assigned on that path. An isolated dispatch reproduced `UnboundLocalError: cannot access local variable 'messages' where it is not associated with a value`.

Impact: models calling the advertised history tool receive an error during history review or context recovery. Supply the current run's history explicitly; avoid shared mutable history across runs.

### P1 Conditional - PM2 exposes privileged local API without mandatory remote authentication

Locations: `ecosystem.config.js:7`, `core/atlas/origin_guard.py:47-48`.

The PM2 entry binds uvicorn to `0.0.0.0`. The origin guard trusts requests without an Origin header when no API token is configured. An isolated ASGI request with a non-loopback client address and no Origin/token was forwarded successfully.

Impact requires deployment through this entry point and network/firewall reachability. This audit did not establish current external exposure; no service was listening on the checked production ports. Default PM2 to loopback, or require authentication for non-loopback clients and verify HTTP/WebSocket boundaries.

### P1/P2 - Optional startup failure can cause the desktop to terminate a usable backend

Locations: `core/atlas/api/health_router.py:52`, `frontend/src/main/backendProcess.ts:26,67,256-258,407`.

Health reports `starting` whenever any component is not `ready`, including a component already marked failed. The desktop accepts only status `ok`, waits up to 300 seconds, then stops the backend it started. Existing backend logs show MemoryOS failure followed by shutdown at approximately the startup deadline. Source inspection confirms the failure-to-timeout-to-stop path.

Impact: failure of a nominally optional component can prevent desktop startup and terminate an otherwise responding API. Define core readiness separately from degraded optional components; preserve visible failure diagnostics rather than marking failures silently healthy.

## Verification and Test Baseline

- Renderer TypeScript and Electron TypeScript checks passed.
- Backend-adapter: 18 tests passed.
- Frontend source-only run: 185 tests, 179 passed, 6 failed. Most failures are stale markup/timing assertions or an Electron mock missing requestSingleInstanceLock, not six independently established UI defects.
- Isolated backend unit runs, deduplicated by test ID across continuation segments: 2440 passed, 79 failed, 5 skipped. Five additional collection errors and two blocking timeouts were recorded separately.
- Backend collection errors resolve `scripts` to a site-packages package rather than the repository's namespace directory; the required repository files do exist. Affects f2_observer_smoke and four unified_memory test modules.
- Blocking tests: test_gateway_write_approval_e2e::test_channel_write_approved_by_channel_reply and test_subagent_settings::test_subagent_settings_apply_to_new_children_only. Execution continued after those modules; four other gateway tests were not executed in this pass.
- Several failing backend tests use obsolete Hermes/config fixtures against current runtime contracts. Those failures were not automatically classified as production regressions. The 79 failures have not all been individually root-caused.
- A subprocess encoding contract test also flags projects_router.py:103. Its text-mode git invocation lacks explicit encoding; a user-visible non-ASCII failure was not reproduced in this audit.
- All 401 Python source files parsed. Ruff found one actionable undefined-variable path, the history defect above; other diagnostics were predominantly unused imports/variables.
- pip check found no broken requirements. The editable Hermes checkout was clean and matched the declared pinned commit c9e076b41f2163445b506b1cb79862d0dab0eecd.

## Dependency Risk

Production npm audit reported 11 affected packages: 9 high and 2 low, with no critical severity. These are affected-package counts, not unique vulnerability counts. The dependency chain includes Pi, MCP SDK, basic-ftp and extract-zip. Reported risks include OAuth credential disclosure, archive symlink traversal and CPU denial of service. Exploitability through Atlas was not established. Do not blindly apply npm audit fix --force: the proposed Pi replacement can be a downgrade and needs compatibility review.

## Evidence Files

- D:/Temp/atlas-whole-audit-unit-trace-20261012.log
- D:/Temp/atlas-whole-audit-unit-tail-20261012.log
- D:/Temp/atlas-whole-audit-unit-final-20261012.log
- D:/Temp/atlas-whole-audit-unit-final-20261012.xml
- D:/Temp/atlas-whole-audit-unit-20261012.xml (initial collection errors)
- D:/Temp/atlas-whole-audit-failure-probes.xml
- D:/Temp/atlas-whole-audit-frontend-src-20261012.json
- D:/Temp/atlas-whole-audit-ruff-20261012.json

## Status

The initial audit did not repair or deploy these findings. A subsequent user-authorized repair pass implemented the four confirmed product fixes below. Production desktop/CDP and live-provider acceptance remain unverified; source verification is not a claim of deployed acceptance.

## Authorized Repair Follow-Up

- ExternalProcessAdapter.close retains its session entry until cancel has terminated and awaited the text-agent process. A real isolated child regression verifies termination, registry removal, reader cleanup, and repeat close.
- read_tool_history uses a per-run callback wired to the kernel's current message list. It limits returned records and does not share history between runs; runtimes without history return an explicit tool error instead of raising.
- Health now reports starting while any deferred component is still starting, degraded when all have settled but some failed, and ok when all are ready. Component errors remain in the response. Electron accepts degraded health without stopping the backend, for both managed and external backends.
- PM2 defaults to 127.0.0.1. OriginGuard requires a valid launch token for non-loopback clients regardless of Origin, for HTTP and WebSocket. No test-specific host exemption is present.
- The existing desktop timeout test was updated from its obsolete 120-second expectation to the production 300-second limit.

Final verification: 51 backend tests passed across six focused modules; 9 desktop startup tests passed; Electron TypeScript check and git diff --check passed. Three existing Pydantic deprecation warnings remain. The first Python invocation hit a Windows temporary-directory cleanup permission error after test execution; final reruns used isolated basetemp and completed successfully.

Evidence: D:/Temp/atlas-four-fixes-verified-20261012.xml. New regression coverage: core/tests/test_whole_audit_regressions.py; health/startup and origin tests were also updated.

No listening Atlas/CDP endpoints were found on checked ports 8765, 8099, 9335 or 9336. The repair pass did not start or restart production services, reload the renderer, or operate the foreground. No npm dependencies were upgraded and the unrelated full-suite failures have not been fixed in this bounded repair pass.

Push preflight additionally verified the earlier stop-button and MemoryOS lifecycle repairs: 68 backend tests passed, adapter 18 passed, renderer store and desktop startup 33 passed, both TypeScript checks passed. A WebSocket isolation test was updated to use an explicit loopback client, consistent with the strengthened origin guard. MemoryOS companion verification passed 5 delivery-order regressions, 23 deterministic Freshness checks and an isolated readiness lifecycle check (503 before startup, ready after startup, 503 after shutdown). Unrelated configuration changes and temporary probes were excluded from the repair commits.

## Update Button Follow-Up - 2026-10-13

The running source desktop disabled its update button because checkSourceUpdate treated every tracked local modification as a blocker. The remaining engine/config.yaml edit did not overlap either pending dependency update. Git merge-tree preflight found the pending commit could merge cleanly without modifying the working tree.

Source update checks now compare incoming paths against both tracked local modifications and untracked files. NUL-delimited Git output preserves spaces in file names; file/directory collisions are also blocked. Unrelated configuration changes no longer block the update. Conflicting paths remain explicit in the blocked message.

Five new regressions first failed against the old behavior, then passed with the fix. Combined source-update and desktop-startup verification passed 14 tests; Electron TypeScript compilation passed. The compiled checker was loaded into the running Electron main process through a temporary local inspector by replacing only the update:check IPC handler. The existing renderer update state was refreshed with the real IPC response. No application restart, navigation, renderer reload or update execution was performed.

CDP verified the live update button had disabled=false, pointer-events=auto, and an unobstructed hit target. Electron retained PID 11204. The temporary main inspector was scheduled to close after verification; the existing renderer CDP endpoint was left intact. This verifies that the button is enabled, not that pulling, dependency installation, rebuilding or relaunching has completed. The user's local configuration edit was preserved.
