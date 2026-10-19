# Discovery ledger — Claude Code CLI 2.1.302

Evidence: **S** = exact Claude package code/symbol, **R** = observed this 2.1.302 runtime, **D** = Anthropic documentation, **I** = reasoned inference, **U** = needs verification. The 2.1.302 archives and Windows PE are now available and hash-verified; see `evidence/`. R is restricted to version/help probes. Native strings are static S anchors, not proof of callable functions. Existing IDs remain stable; upgrades and added discoveries below are evidence deltas, not redefinitions. Atlas counterparts have independent source anchors in ATLAS-GAP.md.

| ID | Capability / mechanism to reverse | Current evidence | Why it matters and unlock |
|---|---|---|---|
| CLAUDE_CODE-001 | Interactive session vs print/headless via claude and -p; stdin and JSON/stream-json framing | D | Extract root command dispatch, output discriminant union, streaming message grammar |
| CLAUDE_CODE-002 | Resume by ID/name/transcript, continue most recent and fork new session ID | D | Derive transcript identity, parent linkage, file/branch ownership; R test fresh/resumed/fork |
| CLAUDE_CODE-003 | Background session supervisor: daemon status/logs/run, attach, logs, stop, respawn, rm | D | Reconstruct process tree, worker registry, IPC socket and restart survival |
| CLAUDE_CODE-004 | Addressable parallel agents, agent view, foreground/background delegation, task completion notifications | D | Trace agent process/thread ownership, scheduling, cancellation and parent-child IDs |
| CLAUDE_CODE-005 | Team mailbox on disk, per-agent context, direct SendMessage, shared task list | D | Reverse protocol envelope, mailbox atomicity/replay, distinction from ordinary subagents |
| CLAUDE_CODE-006 | Parallel child transcripts emitted with parent_tool_use_id; nested agent forwarding | D | Need actual stream-json sample to align structured UI/provenance, not collapse to plain text |
| CLAUDE_CODE-007 | Lifecycle hooks including SubagentStart/Stop, setup, compaction and tool phases | D | Extract built-in hook registry, ordered dispatch, blocking semantics and failure path |
| CLAUDE_CODE-008 | Skills, scoped commands, project/user/plugin lookup and fork-context skills | D | Reverse discovery precedence, lazy context injection, subagent handback |
| CLAUDE_CODE-009 | MCP transports and auth/config lifecycle; plugin-scoped extensibility | D | Extract tool schema registry, discovery, token boundary, plugin registration |
| CLAUDE_CODE-010 | Compaction/context window control, token and budget accounting, streaming usage | D | Trace context builder, summary handoff, session log and usage accounting |
| CLAUDE_CODE-011 | Permission mode, tool allow/deny, plan mode and auto mode policy | D | Trace classification/rules evaluation before tool exec; current version gated flags |
| CLAUDE_CODE-012 | TUI agent view, focus/plan/task panes, terminal lifecycle and controls | D | Need TTY snapshots and native TUI registration/render state |
| CLAUDE_CODE-013 | Git worktrees, file-edit rewind/checkpoint and task ownership | D | Need actual persisted data layout, restore invariants and rollback checkpoints |
| CLAUDE_CODE-014 | Self-hosted runner, remote-control server, cloud session dispatch | D | Explicitly client/protocol only; no inferred server implementation |
| CLAUDE_CODE-015 | Advisor, goal, batch, autofix-pr, ultrareview and imported agent configs are additional discovery targets | D | Discover commands beyond the original user list; require explicit native registration and gating evidence |
| CLAUDE_CODE-016 | Native executable bundling, runtime framework, embedded symbols and source map presence | U | Extract PE header, section table, imported symbols, resource enumeration; avoid assuming Bun/Node |
| CLAUDE_CODE-017 | Agent model request, tool-use iterative loop and stop/retry/error policy | U | Trace native decoded function/strings -> tool scheduler -> stream parser -> session persistence |
| CLAUDE_CODE-018 | Secretless boot, auth states, telemetry/update/cache files | U | Probe help/version/auth-status-only; inspect string/file references, never upload credentials |
| CLAUDE_CODE-019 | Cross-session inter-agent messaging outside teams and wakeup protocol | D | Documented in agent team page; test output and disk ownership under R |
| CLAUDE_CODE-020 | Dynamically loaded CLI command completion/suggestions, accessibility and renderer fallback | D | Inspect registration tables, TUI capability-detection and terminal-specific state |
| CLAUDE_CODE-021 | Daemon keep-workers, worker respawn, worktree refuse-to-remove and recovery reasons | D | Inspect daemon graph and recovery transaction, not just existence of commands |
| CLAUDE_CODE-022 | Per-model route, --fallback-model, prompt cache and retry during interrupted tool streams | D/U | Docs establish flags; implementation and resilience policies unknown |
| CLAUDE_CODE-023 | Background tasks' distinct tool availability and inherited permissions | D | Context-dependent tools differ from foreground; prove actual tool filter in package |
| CLAUDE_CODE-024 | Programmatic JSON schema validated output and prompt suggestions | D | Reverse result/validation event protocol and UI event variants |
| CLAUDE_CODE-025 | Unknown command IDs, flags, hidden gated features and reverse references | U | Build whole-program string inventory and diff with --help/doc command tables before claiming coverage |

## Distinctly sourced discoveries outside initial task list
CLAUDE_CODE-003, -014, -015, -019, -020, -021, -024 are proactive expansion candidates found while cross-checking official CLI surface. These are NOT first-hand package findings. Official docs identify daemon supervisor, self-hosted runners, import from other agents, per-session goal, autobatch/PR repair, post-turn suggestions and extended agent communication. Package version affinity remains unresolved.

## D-grade sources checked
- https://code.claude.com/docs/en/cli-reference — CLI options including background supervisor, session forking, stream-json, prompt suggestions, agent view and fallback chains
- https://code.claude.com/docs/en/sub-agents — execution modes, child tool filter and notification delivery
- https://code.claude.com/docs/en/agent-teams — mailbox file layout, separate context and task/messaging semantics
- https://code.claude.com/docs/en/hooks — SubagentStart schema and lifecycle hooks
- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/checkpointing
- https://code.claude.com/docs/zh-CN/commands — additional interactive command inventory

**No attempt was made to impersonate authenticated usage or assert undocumented server internals.**

## Evidence upgrades for existing IDs (pinned executable only)

| Existing IDs | New evidence | Still unknown |
|---|---|---|
| `CLAUDE_CODE-001` | **R:** native `--help` registers interactive default and `-p/--print`; structured output flags appear in actual help. | Generated stream event schema and prompt execution. |
| `CLAUDE_CODE-002` | **R/S:** help advertises `--resume`, `--continue`, `--fork-session`; bundle string cluster includes `--session-id`, `transcriptPath`, `launch`, `fork`. | Identity/ancestry write semantics. |
| `CLAUDE_CODE-003`, `-021` | **R/S:** help registers `agents`, `attach`, `logs`, `stop`, `respawn`, `rm`, `daemon`; `agents --json/--all` and daemon service lifecycle options are concrete. Strings include lease/client schemas, claim frame, socket auth, stale-idle respawn, scheduling and respawn reason constants. | No service process was started; lease/reattach/recovery behavior remains unobserved. |
| `CLAUDE_CODE-004`, `-005`, `-006`, `-019`, `-023` | **S:** embedded strings and exact bundled-source traces cover Agent/SendMessage, direct teammate resolution/delivery, evicted-child recovery, agent/team context helpers, disk subagent enumeration and parent-child fields. **R:** dispatched-session CLI options expose model, effort, permission mode/restriction, settings sources, MCP and plugin directories; published SDK `AgentInput` describes background default, addressable `name`, and worktree/remote isolation. | No agent/team run, mailbox read/ack or persisted operation, emitted event sample, or background-vs-foreground tool execution. |
| `CLAUDE_CODE-007` | **S:** bundle includes named setup, stop-failure, subagent-start, task-created/completed, teammate-idle, user-prompt, and worktree hook helpers. | Ordering/blocking/error contracts not decoded or run. |
| `CLAUDE_CODE-008`, `-009` | **R:** plugin marketplace lifecycle and MCP `serve` are in native help. **S:** tool registry chunk names include skills/goal/plugin/notification and MCP operations. | Config precedence, plugin hot reload and transport/auth behavior. |
| `CLAUDE_CODE-010`, `-022` | **S:** stream/result/session/token-like names occur in bundle. | These are weak field/string hints; compaction, cache accounting, retry and fallback policy remain U. |
| `CLAUDE_CODE-011` | **R:** dispatched agent help exposes restricted mode and permission defaults. **S:** permission parsing/change-guard helper names exist. | Actual permission decision path and tool-block event behavior. |
| `CLAUDE_CODE-012`, `-020` | PE subsystem is console; Windows imports include ConPTY APIs; help confirms agent view/interactive session commands. | TUI render loop, keyboard behavior and accessibility fallbacks not observed. |
| `CLAUDE_CODE-013` | **R:** `rm --help` exposes unpushed commit/worktree and force-remove-worktree options; SDK declares worktree isolation. | Actual checkpoint/rewind and worktree transaction semantics. |
| `CLAUDE_CODE-014` | **S:** exact binary embeds explicit Windows restriction strings for self-hosted runner `--hooks-dir` and orchestrator lifecycle hooks. **R:** `gateway` is registered. | Runner/gateway/cloud service behavior is not observed. |
| `CLAUDE_CODE-015` | **R:** actual help registers `import`, `gateway`, `ultrareview`, `auto-mode`, `purge`, `install`, `update`, `doctor` and `setup-token`, beyond earlier workflow examples. | Cloud review/gateway and authenticated state remain U. |
| `CLAUDE_CODE-016` | **S/R:** exact native file hash/version, AMD64 console PE structure, 13 sections, 18 resources, Bun-compiled `.bun` payload and runtime version/help are confirmed. | Application code remains embedded; function graph not decompiled. |
| `CLAUDE_CODE-017`, `-018`, `-024`, `-025` | **S:** tool/event names, `parent_tool_use_id`, `agent_id`, CLI command registry and SDK task/workflow schemas provide real evidence targets. | No real model turn, auth, structured output result, or exhaustive hidden/gated command inventory. |

## Newly discovered from the package (stable new IDs)

| ID | New observation | Evidence / boundary |
|---|---|---|
| CLAUDE_CODE-026 | npm install normally hardlinks/copies the platform binary over a tiny `bin/claude.exe` stub; manual CJS fallback instead spawns it and propagates signals/status | **S:** `install.cjs` and `cli-wrapper.cjs`; explains why installed and fallback process trees differ. |
| CLAUDE_CODE-027 | Background-session supervisor exposes lease/claim/attach/detach and stale-idle respawn concepts, with explicit legacy/stall/upgrade reason identifiers | **S/R:** exact native string anchors plus matching CLI commands. Concrete lease state machine still U. |
| CLAUDE_CODE-028 | Agent transcript discovery has disk helpers (`getSessionSubagentsDir`, `listSubagentIdsFromDisk`, `locateAgentTranscript`) and dynamic team context getters | **S:** bundle literals; file schema and lifecycle not observed. |
| CLAUDE_CODE-029 | Bundled SDK defines resumable Workflow scripts: persisted script path, `resumeFromRunId`, same-session cached completed `agent()` calls when prompt/options are unchanged, and TaskStop-before-resume guidance | **S:** `sdk-tools.d.ts:2869-2900`; SDK type contract, not asserted as CLI call path. |
| CLAUDE_CODE-030 | SDK task store has `pending/in_progress/completed`, `blocks`, `blockedBy`, optional owner, active-form spinner label and arbitrary metadata | **S:** `sdk-tools.d.ts:2802-2868,4005-4038`; existence in SDK declarations, not a captured persisted task file. |
| CLAUDE_CODE-031 | Native CLI provides worktree-aware cleanup (`--discard-unpushed`, `--force-remove-worktree`) and service registration/uninstall controls | **R:** exact `rm --help` and `daemon --help` output; no destructive operation run. |
| CLAUDE_CODE-032 | Windows build rejects POSIX lifecycle-hook runner `--hooks-dir` and orchestrator mode | **S:** literal diagnostic strings in native `.bun`; runtime failure path not executed. |
| CLAUDE_CODE-033 | `gateway` and `ultrareview` are product-level, server-backed command surfaces hidden outside simple coding loop | **R:** native help labels them enterprise auth/telemetry gateway and cloud-hosted multi-agent review; backend is U. |
| CLAUDE_CODE-034 | A stale-version background worker is restarted only after explicit safety guards and a second v5-state read; attached workers, recent input, non-idle state, in-flight work, transitions, and terminal outcomes prevent upgrade | **S (readable source in exact PE):** `evidence/12-native-supervisor-source.md`, method at file offset `0x0f3adb0d`. Actual daemon execution remains U. |
| CLAUDE_CODE-035 | Settled-worker retirement has separate guards for queued work, active tasks, drainable monitors, routines, session-cron tasks, bridge-session grace, pinned status, and recent adoption/input; low-memory sweeper applies staged retirement | **S:** exact PE methods at `0x0f3ae7ff` and `0x0f3c9807`; no induced low-memory run. |
| CLAUDE_CODE-036 | Background restart restores resume session ID, flags, cwd, interactive lineage and transcript selection from v5 state; interrupted-turn env is set when prior transcript has messages | **S:** `doSpawn` visible at PE offset `0x0f3b306d`; model response and successful resume not observed. |
| CLAUDE_CODE-037 | Daemon adoption checks PID liveness and process-start identity before rebuilding worker state, PTY and rendezvous; claim frame rebuilds argv/env with session ID/respawn flags | **S:** exact PE offsets `0x0f3b0d05`/`0x0f3b0dff`; cross-process takeover not exercised. |
| CLAUDE_CODE-038 | Worker sockets use independent random 16-byte hex rendezvous and PTY auth values; retry path checks whether disk state is settled before another spawn | **S:** methods in exact PE at `0x0f3b0d05`, `0x0f3b306d` and adjacent source; actual authorization and retry outcomes remain U. |
| CLAUDE_CODE-039 | Bundled wire schemas declare user/assistant/stream frames with nullable `parent_tool_use_id`, distinct local UUID/API message IDs, user-message correlation and restart `resume_reason` | **S:** schema source at exact PE offsets `0x0e6853d0`, `0x0e68a935`, `0x0e6a0bf7`; no real event frame captured. |
| CLAUDE_CODE-040 | Child task protocol separates task ID from run ID and spawning tool ID; start includes parent/depth/background/awaited, updates are wire-safe patches, terminal notifications and full live-task set have separate schemas | **S:** `task_started`, `task_updated`, `background_tasks_changed`, `task_notification` schema source near `0x0e6aa80a-0x0e6a9e7a`; order not observed. |
| CLAUDE_CODE-041 | Backgrounded tool may return placeholder result, with actual completion later sent in task notification joined by originating `tool_use_id`; subagent handback has separate metadata | **S:** `task_notification` schema description at `0x0e6a9e7a`; no background task was run. |
| CLAUDE_CODE-042 | Tool-result metadata distinguishes whether an error tool call executed (`non_execution_kind`) from permission decision, and links source tool/assistant UUID; metadata presence alone does not prove execution | **S:** user/tool-result schema source at `0x0e6853d0`; no permission/tool result was generated. |
| CLAUDE_CODE-043 | Init event declares the active CLI capability/config snapshot; success result schema carries detailed request/turn timing phases rather than only final text | **S:** `system/init` and `result/success` schema source at `0x0e69c2e3` and `0x0e694228`; no live event emitted. |
| CLAUDE_CODE-044 | `SendMessage` resolves teammates against live context/persisted roster and fails closed on stale, duplicate or ambiguous name/ref resolutions; prefix/duplicate candidates require explicit confirmation | **S:** exact PE `deliver`/resolver and `bt` source at `0x105537f5` and `0x1054e772`; no message sent during research. |
| CLAUDE_CODE-045 | `SendMessage` is executor/permission/hook integrated; it rejects broadcast, unsafe protocol text, structured cross-session messages and post-approval recipient/content rewrites | **S:** tool definition at `0x105510c8`; actual permission UI/settings/hooks not exercised. |
| CLAUDE_CODE-046 | Named local teammate delivery writes an inbox envelope, then updates resolver task state; when recipient already runs, it writes first then emits retryWake; write failure reports no delivery | **S:** `bt` and `xe` at `0x1054e772`/`0x1054f1f1`; inbox path/writer/read/ack are now partly source-traced in `evidence/15`; live runtime consumption remains U. |
| CLAUDE_CODE-047 | Tool routes among named teammate, local-session UDS, Claude Desktop and bridge/cloud peers; optional idle subscription is separate from a message and is not claimed when the send fails | **S:** dispatcher at `0x105537f5`; network/server delivery and live routing remain U. |
| CLAUDE_CODE-048 | Message to an evicted/stopped local child can load recovery metadata and resume it as an in-process teammate with prior messages and the new message as its next prompt; concurrent resume attempts are coalesced and an already-running match is inbox-queued | **S:** `agent-evicted` branch at `0x1055916f`; transcript retention, model turn and successful run remain U. |

These discoveries are readable bundled application-JS source, not just function-name strings. Exact executable SHA and offsets are in `evidence/12-native-supervisor-source.md`, `evidence/13-native-message-task-schemas.md`, `evidence/14-native-sendmessage-source.md`, `evidence/15-native-mailbox-source.md` and `evidence/16-native-task-state-events.md`; the full unique chunk-reference inventory is in `evidence/17-bun-chunk-import-inventory.txt`. They upgrade static mechanism and declared wire-schema traces only. A new synthetic isolated process run reached `system/init` but its model request returned HTTP 401; no Agent/tool execution or event ordering was observed.

| CLAUDE_CODE-049 | The exact package contains a schema-validating teammate inbox writer with team/agent path resolution, exclusive file initialization, lock-protected append, atomic replacement and v5-store updateText path | **S:** `Zw` at PE byte offset 248022054, exact source excerpt in `evidence/15-native-mailbox-source.md`; no live mailbox write. |
| CLAUDE_CODE-050 | Teammate mailbox read/ack/clear paths validate records, expose unread messages, prune acknowledged records under lock and atomically persist survivors; missing/corrupt cases have explicit handling | **S:** `S8e`, `RRr`, `gOe`, `WWn` at PE offsets 248020900, 248024280, 248025672, 248027467; actual consume/wakeup/parent notification remain U. |
| CLAUDE_CODE-051 | Task registry emits task_started with stable task/run/tool IDs and parent/child/task-kind metadata; transitions emit task_updated patches and terminal task_notification | **S:** `Kn` at 246861552, `Hn` at 246859691, `_a` at 242665992; no live task executed. |
| CLAUDE_CODE-052 | Task event queue is bounded, coalesces/holds background snapshots, preferentially preserves lifecycle start/terminal events, and selected consumers reconstruct task state from replacement snapshots and terminal updates | **S:** queue source near 242662000, consumer `Gzr` at 269514323 and `ut` at 275456189; event delivery and persistence remain U. |

These new discoveries are preserved source findings; they do not promote runtime event generation, parent notification, persistence or Agent/tool execution to R. Gate status and active unknowns are tracked in `COVERAGE.md`, `END-TO-END-TRACES.md` and `FINISH-GATES.md`.
