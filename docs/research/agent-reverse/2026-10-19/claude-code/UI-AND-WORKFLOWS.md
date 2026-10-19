# Interface, protocol and workflow tracing

**R** = exact shipped 2.1.302 CLI help/version output; **S** = exact package/bundle literal/type evidence; **D** = official description; **A-S** = Atlas source observation; **U** = unobserved runtime behavior. The real PE was probed in an isolated empty profile. This report still does **not** claim native TUI screenshots, keyboard recordings, generated event captures or an authenticated agent run.

## Workflow 1 — CLI interactive lifecycle (R/D/U)
- Entry: claude launches interactive mode, claude "query" prepopulates first prompt.
- During work: commands and inline tool progress are displayed; /agents, /tasks, /mcp, /hooks, /model, /permissions are CLI commands described by official docs. /focus modifies rendering mode; model/permission controls change session configuration.
- Exit/re-entry: claude -c continues latest compatible project session; claude --resume ID/name selects session; --fork-session with resume generates a new identity rather than mutating old session; some commands also accept transcript paths.
- Verify: start/restart in an isolated project; capture terminal frames, session filenames and parent linkage. Differentiate named-session selection from stored transcript content. Native TUI control IDs and screen refresh engine remain **U**.

## Workflow 2 — Headless structured request (R/D/U)
- Entry: claude -p "query" --output-format stream-json --verbose --include-partial-messages
- Optional: --forward-subagent-text exposes child assistant/user text with parent_tool_use_id; --include-hook-events surfaces allowed hook lifecycle messages; --input-format stream-json allows structured requests and --replay-user-messages acknowledges stdin.
- Evidence needed: exact JSON lines for initialization, assistant text, tool use/results, subagent turn, usage and result, error and exit; fields must be copied from *generated sample*, not fabricated.
- UI consequence: a consumer must preserve parent/child provenance and status types; printing plain lines is insufficient. Atlas currently normalizes limited ACP types in core/atlas/runtime/external_agents.py:60-98 (A-S).

## Workflow 3 — Supervisable background session (R/S/U)
- Entry: claude --background "..." (also --bg); a supervisor may manage worker sessions.
- Inspection: claude agents --json [--all], claude logs ID, claude daemon status/logs; attach ID to re-enter interactive UI; respawn ID to restart while retaining conversation; stop/rm manage lifecycle.
- Distinguished statuses required: queued, active, waiting for permission/tool/agent, disconnected, stopped, resumed, failed, completed; do not claim exact state enum without native evidence.
- Data path needing reverse: CLI -> supervisor discovery/IPC -> worker runtime -> transcript + registry -> attach/logs renderer -> restart reconnection.
- Compare Atlas: runtime/hub.py:1-17 is a separate *scheduled-agent* service, not established as identical to an interactive attachable supervisor (A-S).

## Workflow 4 — Subagent and team (S/R/U)
- Agent tool can launch foreground or background workers, with different tool eligibility and permission-prompt delivery; a background task can notify parent upon completion.
- Some team configurations have per-agent independent context, a common task list and direct named messages; official doc describes JSON mailbox paths at ~/.claude/teams/{team-name}/inboxes/{agent-name}.json.
- Team messages include plain text and structured plans/shutdown signals; confirmed *documentation*, not verified layout of version 2.1.302's active implementation.
- Required field trace: parent session ID, child agent ID and name, parent_tool_use_id, message ID, task claim owner, cancellation/stop code, restart behavior; capture concurrency and failure test.
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
- These components substantiate front-end presence. No real Claude TUI image or round-trip parity test was performed.

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

## U boundaries for interactive UI
The interactive terminal renderer, input editing, focus/navigation, live task/status panels, status transitions and error/cancel rendering were not operated. Windows ConPTY imports and console subsystem are structural evidence only. Treat the documented /agent view or TUI behavior as D, and the exact command registration as R; visual details stay U.
