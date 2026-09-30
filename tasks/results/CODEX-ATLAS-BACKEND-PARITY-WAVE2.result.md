# CODEX-ATLAS-BACKEND-PARITY-WAVE2

STATUS: DELIVERED
BASE_HEAD: `dc6ce0ffca763131ae376c3b1c3eb8044aa047fd`
PREDECESSOR: `CODEX-ATLAS-BACKEND-PARITY-WAVE1` — ACCEPTED

## Delivery summary

Implemented all 12 taskbook sections in backend code. No changes were made under `frontend/`, `backend-adapter/`, or `core/atlas/origin_guard.py`. Runtime protocol is `1.4`. New tests and test data use `tmp_path`; pytest basetemp was kept in the Windows system temp directory.

## Section results

1. **Git worktree isolation — complete.** `run.start.worktree` creates and reuses a per-conversation worktree; conversation records and `GET /api/conversations` expose `worktree_path`, `worktree_branch`, and `base_branch`. Added `GET /api/conversations/{id}/worktree`, `POST /api/conversations/{id}/worktree/merge`, `DELETE /api/conversations/{id}/worktree`, and `GET /api/git/branches`. Dirty removal is rejected unless forced. Merge and squash conflicts return 409 and clean the base worktree state. Tests create temporary Git repositories and cover success, non-Git validation, dirty removal, and both conflict strategies. The optional `worktree.name` input is accepted; prescribed path and branch names remain derived from the conversation ID.
2. **Sub-agent progress and cancellation — complete.** Delegation emits `subtask.started`, throttled `subtask.progress`, and `subtask.completed` through the parent run's sequence. Added `POST /api/runs/{run_id}/subtasks/{subtask_id}/cancel`; cancellation targets the child task. Tests cover progress throttling, completion summary, cancellation and missing IDs.
3. **Recipes — complete.** Added TOML-backed `GET/POST/PUT/DELETE /api/recipes`, `POST /api/recipes/{id}/render`, and `POST /api/recipes/from-run`. Rendering substitutes declared parameters and returns 422 with missing parameter names. From-run retains the run prompt, skills, mode, workspace, and profile. Tests cover CRUD, render, missing parameters, and from-run fields.
4. **Profiles and modes — complete.** Added TOML-backed `GET/POST /api/profiles`, `PUT/DELETE /api/profiles/{id}`, and built-in `default`, `architect`, and `reviewer` profiles. `run.start.profile_id` supplies defaults while explicit model, skills, and mode take precedence. Allow/deny policy is checked at tool dispatch and through the nested CodeAct tool bridge. FULL_ACCESS remains the default; built-in read-only roles reject writes. Tests cover built-ins, CRUD, validation, and dispatch policy.
5. **Reasoning effort — complete.** `run.start.reasoning_effort` accepts `minimal|low|medium|high`, is passed only when LiteLLM reports support, and unsupported requests report `reasoning_effort_applied: false` on the first usage event. `/api/models` includes `supports_reasoning_effort`; unknown capability data fails closed. Tests cover supported and unavailable LiteLLM capability responses.
6. **Workspace search and references — complete.** Added `GET /api/workspace/search?root=&q=&limit=`, filename subsequence matching, relevance ordering, `.gitignore` handling, and the same ignored directories as the tree endpoint. `run.start.context_files` injects relative workspace files with 64 KiB per-file and 256 KiB total limits and truncation markers. `context_conversations` accepts up to three references and summarizes each last-20-message slice with `ContextMaintenance`. Tests cover fuzzy search, ignored paths, bounded file context, and path escape rejection.
7. **Side chat — complete.** `run.start.ephemeral: true` clones source history to a temporary conversation, runs with read-only dispatch restrictions, and removes the temporary conversation after completion. Concurrent runs for the same source conversation are allowed. A regression test verifies the source transcript remains unchanged and the temporary transcript is removed.
8. **Conversation fork and duplicate — complete.** Fork records `parent_conversation_id` and `fork_message_id`; `summarize: true` inserts the ContextMaintenance summary as the first system message. Added `POST /api/conversations/{id}/duplicate` to copy the full transcript. Tests cover links, summary ordering, and full duplication.
9. **Goal editing — complete.** Added `PUT /api/goals/{id}`, `/pause`, and `/resume`. Replacing a goal updates its action, resets `goal_status` to pending, and records `goal.replaced`. Pause disables the scheduled task and blocks heartbeat invocation; resume reactivates it. Tests cover replace, event, pause, and resume behavior.
10. **Raw workspace reads — complete.** Added `GET /api/workspace/raw?root=&path=` with extension-based content types, streaming, a 50 MB cap, and `_workspace_path` traversal protection. Tests cover HTML content type/body and traversal rejection.
11. **Large tool output — complete.** Tool results over 16 KiB are written in full to `<data>/tool-results/<run_id>/<call_id>.txt`; model context receives 4 KiB byte-bounded head/tail previews, the file path, and instructions to use the file tool for the complete output. `tool.completed.data` exposes `full_output_path`. Tests cover externalization, bounded preview, small-result behavior, and event field mapping.
12. **Miscellaneous — complete.** Historical result files identify repository-local `--basetemp core/.pytest-wave1-*` invocations as the source of the pre-existing `core/.pytest-*` directories. This run used `%TEMP%` basetemp with cacheprovider disabled and created no repository-local pytest directory. Added the Node `zh-CN` provider-hash reference fixture; the locale regression passes.

## Verification

- `python -m compileall -q core/atlas core/tests` — passed.
- `git diff --check` — passed.
- Focused regression: `$tempBase = Join-Path $env:TEMP ('atlas-wave2-final-focused-' + [guid]::NewGuid().ToString('N')); python -m pytest core/tests/test_backend_parity_wave2.py core/tests/test_server.py core/tests/test_goal_scheduler.py core/tests/test_agent.py core/tests/test_agent_enrichment.py core/tests/test_skill_acquisition.py -q -p no:cacheprovider --basetemp $tempBase --tb=short` — **183 passed**. Later focused run: `$tempBase = Join-Path $env:TEMP ('atlas-wave2-tests-final-' + [guid]::NewGuid().ToString('N')); python -m pytest core/tests/test_backend_parity_wave2.py core/tests/test_agent.py core/tests/test_agent_enrichment.py core/tests/test_server.py core/tests/test_goal_scheduler.py -q -p no:cacheprovider --basetemp $tempBase --tb=short` — **152 passed** before the final conflict-cleanup and child-summary edits.
- Final backend suite: `$tempBase = Join-Path $env:TEMP ('atlas-wave2-acceptance-' + [guid]::NewGuid().ToString('N')); python -m pytest core/tests -q -p no:cacheprovider --basetemp $tempBase --ignore=core/tests/test_computer_use.py --tb=short` — **572 passed, 5 skipped**. `test_computer_use.py` was excluded as explicitly permitted by the taskbook because it manipulates the real mouse.
- `/api/runtime/protocol` — **1.4**.
- `test_provider_reference_hash_matches_node_generated_mixed_path_fixture` — passed with the `zh-CN` fixture.

## Incomplete items and deviations

- No taskbook section remains incomplete.
- The taskbook names `worktree.name` but defines the path and branch from the conversation short ID and gives no separate behavior for `name`; the field is accepted without changing those fixed names.
- The real-mouse `test_computer_use.py` was not run; all other `core/tests` were included in the final suite.
