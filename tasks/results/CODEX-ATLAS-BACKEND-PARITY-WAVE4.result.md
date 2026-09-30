# CODEX-ATLAS-BACKEND-PARITY-WAVE4 Result

STATUS: IMPLEMENTED; REQUIRED FULL-SUITE VERIFICATION INCOMPLETE
BASE_BRANCH: main

## Delivery

Completed the six taskbook sections in backend scope. frontend/, backend-adapter/, and core/atlas/origin_guard.py were not modified. All test basetemp directories used for this work were under the system temporary directory. No real Docker daemon, external Agent CLI, or SSH server was used by the automated tests.

### 1. Conversation execution preferences and Wave3 leftovers

- Built-in profile guidance is now Chinese. Existing English defaults migrate once while user-customized profile text is preserved.
- Conversations persist workspace, permission mode, allowed paths, executor, and sandbox settings; run start inherits saved values unless the request overrides them.
- Added Chinese permission/path rejection messages, SSH allowed-path normalization, stale rules.trust event ID handling, and run.started.data.executor.
- Runtime Event Protocol is now 1.6.
- Updated old protocol assertions, including tests/test_server.py.

### 2. External Agent execution

- Added GET /api/agents/external availability/version reporting for Codex, Claude, Hermes, Pi, and ZCode with a 60-second cache.
- run.start.executor selects an installed backend. Per-conversation backend sessions are reused; normalized output, tool, completion, failure, and cancellation events flow through the runtime event protocol.
- External Agent execution is rejected for read-only conversations and SSH workspaces. Checkpoints are recorded before and after execution, and run changes include new files.

### 3. Parallel worker delegation

- Added delegate_parallel for up to eight tasks and a concurrency limit of four.
- Git repositories use isolated worktrees. Results contain binary patches and changed-file lists for coordinator review and are not auto-merged. Non-Git directories use shared-workspace ownership instructions and before/after file fingerprints.
- Worker failures do not discard successful worker results. Cancellation cleans up workers, and the coordinator performs one summary call.
- Added subtask.started, subtask.output, subtask.completed, and subtask.group_completed events.

### 4. Office artifacts and workspace history

- Added agent tools to create and read DOCX, XLSX, and PPTX artifacts, with a checkpoint before writes and an artifact.created event afterwards.
- Added static Office preview at GET /api/workspace/preview, including the taskbook CSP, inline images, and the 10 MB input limit.
- Added checkpoint and Git versions at GET /api/workspace/history, content and raw-content routes, and restore with an automatic pre-restore checkpoint.
- Preview and sandbox status routes have OriginGuard tests for token access and rejection of a foreign browser origin.

### 5. Structured checks

- Added run_checks for lint, typecheck, test, or all available project checks. Python projects detect ruff, configured mypy, and pytest; Node projects detect package scripts and available TypeScript tooling.
- Added bounded parsers for ruff JSON, mypy/TypeScript diagnostics, pytest JUnit XML, ESLint JSON, and Vitest/Jest JSON.
- Results use the taskbook schema, cap diagnostics at 200 items, and emit check.results. Recognizable local shell/exec test summaries also emit count-only check events.
- If no check tool is available, the tool returns a Chinese explanation.

### 6. Docker command sandbox

- Added GET /api/sandbox/status with a 60-second Docker availability/version cache.
- run.start.sandbox accepts null or Docker settings. Docker is limited to Atlas runs with a local workspace; SSH and external Agent execution return clear errors.
- Each Docker run binds the workspace at /workspace, uses /workspace as its working directory, defaults to python:3.12-slim, and defaults to --network none. The container is forcibly removed in the run finally path, including failures and cancellation.
- local_shell, local_exec, and local_git execute through docker exec. Host file tools remain available within the workspace boundary. Computer, browser, and MCP tools return a Chinese disabled message.
- run.started.data.environment is docker and includes the selected image.

## Deviations and known limits

- The local_shell.shell selector remains in the tool schema, but Docker command execution uses the Linux container's sh -lc. PowerShell- or cmd-specific commands need a Linux-compatible equivalent inside the selected image.
- run_checks currently reports that SSH workspaces are unsupported. Office generation/reading and preview support the SSH paths described by the implementation.
- Real SSH coverage was skipped because ATLAS_SSH_TEST_HOST and ATLAS_SSH_TEST_ROOT were not configured. Real external Agent and Docker execution were verified with fakes only.
- The required full-suite command did not finish. It was interrupted with KeyboardInterrupt after 60 passed and 1 skipped while starting the Git worktree test in test_backend_parity_wave2.py. A separate run of that worktree test passed. The real child-process startup test in test_hub.py was also interrupted while waiting for its local health endpoint; it did not complete. These are not recorded as a passing full-suite gate.
- The first full test_server.py run found one stale assertion expecting protocol 1.5. The assertion was updated to 1.6 and the complete file then passed: 68 passed.
- Pytest emitted a cache warning because the existing core/.pytest_cache directory is not writable in this environment. Test basetemp remained outside the repository.

## Verification evidence

- Section-focused regression runs: Wave1/SSH checks 7 passed, 1 skipped; external Agent checks 10 passed, 1 skipped; delegation regression 49 passed, 1 skipped; Office/history and OriginGuard 27 passed, 1 skipped; structured checks 3 passed; Docker/checks/OriginGuard 35 passed, 1 skipped.
- After making the sandbox context fields optional for existing Agent callers, test_agent.py plus the Wave4 tests passed: 56 passed, 1 skipped.
- test_backend_parity_wave2.py: 22 passed.
- test_backend_parity_wave3.py: 20 passed (the command process was interrupted after its pass summary).
- test_server.py after the protocol assertion update: 68 passed.
- Additional individually run modules, including memory, local execution, MCP, project, release, scheduler, skill, and integration coverage, reported passing tests; the hub child-process startup test remains incomplete as noted above.
- The taskbook-mandated full-suite command was attempted with --ignore=tests/test_computer_use.py and a system temporary basetemp, but it did not complete.

## Manual verification

1. Start Atlas and call GET /api/agents/external; confirm each installed CLI reports its availability and version. Start a WebSocket run with executor set to an available backend, send a prompt that produces a short response, then cancel a second run and confirm run.cancelled and session cleanup.
2. Start Docker Desktop and call GET /api/sandbox/status. Start an Atlas WebSocket run with sandbox: {"type":"docker"} and a local workspace. Run pwd and git status; confirm returned paths map to the host workspace and run.started.data reports environment: docker with the image. Cancel a long-running command and confirm the named atlas-... container disappears. For the default network policy, verify the container cannot reach the network; repeat with network: true only when network access is intended.
3. With a local workspace, create one DOCX, XLSX, and PPTX through the tools; preview each and inspect its history. Restore an earlier version and confirm the pre-restore checkpoint appears in history.
4. Run run_checks in a small Python or Node project and inspect both the concise tool response and the check.results runtime event.
