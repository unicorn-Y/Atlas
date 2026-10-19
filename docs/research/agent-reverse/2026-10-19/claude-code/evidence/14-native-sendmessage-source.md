# SendMessage tool: target resolution, consent, and team inbox delivery

## Artifact identity

Source is embedded in the exact shipped Bun PE `@anthropic-ai/claude-code-win32-x64@2.1.302`, `package/claude.exe`, SHA-256 `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae` (archive SHA-256 `cd077f50f24f5155c28800a3658a58c89b5d1ccae2f95a2e096a16ab250a544d`). These are byte offsets into that exact PE and point into readable bundled application-JS. This is static shipped-client code; no SendMessage call or mailbox write was executed.

## Traced local teammate path

### Registry and executor-bound tool registration (`0x105510c8`, byte 274,010,312)

The bundle registers a `SendMessage` tool with `backgrounding:"never"`, `shouldDefer:true`, `isReadOnly` only when the message is a string, custom input validation, permission checks and a custom `deliver` method. Its execution context must include the issuing assistant message, `canUseTool`/permission dispatcher and engine runner (`At`, `0x10550f29`); missing that executor context throws. Therefore this is a scheduler-integrated, policy-aware tool, not a naked file append.

### Input and policy gates (same `SendMessage` definition)

`validateInput` rejects broadcast `to:"*"`, invalid/ambiguous recipients, an empty ordinary message, malformed teammate protocol frames embedded as plain text, structured messages when teams are disabled, structured messages cross-session, and `notify_when_idle` attached to structured messages or remote bridge recipients. Shutdown protocol responses are restricted to the team lead; an approval cannot carry a rejection reason, while a rejection requires one. This preserves a distinction between plain user-facing prose and structured internal teammate lifecycle/plan/shutdown frames.

`checkPermissions` validates the destination and delegates to tool permission policy before delivery. If `isolatePeerMachines` is enabled, cloud/Remote Control/bridge destinations are resolved and asked with an explicit cross-session/cross-machine notice (or denied for unavailable/blocked routes); unresolved names are asked rather than silently assumed. Tool hooks/permission handlers may rewrite input, but a post-approval recipient change or a rewrite to structured content is rejected before sending. Permission/approval behavior depends on settings and actual hooks; no policy was exercised here.

### Target resolver and local mailbox append (`bt`, `0x1054e772`, byte 273,999,730)

The in-session teammate sender first requires active team context. It resolves a teammate using current team context or the persisted roster via helper `Ub(teamName, storageV5)`, and when provided, cross-checks the resolved `agentId` against the roster. If a previously resolved member disappeared, duplicate roster identity exists, or roster lookup fails, it returns an explicit refusal and sends nothing; it does not silently route a stale bare name to a different teammate. For a resolved teammate it calls:

`Zw(targetName, {from, text, summary, timestamp, color, from_plugin?}, teamName, storageV5)`

If the write helper returns no message ID, delivery reports `mailbox_write_failed`. On success it updates the task resolver state with `p8r(...)` and returns a success result with `msg_id` and sender/target/summary routing metadata. The helper's underlying file path, lock/atomic-write protocol and read/consume behavior are not recovered from this method.

For a teammate already running, helper `xe` (`0x1054f1f1`, byte 274,002,417) writes the same envelope to that teammate's inbox, then signals `retryWake.emit()` and returns “queued your message for its next turn.” Failure returns “nothing was queued.” This is explicit inbox-plus-wakeup behavior in the client source, although runtime delivery order was not captured.

### Stopped/evicted child resume (`case "agent-evicted"` at `0x1055916f`, byte 274,043,247)

The local agent route distinguishes an evicted agent from an ordinary absent name. It coalesces concurrent resume attempts per `agentId` using `toolState` and a shared promise; it checks for an already-running resumable task and queues through `xe` if one exists. Otherwise it reads recovery metadata with `ds(agentId, storageV5)`. With metadata available, it checks again for a running matching task and queues if found; if none exists, it calls the in-process spawn/resume path with `{resumableAgentId, prompt: currentMessage, senderName, meta, fallbackName}`. Its returned result explicitly reports the number of prior messages restored and that the current message is the resumed teammate's next prompt. If the native agent type/config can no longer be restored, the resume path can be denied or fall back to a narrower subagent route, and it reports a diagnostic rather than silently pretending the original teammate resumed.

This is strong source evidence for an addressable post-eviction teammate recovery path in the local client. It does not reveal how much transcript is retained, exact transcript file schema, lifetime/retention limits, successful model execution, or cross-process restart behavior.

### `deliver` dispatcher (`0x105537f5`, byte 274,020,341)

The outer method first checks whether the sending subagent has a stop still completing, validates that the sender may send, and rejects observers. It then routes by recipient scheme:

- A Desktop session uses the Desktop-host messaging tool and is plain-text only.
- A bridge address uses `postInterClaudeMessage` from another bundled module, gated by credential/recipient checks and the permission handler. The remote service protocol remains outside this package.
- A local Unix-domain socket path calls `sendToUdsSocket`; optional `notify_when_idle` is handled by a separate `subscribeToPeerIdle` call after message delivery. On send failure, idle subscription is not falsely reported as successful.
- Other names go through `Oqt` target resolution. It fails closed for unavailable/observer/non-addressable sessions, validates local sockets and identity claims, asks the model to disambiguate duplicate/prefix names with an explicit reference, and does not send until a candidate is confirmed.
- Team resolution routes through local roster helpers such as `bt`/`xe`; a completed inbox write updates task resolver state. If no reachable/unique target can be established, it returns a diagnostic without sending.

The target-resolution behavior shows this tool can address more than teammates (local sessions and cloud/Remote Control peers), but the actual bridge/cloud API service is not present here. Cross-machine structured payloads are specifically disallowed; only plain text goes through that path.

## Atlas main comparison

Pinned Atlas baseline `main@aa6196f550098cc46081dc6db2c376cb87ddffa5` was inspected beyond the agent todo path:

- `core/atlas/groups/store.py:55-93,126-181` persists group definitions with validated persistent-agent members and membership changes.
- `core/atlas/groups/__init__.py:129-198,235-260,286-390,442-470` implements a persistent room log, monotonic sequence, per-agent watermarks, round-robin/mention handoffs, turn caps, stop epochs and per-member dispatcher calls. `submit_member_message` records a late message as `stranded`, explicitly not replaying it to a later prompt.
- `core/atlas/api/group_router.py:164-195` exposes timeline, stop and turn-drive endpoints. This is a real Atlas multi-agent collaboration implementation, so the earlier “trace groups before saying absent” caveat is resolved for group chat/workflow.
- `core/atlas/engine/notifications.py:62-114,119-148` separately provides a durable SQLite per-conversation notification inbox with source dedupe, transaction, waiter wakeups and atomic consume. Its module contract is notifications for detached processes/watchers, not a named agent mailbox.

Assessment: Atlas has persisted group collaboration and a separate durable notification inbox. These are **related real mechanisms**, not missing shells. Their contracts differ from Claude's SendMessage tool, which resolves a named teammate/session, permission-checks each send, writes a recipient inbox, wakes a running teammate, and emits task/routing metadata. The inspected Atlas group room log is broadcast/round-turn context, while `notification_inbox` is conversation-targeted notifications; neither is the same call path. No claim is made that Atlas lacks all direct agent messaging elsewhere; this comparison is limited to the inspected group, notification and subagent paths.

The inspected Atlas child-worker path also explicitly deletes its transient conversation in `core/atlas/agent/__init__.py:640-650`; it does not show Claude's resumable-agent ID plus prior-message rehydration. This is a path-scoped difference, not a system-wide proof that Atlas cannot resume persistent agents.

## Remaining unknowns

- The full mailbox path and writer/read/ack implementation are source-traced in `15-native-mailbox-source.md`; runtime locking, crash durability, idempotency and file/store repair behavior remain unknown.
- Actual reader/ack/replay/ordering behavior and race behavior with `retryWake` remain unobserved; see `15-native-mailbox-source.md` for the static code path.
- Whether/when a teammate is woken, tool-call loop resumes, and parent receives the corresponding message/task event.
- Runtime permissions, hook ordering, user confirmation and cross-machine service behavior.
- Cross-machine `postInterClaudeMessage` server contract and durable delivery.
