# T2-APP-SERVER-SDK-REPLAY-004

Status: `DONE_SCOPED` for the already executed app-server/ACP/Python-SDK consumer matrix. This is not a Task 2 closure.

## Scope and prior evidence matrix

No production file changed in this batch and no prior node was rerun. I reviewed the linked reports and exact assertions to avoid duplicating passing subprocesses.

| Consumer edge | Existing actual evidence | Limit |
|---|---|---|
| ACP stdio protocol → AgentOrchestrator/kernel | `T2-ACP-KERNEL-ATTEMPT-STREAM-021`: actual `serve_stdio(protocol="acp")`, two loopback provider requests; emitted `session/update` chunks concatenate to NEW only, final prompt result `end_turn`, reopened SessionDB is NEW only with OLD in discarded audit. `12 passed, 5 warnings in 9.03s` for the module. | In-process stdio fixture, not an external ACP client or packaged app. |
| SDK → repository CLI app-server child | `T2-SDK-CLI-ATTEMPT-REPLAY-011`: actual SDK-spawned `atlas.cli app-server`, rollback event identity, final `NEW answer`, private DB reopen and natural child exit. `1 passed, 5 warnings in 10.14s`; affected lifecycle + node: `7 passed, 5 warnings in 10.71s`; standalone SDK node: `2 passed, 1 warning in 0.02s`. | Repository CLI, not installed/packaged CLI. |
| SDK process restart/replay | `T2-SDK-RECONNECT-REPLAY-012`: second actual SDK/CLI child opens the same conversation; follow-up provider request contains NEW and excludes OLD; audit retained. `1 passed, 5 warnings in 12.50s`. | Private loopback provider, not live model. |
| Pending tool approval after retry | `T2-APPSERVER-RETRY-APPROVAL-057`: pending approval contains NEW request arguments; retry input excludes OLD; approval resolves, transcript NEW-only and audit preserves OLD. `1 passed, 5 warnings in 11.05s`, natural child exit. | Fixture provider and repository CLI. |
| Retry terminal failure | `T2-APPSERVER-FAILED-RETRY-058`: terminal task failed after provider retries; canonical transcript excludes OLD and discarded audit retains only emitted prefix. `1 passed, 5 warnings in 12.54s`, natural child exit. | Fixture provider and repository CLI. |
| Provider timeout after OLD partial | `T2-APPSERVER-PROVIDER-TIMEOUT-059`: actual task reaches failed after bounded provider timeout; canonical/audit split preserved. `1 passed, 5 warnings in 19.50s`, natural child exit. | Timeout fixture only. |
| Additional stream boundaries | Existing `T2-SDK-PARTIAL-TOOL-ROLLBACK-056`, `T2-SDK-PROMPT-CALLBACK-DRAIN-063`, `T2-SDK-APPSERVER-MAXOUTPUT-AFTER-RETRY-040` preserve partial arguments, callback completion drain and normal max-output continuation. | Their reports hold exact node commands/results; this batch did not rerun them. |

## Result

The existing distinct evidence covers the local app-server/ACP/SDK consumer branches for committed NEW output, rollback events, final result, restart replay, approval, failure, timeout, partial tool arguments, callback drain and normal max-output continuation. No additional production change was justified by this evidence review. Task 2 remains OPEN for actual model authorization, packaged/visible desktop evidence, any uncovered platform/distribution consumer and global parity/superiority gates. The more recent API history route assertion is separately recorded under `T2-API-ATTEMPT-PERSISTENCE-003.md`.
