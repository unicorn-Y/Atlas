# Atlas Tool Error Audit

Read-only investigation. No foreground navigation, reload, restart, or tool-command replay.

Sources: data/logs/runs/2026-10-11 and 2026-10-12; data/logs/backend.log; engine/state.db (read-only); scoped execution source.

Observed window: 2026-10-12 00:05:24 through 20:15:31, Asia/Hong_Kong. Log folder names use UTC dates.

- 977 tool_result events: 258 failed, 5 cancelled. This is the recorded sample, not an all-time failure rate.
- Failed tools: local_shell 115, local_exec 61, local_file 30, execute_code 28, local_edit 8, powershell 8, view_image 4, and four other tools with one failure each.
- At least 85 shell/process failure outputs contain Python or PowerShell syntax errors. These exclude additional execute_code errors.
- All 28 execute_code failures have preserved tool results: syntax/indentation errors, undefined names, assertion failures, missing paths, or index errors. No evidence here of a universal CodeAct bridge outage.
- Original persisted arguments include taskill instead of taskkill, ensure_asci instead of ensure_ascii, and malformed Python expressions. The corruption is already present before command execution; raw provider wire responses were not available to locate the upstream origin.
- Backend log contains 12 workspace-write-scope refusals. Affected run_start records have empty workspace. local_file/local_edit reject absent mutation scope. Do not bypass this guard to hide failures.
- 156 model_error events classified malformed_response, 9 connection, 1 model. These are model-response attempts, not additional tool failures; retry recovery is possible.
- MemoryOS startup timeout and unified-memory read timeout remain present in backend logs. They are separate from shell syntax failures.

Limits: historical log/schema investigation only. Production CDP and API ports were not listening during this pass. No failed command was replayed because historical commands include writes, configuration changes, and process termination.

## Repair Verification

- Root cause reproduced: kernel/model_call.py used overlap merging for incremental tool argument fragments. This removes valid repeated characters, indentation and adjacent braces. Four fragmentation sizes and repeated-error receipt tests failed before the repair.
- Same-attempt tool arguments, function-name fragments, reasoning and refusal deltas now append without overlap removal. Retry text retention remains separate; incomplete tool arguments are discarded on retry.
- Error loop detection now ignores process IDs and generated output-log trailers while retaining substantive errors and arguments. Different commands and different errors do not trigger the repeated-error path.
- Missing workspace is explicitly explained in model self-knowledge and mutation refusal results; mutation authorization remains required.
- Final verification: 85 tests passed, including nine new regression cases, actual isolated Python child execution, model routing/error recovery, and production WebSocket cancellation tests with isolated collaborators. Four existing library warnings remain. git diff --check passed.

Status: source repaired and verified locally. Production CDP/API ports remain unavailable; desktop activation and a real-model production run were not verified. No foreground restart or dangerous historical command replay was performed. These fixes do not guarantee that arbitrary generated commands, missing files, unavailable providers, or MemoryOS service outages cannot fail.
