# CODEX-ATLAS-BACKEND-PARITY-WAVE3 Result

## Outcome

Implemented the six backend taskbook sections. `frontend/` and `backend-adapter/` were not changed. `core/atlas/origin_guard.py` remains unchanged and in the HTTP/WebSocket request paths. The runtime protocol reports `1.5`.

The full required `core/tests` gate is **not verified**. The runner interrupted pytest while the full run was in progress; the visible partial result was 58 passed and 1 skipped in 13.47 seconds. `test_computer_use.py` was excluded as permitted. Focused tests and the remaining test groups below do not replace the incomplete full-suite gate.

## Section results

### 1. Second-wave follow-ups — implemented

- `POST /api/recipes/from-run` stores the conversation's original `workspace`, even when the run used a worktree. The default description is `从一次任务生成`.
- Fork and duplicate retain the source workspace without copying worktree linkage; the fork response retains the existing `files_shared` field.
- Worktree names are converted to a lowercase `[a-z0-9-]` suffix, with nonmatching characters replaced by `-` and a 24-character maximum.
- Added normal and error coverage for recipe creation; fork, workspace and branch behavior were also exercised.

### 2. Unified scheduler — implemented

- `schedules.toml` is the shared task store. Legacy `hub-schedules.toml` tasks migrate once; colliding IDs gain `-hub`, then the legacy file is renamed with `.migrated`.
- A heartbeat lease in `scheduler.lock` elects one desktop or Hub trigger owner. Hub can preempt desktop; desktop can take ownership after Hub exits. Event tasks, file-change debounce, bounded run history, shared-store refresh, pause/resume APIs, and deprecated `/api/hub/tasks*` aliases are implemented.
- Hub execution now dispatches `run.completed` or `run.failed` to event schedules.
- Required live-owner test assertions reported one owner at a time and successful transfer. The runner returned a nonzero/interrupt status after pytest printed the passing test; this does not count as a clean test-process exit.

### 3. SSH workspaces — implemented

- `GET /api/ssh/hosts` returns `{hosts: [{alias, hostname, user}]}` from SSH config. `POST /api/ssh/test` takes `{host}` and returns `{ok, os, detail}`; unknown aliases return HTTP 400.
- SSH workspaces use `ssh://<host>/<path>`, reject URI credentials, use configured keys, cache connections for five minutes, retry a command once after disconnect, and detect Windows versus POSIX remotes.
- Remote file, edit, shell, exec, Git, workspace file/tree/rules/search/raw, changes, and checkpoint paths are connected. Windows shell, exec, Git and file search use encoded PowerShell scripts with quoted arguments. Remote checkpoints snapshot nested files under `.atlas-checkpoints`; the checkpoint directory is excluded from its own snapshots. Unsupported computer/browser tools remain local and identify local execution in their result.
- The SSH test group reported 5 passed, covering file read/write/list, command execution, Windows argument handling, retry, invalid URI/credentials and unknown host alias.

### 4. Optional permission modes and workspace trust — implemented

- `run.start.permission_mode` accepts `full_access` (default), `ask_writes`, or `read_only`. Optional absolute `allowed_paths` are validated; the selected mode is persisted on the conversation and returned in conversation listings.
- First-use workspace rules emit `rules.trust_required` with the current run's event sequence and wait for `rules.trust`; trust is stored in `<data>/trusted-workspaces.json`. `GET /api/workspace/trust?root=` reads trust and `DELETE` revokes it.
- Invalid permission/path input and trusted-workspace continuation were exercised in the server test. Separate end-to-end first-use accept/decline coverage remains limited.

### 5. PR and CI — implemented

- `GET /api/git/pr?root=` shapes current PR metadata and checks, returning `{pr: null}` when no PR exists.
- `POST /api/git/pr` checks `gh` authentication, pushes the current branch from the requested workspace (including worktrees), creates the PR, and returns the same shape. Failed-check logs are capped at 64 KiB by `GET /api/git/pr/checks/{check_name}/log?root=`.
- Mocked successful creation and unauthenticated failure tests both passed (2 passed).

### 6. User-configurable hooks — implemented

- Hooks are stored in `<data>/hooks.toml`; APIs are `GET/POST /api/hooks`, `PUT/DELETE /api/hooks/{id}`, and `POST /api/hooks/{id}/test`.
- Supported events are `run.started`, `tool.before`, `tool.after`, `run.completed`, and `run.failed`. Hook input is JSON on stdin; output is capped at 4 KiB; `tool.before` exit code 2 blocks the tool; failures/timeouts are recorded without blocking execution; `hook.ran` contains `hook_id`, `event`, `exit_code`, `duration_ms`, and `output`.
- Hook configuration, nonblocking failure and exit-code-2 blocking tests passed (3 passed).

## Verification record

Commands used from `D:\Atlas\core`; every pytest `--basetemp` was under `%TEMP%`, outside the repository and user data directories:

- `pytest -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-required-suite2" tests --ignore=tests/test_computer_use.py -q` — interrupted by the command runner after 58 passed, 1 skipped; full suite remains incomplete.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-parity-e2e" tests/test_backend_parity_wave3.py -k "fork_and_duplicate or worktree_name or recipe_from or create_pr_" -q` — 6 passed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-ssh-final" tests/test_backend_parity_wave3.py -k "ssh_" -q` — 5 passed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-hooks-final" tests/test_backend_parity_wave3.py -k "hook_store_validates or hook_error_does_not or hook_exit_two" -q` — 3 passed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-modes-final" tests/test_backend_parity_wave3.py -k "workspace_trust or runtime_protocol_is_1_5 or permission_modes" -q` — 3 passed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-event-run" tests/test_backend_parity_wave3.py -k "event_schedule_fires_once" -q` — 1 passed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-scheduler-tests" tests/test_backend_parity_wave3.py -k "hub_schedule_migration or scheduler_lease_has or hub_claim_preempts or event_trigger_args_roundtrip" -q` — pytest printed 4 passed, then the runner returned nonzero; clean process exit not verified.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-live-lease" tests/test_backend_parity_wave3.py -k "two_live_schedulers" -q` — pytest printed 1 passed; runner returned nonzero after the test assertions completed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-fork-fixed" tests/test_server.py -k "fork_truncate_and_missing_message" -q` — 1 passed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-workspace-fixed" tests/test_server.py -k "run_workspace_saved_and_invalid_mode_rejected" -q` — 1 passed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-protocol" tests/test_server.py -k "protocol_version" -q` — 1 passed.
- `.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-durable-only" tests/test_durable.py -q` — 3 passed.
- `pytest -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-w2" tests/test_backend_parity_wave2.py -q` — 22 passed.
- `pytest -p no:cacheprovider --basetemp "%TEMP%\atlas-wave3-batch1" tests/test_agent.py tests/test_agent_browser_acceptance.py tests/test_agent_capabilities.py tests/test_agent_enrichment.py -q` — 54 passed, 1 skipped.
- `.\.venv\Scripts\python.exe -m compileall -q atlas` — passed.
- `ruff check --select F atlas/ssh.py atlas/runtime/hooks.py tests/test_backend_parity_wave3.py` — passed.
- `git diff --check` — passed.

The Hub process-start acceptance test and the complete 596-item suite were interrupted by the runner's time limit. Their successful completion is not claimed. No backend/frontend integration run was performed.

## Interface differences

No taskbook event names, route names, request fields, or response field names were intentionally changed. Protocol advancement to `1.5` and updates to old `1.4` test expectations are intentional.

## Commit and remote

This artifact is included in the implementation commit. The final push and remote HEAD comparison are recorded in the delivery receipt.
