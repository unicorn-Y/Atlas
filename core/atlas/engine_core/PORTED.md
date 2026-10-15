# Atlas engine core ports

## BOOT-1 continuation fixes

- Added the X2 browser schemas to the Atlas agent catalog and dispatch browser calls through the run-scoped X2 context. The browser runtime is now reachable from a real chat; `browser_navigate` was verified against `https://example.com`.
- Completed source-split compatibility where delayed calls still expected monolithic Hermes helpers: real-profile consent now delegates to `browser_tool_cloud`; Bot Desktop host placement defaults to Atlas gateway execution and explicitly refuses non-host placement because Atlas does not ship Bot Desktop.
- Kept Hermes PM optional after uninstall: browser execution uses Atlas/host environment and a detected external `agent-browser`; lazy PM installs are skipped when PM is absent. Windows Chromium discovery includes installed Edge/Chrome locations.
- X2 config synchronization now writes compatibility YAML under the Atlas data/Hermes home (`config.yaml`), never to Atlas' TOML `config/atlas.toml`. The latter was restored in the test worktree from the source copy after this bug was found.
- Renamed X2 bridge logging's reserved `LogRecord` field from `module` to `bridge_module` so deferred bridge imports cannot fail while reporting an error.

This is the source map consumed by `atlas.upstream.watch`. The rows track Hermes source files and the commit each Atlas copy was adapted from. Files under `engine_core` are imported through the `atlas.engine_core` namespace; no import-time path injection is used.

| source | destination | commit |
|---|---|---|
| `agent/agent_hooks.py` | `core/atlas/engine_core/agent/agent_hooks.py` | `c9e076b` |
| `agent/browser_provider.py` | `core/atlas/engine_core/agent/browser_provider.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `agent/compaction_display.py` | `core/atlas/engine_core/agent/compaction_display.py` | `c9e076b` |
| `agent/context_breakdown.py` | `core/atlas/engine_core/agent/context_breakdown.py` | `c9e076b` |
| `agent/conversation_compression_archive.py` | `core/atlas/engine_core/agent/conversation_compression_archive.py` | `c9e076b` |
| `agent/message_content.py` | `core/atlas/engine_core/agent/message_content.py` | `c9e076b` |
| `agent/message_metadata.py` | `core/atlas/engine_core/agent/message_metadata.py` | `c9e076b` |
| `agent/deadline.py` | `core/atlas/engine_core/agent/deadline.py` | `c9e076b` |
| `agent/delegation_context.py` | `core/atlas/engine_core/agent/delegation_context.py` | `c9e076b` |
| `agent/message_sanitization.py` | `core/atlas/engine_core/agent/message_sanitization.py` | `c9e076b` |
| `agent/secret_scope.py` | `core/atlas/engine_core/agent/secret_scope.py` | `c9e076b` |
| `agent/proxy_sources/__init__.py` | `core/atlas/engine_core/agent/proxy_sources/__init__.py` | `c9e076b` |
| `agent/proxy_sources/iron_proxy.py` | `core/atlas/engine_core/agent/proxy_sources/iron_proxy.py` | `c9e076b` |
| `agent/terminal_env_registry.py` | `core/atlas/engine_core/agent/terminal_env_registry.py` | `c9e076b` |
| `hermes_time.py` | `core/atlas/engine_core/state/timefmt.py` | `c9e076b` |
| `tools/browser_camofox_state.py` | `core/atlas/engine_core/tools/browser_camofox_state.py` | `c9e076b` |
| `tools/browser_lightpanda.py` | `core/atlas/engine_core/tools/browser_lightpanda.py` | `c9e076b` |
| `tools/credential_files.py` | `core/atlas/engine_core/tools/credential_files.py` | `c9e076b` |
| `tools/env_passthrough.py` | `core/atlas/engine_core/tools/env_passthrough.py` | `c9e076b` |
| `tools/environments/__init__.py` | `core/atlas/engine_core/tools/environments/__init__.py` | `c9e076b` |
| `tools/environments/base.py` | `core/atlas/engine_core/tools/environments/base.py` | `c9e076b` |
| `tools/environments/base_output.py` | `core/atlas/engine_core/tools/environments/base_output.py` | `c9e076b` |
| `tools/environments/base_session_env.py` | `core/atlas/engine_core/tools/environments/base_session_env.py` | `c9e076b` |
| `tools/environments/base_wait.py` | `core/atlas/engine_core/tools/environments/base_wait.py` | `c9e076b` |
| `tools/environments/daytona.py` | `core/atlas/engine_core/tools/environments/daytona.py` | `c9e076b` |
| `tools/environments/docker.py` | `core/atlas/engine_core/tools/environments/docker.py` | `c9e076b` |
| `tools/environments/docker_egress.py` | `core/atlas/engine_core/tools/environments/docker_egress.py` | `c9e076b` |
| `tools/environments/file_sync.py` | `core/atlas/engine_core/tools/environments/file_sync.py` | `c9e076b` |
| `tools/environments/local.py` | `core/atlas/engine_core/tools/environments/local.py` | `c9e076b` |
| `tools/environments/local_env_policy.py` | `core/atlas/engine_core/tools/environments/local_env_policy.py` | `c9e076b` |
| `tools/environments/local_pythonpath.py` | `core/atlas/engine_core/tools/environments/local_pythonpath.py` | `c9e076b` |
| `tools/environments/managed_modal.py` | `core/atlas/engine_core/tools/environments/managed_modal.py` | `c9e076b` |
| `tools/environments/modal.py` | `core/atlas/engine_core/tools/environments/modal.py` | `c9e076b` |
| `tools/environments/path_utils.py` | `core/atlas/engine_core/tools/environments/path_utils.py` | `c9e076b` |
| `tools/environments/remote_common.py` | `core/atlas/engine_core/tools/environments/remote_common.py` | `c9e076b` |
| `tools/environments/singularity.py` | `core/atlas/engine_core/tools/environments/singularity.py` | `c9e076b` |
| `tools/environments/ssh.py` | `core/atlas/engine_core/tools/environments/ssh.py` | `c9e076b` |
| `tools/environments/streams.py` | `core/atlas/engine_core/tools/environments/streams.py` | `c9e076b` |
| `tools/environments/vercel_sandbox.py` | `core/atlas/engine_core/tools/environments/vercel_sandbox.py` | `c9e076b` |
| `tools/managed_tool_gateway.py` | `core/atlas/engine_core/tools/managed_tool_gateway.py` | `c9e076b` |
| `tools/mcp_liveness.py` | `core/atlas/engine_core/tools/mcp_liveness.py` | `c9e076b` |
| `tools/spill_safety.py` | `core/atlas/engine_core/tools/spill_safety.py` | `c9e076b` |
| `tools/terminal_scope.py` | `core/atlas/tools/terminal_scope.py` | `c9e076b` |
| `tools/terminal_tool_config.py` | `core/atlas/engine_core/tools/terminal_tool_config.py` | `c9e076b` |
| `tools/terminal_tool_backends.py` | `core/atlas/engine_core/tools/terminal_tool_backends.py` | `c9e076b` |
| `tools/terminal_tool_macos_open.py` | `core/atlas/engine_core/tools/terminal_tool_macos_open.py` | `c9e076b` |
| `tools/terminal_tool_sudo.py` | `core/atlas/engine_core/tools/terminal_tool_sudo.py` | `c9e076b` |
| `tools/todo_tool.py` | `core/atlas/engine_core/tools/todo_tool.py` | `c9e076b` |
| `tools/tool_output_limits.py` | `core/atlas/engine_core/tools/tool_output_limits.py` | `c9e076b` |
| `tools/tool_output_truncate.py` | `core/atlas/engine_core/tools/tool_output_truncate.py` | `c9e076b` |
| `tools/tool_search.py` | `core/atlas/engine_core/tools/tool_search.py` | `c9e076b` |
| `tools/tool_search_catalog.py` | `core/atlas/engine_core/tools/tool_search_catalog.py` | `c9e076b` |
| `tools/tool_search_validation.py` | `core/atlas/engine_core/tools/tool_search_validation.py` | `c9e076b` |
| `tools/url_safety.py` | `core/atlas/engine_core/tools/url_safety.py` | `c9e076b` |
| `tools/vision_tools.py` | `core/atlas/engine_core/tools/vision_tools.py` | `c9e076b` |
| `tools/vision_tools_history_budget.py` | `core/atlas/engine_core/tools/vision_tools_history_budget.py` | `c9e076b` |
| `tools/website_policy.py` | `core/atlas/engine_core/tools/website_policy.py` | `c9e076b` |
| `tools/bot_desktop/__init__.py` | `core/atlas/engine_core/tools/bot_desktop/__init__.py` | `c9e076b` |
| `tools/bot_desktop/browser.py` | `core/atlas/engine_core/tools/bot_desktop/browser.py` | `c9e076b` |
| `tools/bot_desktop/lease.py` | `core/atlas/engine_core/tools/bot_desktop/lease.py` | `c9e076b` |
| `tools/bot_desktop/placement.py` | `core/atlas/engine_core/tools/bot_desktop/placement.py` | `c9e076b` |
| `tools/bot_desktop/runtime.py` | `core/atlas/engine_core/tools/bot_desktop/runtime.py` | `c9e076b` |
| `tools/bot_desktop/sandbox_host.py` | `core/atlas/engine_core/tools/bot_desktop/sandbox_host.py` | `c9e076b` |
| `agent/plan_prompt.py` | `core/atlas/engine_core/agent/plan_prompt.py` | `c9e076b` |
| `agent/provider_base.py` | `core/atlas/engine_core/agent/provider_base.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `agent/redact.py` | `core/atlas/engine_core/agent/redact.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `agent/runtime_cwd.py` | `core/atlas/engine_core/agent/runtime_cwd.py` | `c9e076b` |
| `agent/title_generator.py` | `core/atlas/engine_core/agent/title_generator.py` | `c9e076b` |
| `agent/transcript_repair.py` | `core/atlas/engine_core/agent/transcript_repair.py` | `c9e076b` |
| `hermes_state.py` | `core/atlas/engine_core/state/hermes_state.py` | `c9e076b` |
| `hermes_state_common.py` | `core/atlas/engine_core/state/hermes_state_common.py` | `c9e076b` |
| `hermes_state_compression.py` | `core/atlas/engine_core/state/hermes_state_compression.py` | `c9e076b` |
| `hermes_state_coverage.py` | `core/atlas/engine_core/state/hermes_state_coverage.py` | `c9e076b` |
| `hermes_state_dbfile.py` | `core/atlas/engine_core/state/hermes_state_dbfile.py` | `c9e076b` |
| `hermes_state_errors.py` | `core/atlas/engine_core/state/hermes_state_errors.py` | `c9e076b` |
| `hermes_state_fts.py` | `core/atlas/engine_core/state/hermes_state_fts.py` | `c9e076b` |
| `hermes_state_gateway.py` | `core/atlas/engine_core/state/hermes_state_gateway.py` | `c9e076b` |
| `hermes_state_guard.py` | `core/atlas/engine_core/state/hermes_state_guard.py` | `c9e076b` |
| `hermes_state_health.py` | `core/atlas/engine_core/state/hermes_state_health.py` | `c9e076b` |
| `hermes_state_holders.py` | `core/atlas/engine_core/state/hermes_state_holders.py` | `c9e076b` |
| `hermes_state_identity.py` | `core/atlas/engine_core/state/hermes_state_identity.py` | `c9e076b` |
| `hermes_state_ids.py` | `core/atlas/engine_core/state/hermes_state_ids.py` | `c9e076b` |
| `hermes_state_lockguard.py` | `core/atlas/engine_core/state/hermes_state_lockguard.py` | `c9e076b` |
| `hermes_state_lockowners.py` | `core/atlas/engine_core/state/hermes_state_lockowners.py` | `c9e076b` |
| `hermes_state_maintenance.py` | `core/atlas/engine_core/state/hermes_state_maintenance.py` | `c9e076b` |
| `hermes_state_messages.py` | `core/atlas/engine_core/state/hermes_state_messages.py` | `c9e076b` |
| `hermes_state_pidns.py` | `core/atlas/engine_core/state/hermes_state_pidns.py` | `c9e076b` |
| `hermes_state_portability.py` | `core/atlas/engine_core/state/hermes_state_portability.py` | `c9e076b` |
| `hermes_state_profile_repair.py` | `core/atlas/engine_core/state/hermes_state_profile_repair.py` | `c9e076b` |
| `hermes_state_readpool.py` | `core/atlas/engine_core/state/hermes_state_readpool.py` | `c9e076b` |
| `hermes_state_registry.py` | `core/atlas/engine_core/state/hermes_state_registry.py` | `c9e076b` |
| `hermes_state_repair.py` | `core/atlas/engine_core/state/hermes_state_repair.py` | `c9e076b` |
| `hermes_state_rewind.py` | `core/atlas/engine_core/state/hermes_state_rewind.py` | `c9e076b` |
| `hermes_state_schema.py` | `core/atlas/engine_core/state/hermes_state_schema.py` | `c9e076b` |
| `hermes_state_search.py` | `core/atlas/engine_core/state/hermes_state_search.py` | `c9e076b` |
| `hermes_state_sessions.py` | `core/atlas/engine_core/state/hermes_state_sessions.py` | `c9e076b` |
| `hermes_state_telegram.py` | `core/atlas/engine_core/state/hermes_state_telegram.py` | `c9e076b` |
| `hermes_state_timeline.py` | `core/atlas/engine_core/state/hermes_state_timeline.py` | `c9e076b` |
| `hermes_state_titles.py` | `core/atlas/engine_core/state/hermes_state_titles.py` | `c9e076b` |
| `hermes_state_usage.py` | `core/atlas/engine_core/state/hermes_state_usage.py` | `c9e076b` |
| `hermes_state_wal.py` | `core/atlas/engine_core/state/hermes_state_wal.py` | `c9e076b` |
| `gateway/message_timestamps.py` | `core/atlas/engine_core/state/message_timestamps.py` | `c9e076b` |
| `hermes_cli/sqlite_safe_read.py` | `core/atlas/engine_core/state/sqlite_safe_read.py` | `c9e076b` |
| `hermes_cli/timefmt.py` | `core/atlas/engine_core/state/timefmt.py` | `c9e076b` |
| `tools/browser_camofox.py` | `core/atlas/engine_core/tools/browser_camofox.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_extension_router.py` | `core/atlas/engine_core/tools/browser_extension_router.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_supervisor.py` | `core/atlas/engine_core/tools/browser_supervisor.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_supervisor_capture.py` | `core/atlas/engine_core/tools/browser_supervisor_capture.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_supervisor_dialogs.py` | `core/atlas/engine_core/tools/browser_supervisor_dialogs.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_supervisor_frames.py` | `core/atlas/engine_core/tools/browser_supervisor_frames.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool.py` | `core/atlas/engine_core/tools/browser_tool.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_cdp.py` | `core/atlas/engine_core/tools/browser_tool_cdp.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_cloud.py` | `core/atlas/engine_core/tools/browser_tool_cloud.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_eval_policy.py` | `core/atlas/engine_core/tools/browser_tool_eval_policy.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_install.py` | `core/atlas/engine_core/tools/browser_tool_install.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_lifecycle.py` | `core/atlas/engine_core/tools/browser_tool_lifecycle.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_lightpanda_fallback.py` | `core/atlas/engine_core/tools/browser_tool_lightpanda_fallback.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_origin.py` | `core/atlas/engine_core/tools/browser_tool_origin.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_real_profile.py` | `core/atlas/engine_core/tools/browser_tool_real_profile.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_session.py` | `core/atlas/engine_core/tools/browser_tool_session.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_snapshot.py` | `core/atlas/engine_core/tools/browser_tool_snapshot.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_tool_vision.py` | `core/atlas/engine_core/tools/browser_tool_vision.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/browser_use_cli.py` | `core/atlas/engine_core/tools/browser_use_cli.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/budget_config.py` | `core/atlas/engine_core/tools/budget_config.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/interrupt.py` | `core/atlas/engine_core/tools/interrupt.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |
| `tools/registry.py` | `core/atlas/engine_core/tools/registry.py` | `c9e076b41f2163445b506b1cb79862d0dab0eecd` |

## Atlas-owned adapters and reduced surfaces

`config.py`, `hermes_constants.py`, `utils.py`, `agent/model_metadata.py`, `agent/turn_usage.py`, `agent/ssl_verify.py`, `agent/async_utils.py`, `agent/session_persistence.py`, `agent/session_activity.py`, `agent/skill_commands.py`, `agent/memory_manager.py`, `agent/vault_store.py`, `state/dashboard_procs.py`, `state/session_keys.py`, `state/startup_watchdog.py`, `state/sqlite_safe_read.py`, `state/timefmt.py`, `tools/tool_backend_helpers.py`, `tools/file_tools.py`, and the browser `computer_use/_platform.py` support are Atlas-owned adapters or narrow local implementations around the listed source ports.

The Hermes CUA plugin, provider plugin manager, auxiliary-client bootstrap, and unsupported cloud/extension/real-profile browser providers were not carried forward. Atlas uses its native computer runtime, ModelRouter, plugin runtime, and local browser path. The upstream watcher intentionally reports source diffs as review data; it does not merge or apply them.

## BOOT-1 import-check repair

The rows added above close the imports reported by `python scripts/diag/import_check.py core` against Hermes revision `c9e076b41f2163445b506b1cb79862d0dab0eecd`. In existing files, this repair also adds `tool_call_id_variants` and `tool_result_id_variants` (`agent/message_sanitization.py`), `estimate_messages_tokens_rough` (`agent/model_metadata.py`, implemented with Atlas' wire-shadow/tokenizer path), `safe_strftime` (`hermes_time.py`), `is_zeroed_sqlite_file` (`hermes_cli/sqlite_safe_read.py`), and the home, socket-temp, profile-scope, and environment helpers from `hermes_constants.py` / `agent/secret_scope.py`. `agent/vault_store.py` is ported with Atlas-owned config and atomic-write seams. The lazy `atlas.engine_core` package entry and `atlas.notifications.apprise.AppriseNotifier` compatibility name are Atlas adapters.

Explicitly unsupported surfaces remain explicit: Bot Desktop operations, selecting Lightpanda, remote credential-file mounts, Nous managed/free gateway authentication, and sudo execution. Atlas keeps its local built-in Chromium and local terminal paths. Hermes' `agent/credential_pool.py` is intentionally not copied: its custom-provider OAuth/plugin persistence has no Atlas-owned authority; Atlas provider keys continue through Atlas settings and keyring. There is no empty credential-pool shim or silent success path.

## BOOT-1 review addendum (Claude)

| source | destination | commit |
|---|---|---|
| `tools/arg_coercion.py` | `core/atlas/engine_core/tools/arg_coercion.py` | `c9e076b` |
| `tools/schema_sanitizer.py` | `core/atlas/engine_core/tools/schema_sanitizer.py` | `c9e076b` |

`tools/tool_search_validation.py` still imported Hermes' top-level `model_tools.coerce_tool_args` inside a try/except, so deferred-tool validation silently skipped argument coercion ("5" for an integer would be rejected). `import_check.py` only covers `atlas.*` imports, which is why it reported 0.

## Web search (atlas.websearch)

Translated, not copied: async httpx against the vendors' REST APIs (no exa-py / parallel-web SDKs), Atlas `[web]` config in `config/atlas.toml` instead of Hermes `config.yaml` / `~/.hermes/.env`, and nothing imported from Hermes. Atlas additions with no Hermes counterpart: Bocha (Chinese index, `providers/keyed.py`), Chinese-query routing (`router.py`), a full failover chain instead of one backend + one-shot keyless rescue, Tavily in the keyless ring, and the free local page reader (`providers/local.py`). Dropped: Nous managed gateway, Firecrawl keyless (refuses proxy exit IPs), xAI and OpenAI-native search (need those vendors' model keys).

| source | destination | commit |
|---|---|---|
| `agent/web_search_provider.py` | `core/atlas/websearch/providers/base.py` | `c9e076b` |
| `agent/web_search_registry.py` | `core/atlas/websearch/providers/__init__.py` | `c9e076b` |
| `plugins/web/_common.py` | `core/atlas/websearch/common.py` | `c9e076b` |
| `plugins/web/keyless_mcp.py` | `core/atlas/websearch/keyless.py` | `c9e076b` |
| `plugins/web/exa/provider.py` | `core/atlas/websearch/providers/keyed.py` | `c9e076b` |
| `plugins/web/parallel/provider.py` | `core/atlas/websearch/providers/keyed.py` | `c9e076b` |
| `plugins/web/tavily/provider.py` | `core/atlas/websearch/providers/keyed.py` | `c9e076b` |
| `plugins/web/brave_free/provider.py` | `core/atlas/websearch/providers/keyed.py` | `c9e076b` |
| `plugins/web/keenable/provider.py` | `core/atlas/websearch/providers/keyed.py` | `c9e076b` |
| `plugins/web/perplexity/provider.py` | `core/atlas/websearch/providers/keyed.py` | `c9e076b` |
| `plugins/web/searxng/provider.py` | `core/atlas/websearch/providers/keyed.py` | `c9e076b` |
| `plugins/web/ddgs/provider.py` | `core/atlas/websearch/providers/ddgs.py` | `c9e076b` |
| `plugins/web/ddgs/_search_worker.py` | `core/atlas/websearch/providers/_ddgs_worker.py` | `c9e076b` |
| `tools/web_tools.py` | `core/atlas/websearch/service.py` | `c9e076b` |
| `tools/web_tools_rescue.py` | `core/atlas/websearch/service.py` | `c9e076b` |
| `tools/web_result_cache.py` | `core/atlas/websearch/cache.py` | `c9e076b` |
| `tools/web_tools_truncate.py` | `core/atlas/websearch/cache.py` | `c9e076b` |

## Independent side sessions (atlas.sessions)

Translated from OpenClaw (MIT) `openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1`, behaviour contract from Claude Desktop's `start_session` / `SendMessage` / `dismiss_task` (closed source, followed from its tool definitions). Nothing imported from OpenClaw. Atlas delta: a child is a normal Atlas conversation driven by the same `run.start` path as the desktop on a server-side connection, so the sidebar shows it, the desktop attaches to its live run by run id, approvals/stop work as usual; proposal cards (offer / own_initiative) the user starts; a turn started by another session or a report can only propose; stopped sessions never report; reports steered into a run that ended unread start the next turn instead of being lost.

| source | destination |
|---|---|
| `src/agents/tools/sessions-spawn-visible.ts` | `core/atlas/sessions/hub.py` (`_launch`, worktree / inheritance) |
| `src/agents/tools/sessions-spawn-visible.schema.ts` | `core/atlas/sessions/tools.py` (`session_start`) |
| `src/agents/tools/sessions-send-tool.ts`, `sessions-send-tool.schema.ts` | `core/atlas/sessions/hub.py` (`send`), `tools.py` (`session_send`) |
| `src/agents/subagents/announce/subagent-announce-active-wake.ts` | `core/atlas/sessions/hub.py` (`_deliver_report`: steer active parent, else wake) |
| `src/agents/subagents/announce/subagent-announce-output.ts` | `core/atlas/sessions/hub.py` (`_report_text`, `_stats_line`) |
| `src/agents/subagents/registry/subagent-registry-helpers.ts` | `core/atlas/sessions/store.py` |

## Idle compaction, hook onFailure, taskbar status, send_user_file

Closed-source designs (Claude Code 2.1.295 / 2.1.299 changelog, Claude `SendUserFile`), reimplemented: `core/atlas/sessions/idle_compaction.py` (configurable window and threshold instead of a fixed 54 min / 200K), `core/atlas/runtime/hooks.py` (`onFailure: "block"` for Claude-format hooks, `on_failure` for Atlas hooks), `frontend/src/main/electron.ts` (`window:run-status` = desktop form of the OSC 7501 Program Status Protocol), `core/atlas/sessions/tools.py` (`send_user_file`).

## Web-wide discovery (atlas.evolution.discovery)

Atlas-original (no open-source agent ships an equivalent): sources follow `docs/research/2026-09-30-landscape/10-tracking-sources.md`; drafts plug into the existing E4 index (`taskbook_draft.py`).
