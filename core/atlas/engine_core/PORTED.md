# Atlas engine core ports

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

`config.py`, `hermes_constants.py`, `agent/model_metadata.py`, `agent/turn_usage.py`, `agent/ssl_verify.py`, `agent/async_utils.py`, `agent/session_persistence.py`, `agent/session_activity.py`, `agent/skill_commands.py`, `agent/memory_manager.py`, `agent/vault_store.py`, `state/dashboard_procs.py`, `state/session_keys.py`, `state/startup_watchdog.py`, `state/sqlite_safe_read.py`, `state/timefmt.py`, `tools/tool_backend_helpers.py`, `tools/file_tools.py`, and the browser `computer_use/_platform.py` support are Atlas-owned adapters or narrow local implementations around the listed source ports.

The Hermes CUA plugin, provider plugin manager, auxiliary-client bootstrap, and unsupported cloud/extension/real-profile browser providers were not carried forward. Atlas uses its native computer runtime, ModelRouter, plugin runtime, and local browser path. The upstream watcher intentionally reports source diffs as review data; it does not merge or apply them.
