# Discovery ledger — Claude Code CLI 2.1.302

Evidence: **S** = exact Claude package code/symbol, **R** = observed this 2.1.302 runtime, **D** = Anthropic documentation, **I** = reasoned inference, **U** = needs verification. **Zero Claude S/R** at this stage: release-asset bytes were inaccessible in this session. None of the D items assert that a specific 2.1.302 executable registers the command. Affected command probes are in EXTRACTION-REQUEST.md. Atlas counterparts have independent source anchors in ATLAS-GAP.md.

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
