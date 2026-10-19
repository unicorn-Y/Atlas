# 函数索引（关键路径）

共 266 个关键符号。全仓库 Rust 函数总数：**59,107**（`grep -E "fn "` 实测）。

本索引只覆盖核心执行路径；完整枚举需 AST 解析（未做，见 UNKNOWNS）。


## `app-server/src/lib.rs`

- L88 — `fn is_unsupported_untrusted_approval_policy_error`
- L170 — `fn stderr_span_events`
- L218 — `async fn shutdown_signal`
- L247 — `fn requested`
- L251 — `fn forced`
- L255 — `fn on_signal`
- L278 — `fn update`
- L312 — `fn config_warning_from_error`
- L328 — `fn config_error_location`
- L340 — `fn exec_policy_warning_location`
- L362 — `fn exec_policy_config_warning`
- L372 — `fn app_text_range`
- L385 — `fn project_config_warning`
- L425 — `fn from_env_value`
- L433 — `fn log_format_from_env`
- L438 — `async fn run_main`
- L462 — `enum AppServerExit`
- L469 — `enum PluginStartupTasks`
- L475 — `struct AppServerRuntimeOptions`
- L484 — `fn default`
- L496 — `async fn run_main_with_transport_options`
- L1395 — `async fn init_sqlite_state_db_with_fresh_start_on_corruption`
- L1465 — `fn sqlite_home_is_blocking_file`
- L1472 — `fn sqlite_recovery_notice`
- L1496 — `fn emit_state_db_backup_warning`
- L1506 — `fn test_user_config_file_from_env`
- L1518 — `fn loader_overrides_with_test_user_config_file`
- L1543 — `fn analytics_rpc_transport`
- L1572 — `fn shutdown_waits_for_admitted_requests_but_force_remains_available`
- L1604 — `fn log_format_from_env_value_matches_json_values_case_insensitively`
- L1611 — `fn log_format_from_env_value_defaults_for_non_json_values`
- L1623 — `fn debug_test_user_config_file_overrides_loader_path`

## `code-mode-protocol/src/session.rs`

- L28 — `struct CodeModeSessionCellExecutionLimits`
- L34 — `struct CellId`
- L37 — `fn new`
- L41 — `fn as_str`
- L47 — `fn as_ref`
- L53 — `fn fmt`
- L58 — `struct StartedCell`
- L64 — `fn new`
- L72 — `fn from_result_receiver`
- L83 — `fn from_future`
- L93 — `async fn initial_response`
- L102 — `trait CodeModeSessionDelegate`
- L103 — `fn invoke_tool`
- L109 — `fn notify`
- L118 — `fn cell_closed`
- L122 — `struct NoopCodeModeSessionDelegate`
- L125 — `fn invoke_tool`
- L136 — `fn notify`
- L146 — `fn cell_closed`
- L154 — `trait CodeModeSession`
- L157 — `fn execute`
- L165 — `fn wait`
- L171 — `fn terminate`
- L173 — `fn shutdown`
- L180 — `trait CodeModeSessionProvider`
- L182 — `fn availability`
- L186 — `fn create_session`
- L192 — `fn create_session_with_limits`

## `core/src/compact.rs`

- L67 — `struct AutoCompactionDisabled`
- L73 — `struct CompactedHistoryMetadata`
- L84 — `async fn build_compaction_replacement_history`
- L101 — `fn assemble_compaction_history`
- L117 — `async fn run_inline_auto_compact_task`
- L154 — `async fn run_compact_task`
- L177 — `async fn run_compact_task_inner`
- L263 — `async fn run_compact_task_inner_impl`
- L438 — `struct CompactionAnalyticsAttempt`
- L451 — `struct CompactionAnalyticsDetails`
- L460 — `async fn begin`
- L482 — `async fn track`
- L532 — `fn compaction_status_from_result`
- L547 — `fn content_items_to_text`
- L567 — `struct CompactedUserMessage`
- L577 — `fn collect_user_messages`
- L584 — `fn collect_annotated_user_messages`
- L593 — `fn compacted_user_message`
- L611 — `fn is_summary_message`
- L615 — `fn is_real_user_or_agent_message`
- L640 — `fn insert_initial_context_before_last_real_user_or_summary`
- L691 — `fn build_compacted_history`
- L704 — `fn build_compacted_history_with_limit`
- L791 — `async fn drain_to_completed`

## `core/src/compact_token_budget.rs`

- L21 — `async fn run_manual_compact_task`
- L34 — `async fn run_inline_auto_compact_task`
- L42 — `async fn run_compact_task_inner`

## `core/src/session/turn.rs`

- L147 — `struct McpStartupRequirements`
- L166 — `async fn run_turn`
- L910 — `async fn turn_diff_display_roots`
- L933 — `async fn run_hooks_and_record_inputs`
- L983 — `fn turn_user_input`
- L997 — `async fn required_mcp_servers_for_input`
- L1099 — `async fn build_skills_and_plugins`
- L1244 — `async fn build_extension_turn_input_items`
- L1304 — `async fn track_turn_resolved_config_analytics`
- L1372 — `async fn run_pre_sampling_compact`
- L1406 — `fn comp_hash_changed`
- L1416 — `async fn maybe_run_previous_model_inline_compact`
- L1507 — `async fn run_auto_compact`
- L1666 — `fn build_prompt`
- L1707 — `async fn run_sampling_request`
- L1839 — `struct PreparedToolRecommendations`
- L1845 — `async fn prepare_tool_recommendations`
- L1892 — `async fn built_tools`
- L2004 — `fn new`
- L2030 — `fn parser_mut`
- L2055 — `fn drain_finished`
- L2065 — `fn new`
- L2073 — `async fn start`
- L2085 — `async fn push_delta`
- L2102 — `async fn complete_with_text`
- L2123 — `async fn maybe_emit_pending_agent_message_start`
- L2287 — `async fn handle_plan_segments`
- L2350 — `async fn emit_streamed_assistant_text_delta`
- L2385 — `async fn flush_assistant_text_segments_for_item`
- L2397 — `async fn flush_assistant_text_segments_all`
- L2416 — `async fn maybe_complete_plan_item_from_message`
- L2445 — `async fn emit_agent_message_in_plan_mode`
- L2490 — `async fn emit_turn_item_in_plan_mode`
- L2511 — `async fn handle_assistant_item_done_in_plan_mode`
- L2565 — `async fn drain_in_flight`
- L2595 — `fn assign_missing_streamed_response_item_id`
- L2618 — `async fn try_run_sampling_request`
- L3317 — `fn get_last_assistant_message_from_turn`

## `core/src/tools/registry.rs`

- L59 — `trait CoreToolRuntime`
- L61 — `fn finishes_on_cancellation`
- L66 — `fn is_builtin_control_tool`
- L71 — `fn immutable_spec`
- L78 — `fn cached_code_mode_definitions`
- L87 — `fn wait_until_ready`
- L93 — `fn is_third_party_tool`
- L98 — `fn mcp_server_name`
- L102 — `fn matches_kind`
- L109 — `fn telemetry_tags`
- L114 — `fn on_tool_result_accepted`
- L116 — `fn post_tool_use_payload`
- L150 — `fn pre_tool_use_payload`
- L165 — `fn with_updated_hook_input`
- L189 — `fn create_diff_consumer`
- L196 — `trait ToolArgumentDiffConsumer`
- L198 — `fn consume_diff`
- L202 — `fn finish`
- L207 — `struct AnyToolResult`
- L215 — `fn into_response`
- L232 — `fn code_mode_result`
- L246 — `fn log_output`
- L250 — `fn success_for_logging`
- L254 — `fn set_handler_duration_ms`
- L258 — `fn fallback_token_limit_override`
- L262 — `fn to_response_item`
- L266 — `fn code_mode_result`
- L270 — `fn tool_result_metadata`
- L276 — `struct PreToolUsePayload`
- L290 — `struct PostToolUsePayload`
- L305 — `struct RegisteredTool`
- L314 — `fn spec`
- L323 — `fn cached_runtime`
- L330 — `struct ToolRegistry`
- L338 — `fn search_info`
- L354 — `fn apply_functions_namespace_function_prefixes`
- L369 — `fn prepare_tool`
- L385 — `fn with_tool_policy`
- L393 — `fn from_tools`
- L403 — `fn add`
- L410 — `fn add_with_exposure`
- L417 — `fn register_trusted`
- L422 — `fn register_trusted_with_exposure`
- L443 — `fn prepend_trusted`
- L458 — `fn register_external`
- L463 — `fn register_external_with_exposure`
- L500 — `fn record_collision`
- L504 — `fn first_collision`
- L508 — `fn remove`
- L514 — `fn entries`
- L518 — `fn entries_mut`
- L523 — `fn mcp_namespaces`
- L529 — `fn deferred_tool_namespaces`
- L564 — `fn empty_for_test`
- L569 — `fn with_handler_for_test`
- L576 — `fn tool`
- L581 — `fn registered_tool`
- L586 — `fn tool_names_for_test`
- L593 — `fn tool_exposure`
- L599 — `fn create_diff_consumer`
- L606 — `fn supports_parallel_tool_calls`
- L615 — `async fn dispatch_any_with_state`
- L899 — `async fn notify_tool_finish_if_unclaimed`
- L912 — `async fn handle_any_tool`
- L943 — `fn function_hook_tool_name`
- L954 — `fn function_hook_tool_input`
- L962 — `fn unsupported_tool_call_message`

## `core/src/tools/router.rs`

- L48 — `struct ToolCall`
- L56 — `fn direct_source`
- L74 — `fn tool_log_payload`
- L85 — `struct ToolRouter`
- L95 — `enum ToolSuggestPresentation`
- L101 — `struct ToolSuggestCandidates`
- L108 — `fn from_registry`
- L125 — `fn from_parts`
- L148 — `fn model_visible_specs`
- L152 — `fn tool_mode`
- L157 — `fn requires_code_mode_worker`
- L162 — `fn code_mode_tool_names`
- L167 — `fn tool_namespaces_info`
- L173 — `fn has_terminal_controls`
- L180 — `fn can_manage_children`
- L185 — `fn exposes_tool`
- L218 — `fn deferred_tool_namespaces`
- L222 — `fn mcp_namespaces`
- L227 — `fn registered_tool_names_for_test`
- L232 — `fn tool_exposure_for_test`
- L239 — `fn create_diff_consumer`
- L246 — `fn tool_supports_parallel`
- L252 — `fn registered_tool`
- L257 — `fn build_tool_call`
- L313 — `async fn dispatch_tool_call_with_code_mode_result`
- L336 — `async fn dispatch_tool_call_with_state`
- L359 — `async fn dispatch_tool_call_with_code_mode_result_inner`
- L398 — `fn record_registration_metrics`

## `core/src/tools/spec_plan.rs`

- L121 — `fn build_tool_router`
- L189 — `fn code_mode_only_strict_3p_tools`
- L197 — `fn apply_mcp_tool_exposure_policy`
- L293 — `fn build_core_tool_registry`
- L321 — `fn append_source_tools`
- L349 — `fn extension_tool_executors`
- L368 — `fn finalize_tool_router`
- L555 — `fn apply_direct_model_only_namespace_overrides`
- L577 — `fn tool_exposure_with_namespace_override`
- L602 — `fn enforce_strict_3p_tools`
- L627 — `fn build_model_visible_specs`
- L657 — `fn spec_for_model_request`
- L686 — `fn hosted_model_tool_specs`
- L717 — `fn tool_suggest_enabled`
- L724 — `fn multi_agent_v2_enabled`
- L728 — `fn collab_tools_enabled`
- L743 — `fn required_child_management_tool_names`
- L782 — `fn image_generation_available`
- L819 — `fn wait_agent_timeout_options`
- L835 — `fn agent_type_description`
- L848 — `fn is_hidden_by_code_mode_only`
- L862 — `fn is_directly_visible`
- L876 — `fn is_excluded_from_code_mode`
- L887 — `fn prepare_function_description_prefixes`
- L950 — `fn code_mode_tools`
- L1012 — `fn register_code_mode_executors`
- L1103 — `fn merge_into_namespaces`
- L1154 — `fn code_mode_namespace_descriptions`
- L1177 — `fn add_core_tool_sources`
- L1199 — `fn standalone_web_search_enabled`
- L1209 — `fn tool_environment_mode`
- L1225 — `fn should_include_windows_shell_guidance`
- L1245 — `fn add_shell_tools`
- L1289 — `fn add_mcp_resource_tools`
- L1307 — `fn add_core_utility_tools`
- L1462 — `fn add_collaboration_tools`
- L1595 — `fn append_dynamic_tool_runtimes`
- L1628 — `fn append_tool_search_executor`
- L1647 — `fn append_extension_tool_executors`
- L1677 — `fn compare_code_mode_tools`
- L1691 — `fn code_mode_namespace_name`

## `exec-server/src/process_sandbox.rs`

- L49 — `struct PreparedExecRequest`
- L70 — `fn windows_sandbox_spawn_request`
- L90 — `async fn prepare_exec_request_with_telemetry`
- L349 — `async fn prepare_managed_network`
- L443 — `fn native_path`