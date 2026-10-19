# Interface, protocol and workflow tracing

**R** = exact shipped 2.1.302 CLI help/version output; **S** = exact package/bundle literal/type evidence; **D** = official description; **A-S** = Atlas source observation; **U** = unobserved runtime behavior. The real PE was probed in an isolated empty profile. The PE contains readable message/task schema builders (static S; `evidence/13-native-message-task-schemas.md`), which refine the wire-format description below but are not captured runtime events. This report still does **not** claim native TUI screenshots, keyboard recordings, generated event captures or an authenticated agent run.

## Workflow 1 — CLI interactive lifecycle (R/D/U)
- Entry: claude launches interactive mode, claude "query" prepopulates first prompt.
- During work: commands and inline tool progress are displayed; /agents, /tasks, /mcp, /hooks, /model, /permissions are CLI commands described by official docs. /focus modifies rendering mode; model/permission controls change session configuration.
- Exit/re-entry: claude -c continues latest compatible project session; claude --resume ID/name selects session; --fork-session with resume generates a new identity rather than mutating old session; some commands also accept transcript paths.
- Verify: start/restart in an isolated project; capture terminal frames, session filenames and parent linkage. Differentiate named-session selection from stored transcript content. Native TUI control IDs and screen refresh engine remain **U**.

## Workflow 2 — Headless structured request (R/D/U)
- Entry: claude -p "query" --output-format stream-json --verbose --include-partial-messages
- Optional: --forward-subagent-text exposes child assistant/user text with parent_tool_use_id; --include-hook-events surfaces allowed hook lifecycle messages; --input-format stream-json allows structured requests and --replay-user-messages acknowledges stdin.
- Exact PE schemas now show `system/init`, parent-linked assistant/user/stream frames, result timing phases, task lifecycle forms and tool-result metadata (`evidence/13-native-message-task-schemas.md`). Exact generated JSON lines, field presence/order in a live request, error and exit must still come from an *actual generated sample*.
- UI consequence: a consumer must preserve parent/child provenance and status types; printing plain lines is insufficient. Atlas currently normalizes limited ACP types in core/atlas/runtime/external_agents.py:60-98 (A-S).

## Workflow 3 — Supervisable background session (R/S/U)
- Entry: claude --background "..." (also --bg); a supervisor may manage worker sessions.
- Inspection: claude agents --json [--all], claude logs ID, claude daemon status/logs; attach ID to re-enter interactive UI; respawn ID to restart while retaining conversation; stop/rm manage lifecycle.
- Shipped client source has a restart/retirement state machine with idle/in-flight/attached guards and v5 state recovery fields (`evidence/12-native-supervisor-source.md`). The bundled wire schemas distinguish task `status` values (`pending|running|completed|failed|killed|paused` in `task_updated`), terminal notification (`completed|failed|stopped`), and live background membership. Do not conflate these event-specific values with a complete daemon state enum. None was captured from an executing daemon.
- Data path needing reverse: CLI -> supervisor discovery/IPC -> worker runtime -> transcript + registry -> attach/logs renderer -> restart reconnection.
- Compare Atlas: runtime/hub.py:1-17 is a separate *scheduled-agent* service, not established as identical to an interactive attachable supervisor (A-S).

## Workflow 4 — Subagent and team (S/R/U)
- Agent tool can launch foreground or background workers, with different tool eligibility and permission-prompt delivery; a background task can notify parent upon completion.
- Some team configurations have per-agent independent context, a common task list and direct named messages; official doc describes JSON mailbox paths at ~/.claude/teams/{team-name}/inboxes/{agent-name}.json.
- Team messages include plain text and structured plans/shutdown signals; confirmed *documentation*, not verified layout of version 2.1.302's active implementation.
- Static schema now declares task/run/tool IDs, parent task and depth, awaited/background flags, terminal output/summary/usage and parent_tool_use_id on message/progress frames. A background result can arrive later through a task notification linked by tool_use_id; the live background task list is a replace-all snapshot (`evidence/13-native-message-task-schemas.md`). Team mailbox write/claim, message identifiers, cancellation semantics and actual concurrency/failure behavior remain unobserved.
- Compare Atlas: agent/__init__.py:512-650 runs a separate worker and emits progress; post-completion deletes its session. UI ConversationActivity.tsx:132-190 supports progress, steer, cancel; no first-hand Claude mailbox equivalence established (A-S).

## Workflow 5 — Skills, plugins, hooks and MCP (D/U)
- CLI setup may source CLAUDE.md, project/user skills and plugin-scoped contributions. Hook events can intercept tool/agent lifecycle; SubagentStart hook receives agent_id, agent_type and can inject additionalContext; MCP supplies external server tools.
- Need exact precedence, event matching, hook reject/cancel/continue behavior, dynamic plugin load/reload, tool schema filtering and context-budget implications; not established from documents.
- Compare Atlas: plugins/runtime.py:122-313 discovers plugin component paths; runtime/hooks.py:60-90,287-348 parses/runs Claude-compatible hooks; tools/mcp_client.py:171-490 handles server connections. Backend-semantic parity remains **unproven** (A-S).

## Workflow 6 — Atlas GUI: verified source mapping only (A-S)
- Composer.tsx:40-44,152-205 performs slash-command matching, mentions and keyboard/history interaction.
- services/runtimeEvents.ts:25-84 normalizes RuntimeEventEnvelope, sequences, statuses/phases and retains at most 800 events in the active buffer.
- ConversationActivity.tsx:35-105 selects timeline rows; :132-190 shows steps + steer-subagent; :191-287 presents approval, question and proposed plan controls.
- shell/panels/ProcessesPanel.tsx:7-32 lists background processes, polls every three seconds and supports output/stop.
- components/ForkTree.tsx:12-67 projects parent/child branch relationships.
- These components substantiate front-end presence. No real Claude TUI image, serialized event sample or round-trip parity test was performed. The bounded Atlas ACP projection does not demonstrate the full Claude-native task/result schema.

## Suggested test captures (strictly controlled; see extraction request)
1. Terminal initial/exit/help rendering on Windows x64, sanitized terminal profile.
2. A 2-tool dry-run agent turn with actual stream-json, prompt/response/usage and interruption.
3. One child completing; one child denied/failed; one worker resumed; one team directed message if feature accessible.
4. Session fork, original preservation, restart, daemon attach, stop, respawn and output re-read.
5. Hooks with one matching and one nonmatching rule; MCP tool schema with disabled server.
Record command version plus exit code, monotonic sequence/timestamp and artifact paths. Mask all sensitive data and personal transcripts.

## Exact-binary observations added 2026-10-19

Evidence: `evidence/11-cli-probes.md`, executable SHA `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`.

- The native `--help` states interactive is the default and `-p/--print` is non-interactive. It registers `--resume`, `--continue`, `--fork-session`, `--output-format`, `--input-format`, `--bg/--background`, and `--agents`. These flags are **R-confirmed registrations**, but no session or stream was created.
- The `agents` view accepts `--json`; it includes active interactive/background sessions and optionally completed sessions with `--all`. It filters by `--cwd` and provides per-dispatch model, effort, permissions, settings, MCP and plugin options. The help explicitly says it does not require a TTY for JSON. Exact runtime JSON schema remains U.
- The `daemon` command exposes foreground `run`, `status`, `logs`, `uninstall`, `stop`; `attach`, `logs`, `stop`, `respawn`, `rm` are separate top-level commands. Help describes keeping background sessions running after attach returns to shell and restarting a session on current version. Runtime survival/recovery remains U.
- Plugin help lists marketplace and plugin lifecycle commands, plus `validate`; MCP help lists `serve`. These are real shipped surfaces, not proof of a configured plugin/MCP tool.
- Additional native CLI discoveries: `import` configuration from another AI coding agent, enterprise `gateway`, cloud-hosted multi-agent `ultrareview`, and worktree-aware `rm` flags. No server-side implementation is visible here.
- Static bundle strings locate `SendMessageTool`, `AgentTool`, `listSubagentIdsFromDisk`, `locateAgentTranscript`, `getDynamicTeamContext`, hook lifecycle helpers, `parent_tool_use_id`, lease/claim and respawn symbols. They enrich the reverse-engineering map, but cannot substitute for a screen/event/session trace.
- Follow-up on the exact binary: bounded source reads recover supervisor branch logic (`evidence/12`) and executable message/task schema builders (`evidence/13`), beyond strings alone. This gives declared task snapshot, delayed completion and result/permission metadata semantics; it still cannot substitute for a screen/event/session trace.
- Further exact-source trace follows `SendMessage` through tool registration, permission/recipient rewrite guards, unique teammate/session resolution, local inbox write, running-teammate wake, and local UDS/bridge routes (`evidence/14`). It distinguishes this direct-message tool from both shared task events and broad group-room turns. Mailbox read/ack and actual wake/turn delivery remain **U**.
- The same branch handles an `agent-evicted` local child: it checks/resolves durable resume metadata, coalesces concurrent resume calls, restores prior messages, and uses the current message as the resumed teammate's next prompt. If a matching task is already running, it queues to its inbox instead. This is static evidence only; no transcript was reopened and no agent was resumed.

## U boundaries for interactive UI
The interactive terminal renderer, input editing, focus/navigation, live task/status panels, status transitions and error/cancel rendering were not operated. Windows ConPTY imports and console subsystem are structural evidence only. Treat the documented /agent view or TUI behavior as D, and the exact command registration as R; visual details stay U.

## Synthetic isolated runtime attempt

The pinned binary ran in a newly-created scratch Git repo with isolated `CLAUDE_CONFIG_DIR`; it reached `system/init`, reported version/tools/skills/plugins/capabilities, and then repeated HTTP 401 `authentication_failed` responses. No UI action, assistant response or tool event followed. See exact command and limits in `END-TO-END-TRACES.md`. Earlier statements that R is only help/version probes are superseded: R now includes initialization and an authentication blocker, not a successful Agent run.
