# State and protocol fields actually observed

## Observed names and types

- Native bundle string tables: `session_id`, `sessionId`, `parent_uuid`, `request_id`, `transcriptPath`, `getTranscriptPath`, `parent_tool_use_id`, `agent_id`, `tool_use_id`, `terminal_reason`, `LeaseClientSchema`, `RESPAWNING_ATTACH_CODE`, `RESPAWN_REASON_LEGACY`, `RESPAWN_REASON_STALL`, `RESPAWN_REASON_UPGRADE`, `SUPERVISOR_DETACH_CODE`, `socketAuth`, `buildClaimFrame`, `taskListHighWaterMark` (offsets in `06-native-string-index.jsonl`). These are observed literals/helpers, not a recovered complete schema.
- Bundled SDK declarations `sdk-tools.d.ts:772-812`: `AgentInput` carries description/prompt, optional subagent type, model, effort, background default, named addressable agent, worktree/remote isolation; remote runs always background and are gated.
- `sdk-tools.d.ts:2802-2868,4005-4038`: task inputs expose create/get/update/list; result status enum is `pending | in_progress | completed`, includes `blocks`, `blockedBy`, optional owner in list output.
- `sdk-tools.d.ts:2869-2900`: workflow API supports inline/script path/name, `resumeFromRunId`, same-session resume; completed agent calls may be cached when prompt/options unchanged; stop prior run with TaskStop before resuming.
- Native `claude agents --help`: machine-readable active sessions, optional completed sessions and cwd filter; default dispatch model/effort/permission/settings/MCP/plugin configuration.
- Native `claude daemon --help`: supervisor config/log path defaults (`~/.claude/daemon.json`, `~/.claude/daemon.log`). The help did not expose daemon session DB schema.

## Still unknown

No real session/transcript/daemon/team file was created or read. Persisted task/mailbox schema, lock/lease transaction, atomic writes, recovery state as serialized on disk, transcript-parent linkage, compaction write contract and cloud protocol fields remain U. SDK types and string literals must not be promoted into the native CLI's full persisted schema. Exact client event envelope builders are partially decoded in `evidence/13`; actual emitted event frames and ordering remain U.

**Schema-source delta:** `evidence/13-native-message-task-schemas.md` now records exact-PE schema builders for user/assistant/stream/result/init and child-task event envelopes, including `parent_tool_use_id`, task/run/tool IDs, `task_updated` patches, `background_tasks_changed` replacement snapshots and terminal task notifications. These define wire fields in the shipped client. They do not resolve task-file/mailbox persistence, transaction ordering, actual field presence or serialized runtime messages; those remain U.

