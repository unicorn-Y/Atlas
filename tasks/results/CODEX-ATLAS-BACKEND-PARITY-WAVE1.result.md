# CODEX-ATLAS-BACKEND-PARITY-WAVE1 Result

## Delivery status

Implementation and Wave 1 regression coverage are complete. All 14 tests added for this task pass (the parity test class also runs the existing missing-run resume test). The required full `core/tests` run completed with **551 passed, 5 skipped, 1 failed**. The remaining failure is the pre-existing `test_provider_reference_hash_matches_node_generated_mixed_path_fixture`: this Windows host's Node runtime reports locale `zh-CN`, which is absent from `core/tests/fixtures/provider_hash_reference.json`. No Wave 1 test failed.

`pywinpty` was already available in the execution environment; `core/pyproject.toml` now declares it in the optional `terminal` extra so unsupported installations can still start the other backend routes. The full-suite run needed the declared `dbos==3.0.0` dependency installed into the test Python environment; durable tests passed after that.

## Section results

### 1. Run steering — complete

- `run.start` retains its existing shape; `/api/runtime/protocol` now advertises `1.3`.
- `/ws/chat` accepts `run.steer` with `run_id`, `content`, and `event_id`; the content enters the run's steer queue and is appended as a user message immediately before the next model call. It does not interrupt the active tool call.
- The server emits `run.steered` with `{content, event_id}` after injection. A terminal run receives `run.steer.rejected` with `{reason: "run_not_active"}`.
- Existing 1.2 `run.start` messages remain accepted; the message envelope did not gain a version gate.
- Test: `test_steer_queues_for_next_model_turn_and_rejects_finished_run` verifies the next model request contains the steer and that completed runs reject it.

### 2. Conversation pin/archive — complete

- `conversations` migration adds `pinned INTEGER NOT NULL DEFAULT 0` and `archived INTEGER NOT NULL DEFAULT 0`.
- `GET /api/conversations` returns both as booleans. `PUT /api/conversations/{id}` accepts optional `title`, `pinned`, and `archived` without changing omitted values.
- Test: `test_conversation_pin_archive_and_optional_title` checks persistence, omitted-title preservation, and 404 for a missing conversation.

### 3. Checkpoints and run diff — complete

- Checkpoint manifests carry `run_id` and `conversation_id`, including automatic local file checkpoints and CodeAct bridge checkpoints.
- `GET /api/checkpoints?run_id=&workspace=` returns `{id, workspace, created_at, run_id, files}`. Each file entry has `{path, exists, directory}`.
- `GET /api/runs/{run_id}/changes` returns `{run_id, files}`; each changed file has `{path, workspace, status, additions, deletions, diff}`. A diff above 200 KB is truncated and marked `truncated: true`.
- `run.completed.data` now includes `changes: {files, additions, deletions}`.
- Test: `test_checkpoint_diff_and_invalid_run_filter` checks metadata, returned fields, modified status, and unified diff content.

### 4. Processes and terminal — complete

- `GET /api/processes`, `GET /api/processes/{id}/output?after=`, and `POST /api/processes/{id}/kill` expose Atlas-owned process summaries, offset-based output, and cancellation. Unknown IDs return 404.
- `/ws/terminal?cwd=` starts a PowerShell PTY through pywinpty. It accepts `input` and `resize` messages and sends `output` and `exit`. Disconnect terminates the PTY. Missing pywinpty or an invalid cwd returns a clear WebSocket error while leaving REST routes available.
- Tests: `test_process_endpoints_read_output_kill_and_404`; `test_terminal_returns_explicit_missing_dependency_error`. A direct PowerShell PTY smoke emitted the `ATLAS_PTY_OK` marker.

### 5. Workspace tree and file — complete

- `GET /api/workspace/tree?root=<absolute>&path=<relative>` returns one directory level and hides `.git`, `node_modules`, `.venv`, and `__pycache__`. Entries carry `{name, path, type, size, git}`.
- `GET /api/workspace/file?root=&path=` returns UTF-8 text up to 512 KB, `truncated`, and `binary`; binary content is empty. Root escape attempts return 400.
- Test: `test_workspace_tree_file_and_path_escape` covers a normal listing/read and an escape rejection.

### 6. Usage and manual compaction — complete

- Successful model calls emit `run.usage` with `{input_tokens, output_tokens, context_tokens, context_limit, model}`; unavailable usage fields remain null. `run.completed.data.usage` sums known values and preserves null when a total cannot be derived.
- `POST /api/conversations/{id}/compact` calls `ContextMaintenance.compact` and returns `{before_tokens, after_tokens, summary}`. Missing conversations return 404.
- Test: `test_usage_sum_manual_compact_and_missing_conversation` covers token aggregation, compaction, and missing ID behavior.

### 7. Workspace rules — complete

- Runs load workspace-root `AGENTS.md`, `CLAUDE.md`, `.atlas/rules.md`, and user `~/.atlas/AGENTS.md`. Each source is capped at 64 KB and truncation is stated in the injected system instruction.
- The first run for a workspace emits `rules.loaded` with `{files: [{path, bytes}]}`. `GET /api/workspace/rules?root=` exposes the loaded candidates and their bounded content.
- Test: `test_workspace_rules_list_present_and_missing_roots` checks rule discovery and the empty result for a root without rule files.

### 8. Arbitrary file attachments — complete

- `run.start.files` validates base64 and enforces 10 MB per file / 20 MB total. Text MIME types, JSON, Markdown, CSV, and supported source extensions are inlined. Other files are stored under `~/.atlas/attachments/<run_id>/` and their absolute paths are added to the Agent input. Image `attachments` validation remains unchanged.
- Test: `test_file_attachment_inline_and_invalid_base64` covers text inlining and invalid input rejection. Size limits and binary storage use the same validation path.

### 9. Plan mode — complete

- `run.start.mode` accepts `plan` or `act`, defaulting to `act`; other values fail validation.
- Plan calls expose read-only local file actions and web fetch only. The dispatcher independently rejects local mutations in plan mode. A proposed `TaskPlan` is sent as `run.plan.proposed` with `event_id`; the run waits for the matching `run.plan.approve`, accepts optional `edits`, then continues in act mode. `run.cancel` ends a waiting plan.
- Test: `test_plan_tool_allowlist_and_validation` checks the read-only tool surface and that filtering does not mutate the original tool definitions.

### 10. Agent questions — complete

- The Agent can call `ask_user(question, options?)`. The run emits `input.required` with `{event_id, question, options}`, enters `waiting`, and uses the corresponding `input.response.text` as the tool result.
- Tests: `test_ask_user_event_waits_for_a_response` verifies the run waits and resumes with the response; the existing WebSocket protocol tests cover normal run completion.

### 11. Truncate and fork — complete

- `POST /api/conversations/{id}/truncate` accepts `{from_message_id}` and removes that message and later messages. `POST /api/conversations/{id}/fork` accepts `{through_message_id}`, copies messages through that point, and returns the new summary with `files_shared: true`. Missing messages return 404. No disk files are copied or restored.
- Test: `test_fork_truncate_and_missing_message` verifies both operations, copied message boundary, and an error path.

### 12. Chinese full-text search — complete

- The migration rebuilds `messages_fts` with FTS5 `trigram`, preserving existing message rows and recreating synchronization triggers. Queries shorter than three characters use `LIKE`; results include `title`.
- Test: `test_chinese_trigram_and_short_like_search` checks a Chinese phrase, the short-query fallback, and conversation title.

### 13. Per-conversation workspace — complete

- `run.start.workspace` must be absolute and existing. When omitted, the run uses the conversation's remembered workspace, then the associated project's `workspace_path`; absent both, existing process cwd behavior is retained.
- The selected directory is saved on the conversation and supplied as default cwd to local shell, exec, file, and edit tools.
- Test: `test_run_workspace_saved_and_invalid_mode_rejected` verifies persistence and rejects an unsupported run mode.

## Verification

- `python -m compileall -q core/atlas core/tests` — passed.
- `python -m pytest core/tests/test_server.py::TestBackendParityWave1 core/tests/test_agent_enrichment.py -q -p no:cacheprovider --basetemp core/.pytest-wave1-closeout` — **30 passed**.
- `python -m pytest core/tests -q -p no:cacheprovider --basetemp core/.pytest-wave1-final2` — **551 passed, 5 skipped, 1 failed**. The sole failure and its host-locale cause are recorded above.
- `git diff --check` — passed.
- No edits were made under `frontend/` or `backend-adapter/`.

## Interface deviations and remaining item

- No requested interface, event, or field name was changed. `pywinpty` is declared as an optional `terminal` install extra; the specified clear WebSocket error is returned when it is unavailable.
- The only unresolved acceptance item is the unrelated locale-sensitive provider-hash test fixture on this host. Its fixture does not contain `zh-CN`; fixing that fixture is outside this task's backend scope.
