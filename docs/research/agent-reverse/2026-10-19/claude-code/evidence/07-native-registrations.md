# Shipped CLI registration surface

Observed by executing this exact 2.1.302 PE with isolated empty `CLAUDE_CONFIG_DIR`, `APPDATA`, `LOCALAPPDATA`, `HOME`, and `USERPROFILE`, using only `--help` (full per-command excerpts are summarized in `11-cli-probes.md`). This is R-level evidence that these command registrations are present in the shipped binary; it is not evidence that auth-gated operations work.

Top-level `claude --help` exposes: `agents`, `attach`, `auth`, `auto-mode`, `doctor`, `gateway`, `import`, `install`, `logs`, `mcp`, `plugin|plugins`, `purge`, `respawn`, `rm`, `setup-token`, `stop|kill`, `ultrareview`, `update|upgrade` plus the interactive/default and print modes.

For `--print`, native help describes `--output-format stream-json` as realtime JSONL events; `--input-format stream-json` supports structured input; `--include-partial-messages` exposes partial chunks. `--forward-subagent-text` says child text/thinking can be forwarded as assistant/user messages with `parent_tool_use_id`; `--include-hook-events` exposes hook lifecycle events. These are shipped flag registrations/descriptions, not a captured emitted stream.

Observed behavior descriptions include:

- `agents --json` lists active interactive/background sessions as JSON; `--all` includes completed background sessions; `--cwd` filters sessions by starting path. Dispatch options set model, effort, permission mode/restricted state, settings sources, MCP config and plugin dirs.
- `attach <id|name>` opens a background session in a terminal; `logs`, `stop`, `respawn`, and `rm` target background sessions. `rm --help` additionally advertises `--discard-unpushed <commit>@<worktree-id>` and `--force-remove-worktree <worktree-id>`.
- `daemon` exposes foreground `run`, `status`, `logs`, `uninstall`, and `stop`; help gives default `~/.claude/daemon.json` and `~/.claude/daemon.log` paths. No daemon status command was run.
- `plugin` supports marketplace add/list/update/remove, install/uninstall/enable/disable, validate. `mcp` supports server configuration; its `serve` command starts the Claude Code MCP server.
- `import` targets configuration from another AI coding agent; `gateway` is described as enterprise auth/telemetry gateway; `ultrareview` is described as cloud-hosted multi-agent code review. Private server behavior remains outside the inspected package.

Binary string/module anchors at `06-native-string-index.jsonl` add candidate registration/lifecycle names for background dispatch, self-hosted runner restrictions, Agent/SendMessage tools, hook events, transcript lookup and respawn state. Since Bun's embedded bundle is not decompiled here, those names are not asserted to be callable function bodies.

