# Native function/module anchors — symbol map, not decompilation

The `0x071e2c00` `.bun` section contains the bundled JavaScript payload. Literal module IDs and symbol-like strings are present at the file offsets recorded in `06-native-string-index.jsonl`. This pass did not resolve their bytecode/object references to executable native function addresses, so the anchors below describe source-like bundle metadata and corroborating runtime CLI behavior, not call graph edges.

| Area | Observed anchor | Evidence/interpretation limit |
|---|---|---|
| Background CLI dispatch | `respawnHandler`, `spawnBgSession`, `stopHandler`, `rmHandler` at `0x758d8a8` cluster | Names align with shipped top-level commands/help; body and handler wiring not decompiled. |
| Daemon/lease protocol | `LeaseClientSchema`, `RESPAWNING_ATTACH_CODE`, `SUPERVISOR_DETACH_CODE`, `RACED_SOCKET_GAP` around `0x759abb8-0x759ac68` | Internal protocol-shaped names. Transport message schema and authentication are unknown. |
| Worker supervisor | `respawnIfIdleStale`, `scheduleRespawn`, `buildBridgeReattachEnvFromState`, `socketAuth`, `buildClaimFrame` around `0x75de3c8-0x75de6f4` | Suggests stale-idle recovery and authenticated claim/reattach; no runtime daemon transition was captured. |
| Resume/fork dispatch | `--resume`, `--session-id`, `--fork-session`, `transcriptPath`, `flagArgs` around `0x75df3f4` | Corroborates shipped `--resume`/`--fork-session` flags; persistence format/semantics unobserved. |
| Agent transcript lookup | `getSessionSubagentsDir`, `getTranscriptPath`, `listSubagentIdsFromDisk`, `locateAgentTranscript` around `0x75b509c-0x75b50f8` | Indicates explicit disk-backed subagent discovery helpers. Directory contents and write order unobserved. |
| Agent/team context | `getAgentId`, `getAgentName`, `getDynamicTeamContext`, `getParentSessionId`, `getTeamName`, `getTeammateContext`, in-process teammate predicates near `0x75a157c` | Static identifier cluster supports distinct team/agent context concepts; does not establish orchestration algorithm. |
| Tool registry | `SendMessageTool` near `B:/~BUN/root/chunk-92nntqkt.js` and `AgentTool` near `0x7599d39` | Product tool registration names; no schema/call xref reconstructed from bytecode. The separate SDK declarations provide their own public types. |
| Hook lifecycle | `executeSubagentStartHooks`, `executeTaskCreatedHooks`, `executeTaskCompletedHooks`, `executeTeammateIdleHooks` near `0x75a5cb0` | Hook lifecycle symbols appear in the embedded bundle; order/failure/blocking contract not proven. |
| Event ancestry | `parent_tool_use_id`, `agent_id`, `tool_use_id`, `terminal_reason` clusters near `0x75edda4/0x7602924` | Field-name evidence only; exact JSON envelopes and ordering require a real generated trace. |
| Windows runner limits | Exact strings at `0x75d945c` and `0x75d9608` say `--hooks-dir` and orchestrator mode require POSIX lifecycle hook executables | Shipped strings establish emitted diagnostic text and explicit Windows limitation; no self-hosted runner operation was invoked. |

Runtime implementation chain established to the following boundary: `npm bin` -> postinstall replaces 500-byte shim with native PE -> native PE starts as a console program -> version/help parser reports commands and flags. `--help` verifies the registration output; authenticated prompt dispatch -> network model request -> streamed tool call -> agent/tool executor -> transcript persistence was not dynamically traversed.

