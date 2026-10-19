# CJS short slices (all offsets UTF-8 bytes)

Source digest: 31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54. The exact file was successfully parsed by Acorn 8.16.0. These are short local contexts from the shipped minified code, not recovered upstream source. Runtime execution was not observed.

## Bundle shape

- byte 0: #!/usr/bin/env node
- byte 2,489,228: __webpack_require__; adjacent source has n.m=e,n.c=t,n.p="",n(0) and a numeric module array. Exact code seen; symbol map unavailable.

## Tool lifecycle

- bytes 13,192,839–13,193,404, helper persistPendingToolPart: chooses a provider/tool name, then awaits e.persistPart with type tool and callID. Exact code seen for persistence helper.
- bytes 13,205,979–13,210,657, helper qwt: after tool-call close, invokes scheduleTools, transitions turn state, emits tool_queued, logs execution, then awaits this.executeTools. Exact code seen for this local method order; scheduler/DB effects and runtime timing are not observed.
- byte 13,218,154 begins a separate streamed tool path that emits tool_queued with executionTiming during_stream before executeTools. Exact code seen; full containing branch needs follow-up.

## Subagent and task state

- bytes 5,042,044–5,044,543 define class name InMemoryRuntimeTaskRegistry; fields include activeBranchGeneration, backgroundWaiters, tasks, terminalWaiters. register defaults task branchGeneration to the active generation; update resolves terminal/background waiters.
- byte 5,042,679: requestBackground(t) looks up a task, refuses missing/terminal records, sets isBackgrounded, updates the map, then resolves background waiters.
- byte 12,715,173: child runner callback emits SubagentSpawned with agentId, childSessionId, parent tool/call provenance and run trace.
- byte 12,716,232: run branch handles kind backgrounded by calling detachParent(), stopping the foreground wait and retaining async completion/failure callbacks.
- byte 12,719,281: task port backgroundTask(taskId) requests registry background state and returns the task record. These are packaged static branches; survival under actual process failure was not observed.

## Workflow journal and replay

- bytes 1,515,023–1,543,238: migration closure contains migration id 0019_dwf_journal, dwf_run, workflow_node, workflow_activity tables and columns including call_path, attempt, input_hash, status check values queued/running/completed/failed/skipped, actor sequence and result/error/stat payloads. This is schema text inside the runtime bundle, not proof migrations execute.
- bytes 12,513,514–12,524,192: workflow helpers include inputHash, reuse candidate entries, pure-only reuse checks against stats.worldToolCalls===0, seed/transcript state, and InputHashMismatch deterministic replay error. Exact implementation fragments seen, but no source-map/module source name or full driver-to-SQLite path yet.

## Network retry

- bytes 3,898,082–3,898,491, function V9s: reads retry-after-ms, otherwise retry-after; parses seconds or HTTP-date and returns a finite nonnegative delay within a bound. Likely a bundled HTTP SDK helper. It is not yet connected to ZCode workflow concurrency controller or the 3.15.3 release-note fix.
- bytes 4,007,148–4,007,440, function qXr: core model request retry helper checks retry-after-ms first, then retry-after as numeric seconds or HTTP-date, returning a nonnegative millisecond delay. Exact packaged code seen.
- bytes 4,097,229–4,097,847, function HB logs model.retry.delay.resolved with canRetry, delayMs, nextAttempt, reason, retryAfter headers, retryAfterSource, retryReason, statusCode and x-should-retry. A nearby sHs helper classifies blocked_by_x_should_retry, provider_header, header_unparsed_or_ignored, or missing. This is concrete request retry observability; how the 3.15.3 release-note concurrency repair relates remains unknown.
