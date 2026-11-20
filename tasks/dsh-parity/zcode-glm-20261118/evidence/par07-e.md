# PAR07-E receipt — SDK user-question cancellation closure

Date: 2026-11-19
Worker: E (DSH-PARALLEL-07)
Contract: `tasks/dsh-parity/zcode-glm-20261118/evidence/exec06-user-question-cancel-remoteaccess-20261118.txt` §A/B (A-1, A-3)

## Baseline

- Atlas snapshot commit: `060071ab` ("test(main): tolerate the port field D1 added to ensureBackendRunning"), branch state `wave3`.
- Repo main checkout `D:/Atlas` was read-only for this task. Its in-flight (uncommitted) `core/atlas/tools/app_server.py` (1610 lines), `sdk/python/atlas_sdk/app_server.py` (697 lines) and untracked `core/tests/test_app_server_sdk_subprocess_attempts.py` were read as design reference only; none of those files were touched in main.
- The delivered tree is based on `060071ab`, whose app-server/SDK is the older 727/190-line baseline (no `request_id`, no `appserver.request` audit, no task queue). The closure was implemented against that baseline.
- Baseline affected tests on the unmodified tree (only this task's files stashed, everything else untouched): **29 passed, EXIT=0** (10 app-server ACP + 5 app-server lifecycle + 13 event contract + 1 desktop `test_ask_user_event_waits_for_a_response`).

## Worktree / branch

```
git -C D:/Atlas worktree add -b zcode/par07-sdk-cancel D:/Atlas/.worktrees/zcode-par07-sdk-cancel 060071ab
# exit 0
git -C D:/Atlas/.worktrees/zcode-par07-sdk-cancel rev-parse --abbrev-ref HEAD  # zcode/par07-sdk-cancel
git -C D:/Atlas/.worktrees/zcode-par07-sdk-cancel rev-parse --short HEAD     # 060071ab
```

No commit, push, merge, or main-queue write was performed. The only file written outside the worktree is this receipt (explicit task deliverable).

## Files changed (isolated tree)

- `core/atlas/tools/app_server.py` — server-side state machine + notification + durable audit.
- `sdk/python/atlas_sdk/app_server.py` — client consumption, request-id correlation, defer/respond/cancel helpers.
- `docs/app-server-protocol.md` — documents `user-question.cancelled`, `request_id`, late-answer rejection, durable states.
- `core/tests/test_app_server_user_question_cancel.py` — new real-channel tests (6).

No desktop files, event-name files, frontend files, user data, credentials, or other authors' in-flight files were modified.

## Wire contract chosen

- Method name: **`user-question.cancelled`** (exact DSH SDK name).
- Params: **`{"requestId": <original request_id>, "sessionId": <session_id>}`** — exact DSH camelCase payload, no extra fields.
- `input/request` now additively includes `request_id` (same string as `requestId`) beside the existing `session_id` / `call_id` / `prompt` / `options`.
- Why: the contract's A-1 requires the DSH name/payload with the original identity. Atlas' app-server uses snake_case for request payloads, but this is a server→client notification (not a request), and old clients ignore unknown notification methods (the Python SDK did before this patch). Answering by legacy `call_id` still works; `request_id` is preferred when present.
- Durable audit rows are session events `appserver.request` with exactly `{request_id, session_id, kind, state, instance_id}` and states `pending` → `resolved` | `invalidated` (matches the contract's field/state vocabulary; no new schema fields).

## Deterministic behavior

- Single authority: `pending_input_requests[request_id]` claims `pending` → `resolving`/`invalidating` synchronously before any await, so cancellation and answer cannot both win.
- Cancel paths that invalidate: `session/cancel` (request or notification), `session/close`, explicit `shutdown`, EOF/process drain. Each pending request emits at most one `user-question.cancelled` frame.
- Ordering: the cancellation frame is queued before the durable write yield, therefore before the run's terminal `session/prompt` response.
- Tool semantics: cancellation raises `asyncio.CancelledError` from `ask_user`; the tool never receives `""` as an answer. `run_prompt` converts it to the normal cancelled terminal result (`status: "cancelled"`, or ACP `stopReason: "cancelled"`), so run/task terminal frames are preserved (A-3).
- Accepted answer wins a race: the response handler durably records `resolved` before setting the future; `_wait_with_cancel` gives a completed future precedence over a simultaneous cancel. A later cancel is a no-op (no cancellation frame, no `invalidated` row). A duplicate/late answer is rejected `-32602` and never applied.
- Late answers after cancellation are rejected `-32602` ("input request is no longer pending") both by `request_id` and by legacy `call_id`; an unknown `request_id` never falls back to `call_id`.
- Restart/reconnect: `session/start` with an existing `conversation_id` scans `appserver.request` history (bounded paging, up to 50k rows; bails without guessing if truncated) and appends `invalidated` for `pending` rows whose `instance_id` belongs to a previous process. A late answer in the fresh process is rejected because its in-memory table is empty.
- If the durable `pending` write fails, no `input/request` is announced and no spurious cancellation is sent (`announced` guard). If the durable `resolved` write fails, the answer is rejected `-32603` and the request stays pending. If the durable `invalidated` write fails during cancellation, the wire frame is still sent (wire is authoritative; DSH contains notification failures similarly).

## Exact commands and results (all run in the isolated worktree)

Baseline (this task's four files stashed, existing tests only):

```
cd D:/Atlas/.worktrees/zcode-par07-sdk-cancel/core
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider -o addopts= --tb=short \
  --basetemp=D:/Atlas/.worktrees/zcode-par07-sdk-cancel/.tmp/pytest-par07-base \
  tests/test_app_server_acp.py tests/test_app_server_sdk_lifecycle.py tests/test_event_contract.py \
  tests/test_server.py::TestBackendParityWave1::test_ask_user_event_waits_for_a_response
# 29 passed, 5 warnings; EXIT=0
```

New tests only:

```
cd D:/Atlas/.worktrees/zcode-par07-sdk-cancel/core
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider -o addopts= --tb=short \
  --basetemp=D:/Atlas/.worktrees/zcode-par07-sdk-cancel/.tmp/pytest-par07-newonly \
  tests/test_app_server_user_question_cancel.py
# 6 passed, 5 warnings in 11.12s; EXIT=0
```

Post-change affected suite (new + all existing app-server/event + desktop parity reference):

```
cd D:/Atlas/.worktrees/zcode-par07-sdk-cancel/core
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider -o addopts= --tb=short \
  --basetemp=D:/Atlas/.worktrees/zcode-par07-sdk-cancel/.tmp/pytest-par07-final \
  tests/test_app_server_user_question_cancel.py tests/test_app_server_acp.py \
  tests/test_app_server_sdk_lifecycle.py tests/test_event_contract.py \
  tests/test_server.py::TestBackendParityWave1::test_ask_user_event_waits_for_a_response
# 35 passed, 5 warnings in 14.92s; EXIT=0
```

Related input-path suites:

```
cd D:/Atlas/.worktrees/zcode-par07-sdk-cancel/core
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider -o addopts= --tb=short \
  --basetemp=D:/Atlas/.worktrees/zcode-par07-sdk-cancel/.tmp/pytest-par07-related \
  tests/test_backend_parity_wave4_z1.py tests/test_c4_hooks.py tests/test_x2_pending.py
# 54 passed, 5 warnings in 8.31s; EXIT=0
```

Lint (changed Python files):

```
cd D:/Atlas/.worktrees/zcode-par07-sdk-cancel/core
python -m ruff check --output-format concise atlas/tools/app_server.py
# 38 errors — identical count to baseline `git show 060071ab:core/atlas/tools/app_server.py` (38), all pre-existing E501/I001/BLE001
python -m ruff check --output-format concise tests/test_app_server_user_question_cancel.py
# All checks passed!; EXIT=0
python -m ruff check --output-format concise ../sdk/python/atlas_sdk/app_server.py
# 12 errors vs baseline 13 (one fewer; no new diagnostics)
```

Test inventory (6 new, all `@pytest.mark.unit`):

1. `test_ask_cancel_notifies_once_before_terminal_and_rejects_late_answer` — real `serve_stdio` JSON-RPC loop; session/cancel with pending `ask_user`; asserts exactly one exact-payload frame, ordering before terminal, `status=cancelled`, tool got no `""`, late `request_id` and legacy `call_id` answers both `-32602`, durable `[pending, invalidated]`.
2. `test_accepted_answer_wins_late_cancel_and_is_not_invalidated` — answer accepted, duplicate answer rejected, later cancel is a no-op, zero cancellation frames, durable `[pending, resolved]`.
3. `test_shutdown_drain_cancels_pending_question_once` — explicit `shutdown` with a pending question emits one frame, audited `invalidated`, prompt terminal still `cancelled`.
4. `test_reconnect_invalidates_pending_request_from_previous_process` — seeded old `pending` row with old `instance_id`; reconnect `session/start` appends `invalidated` preserving the original instance id; late answer rejected.
5. `test_legacy_call_id_only_answer_still_resolves` — pre-`request_id` clients remain functional.
6. `test_real_sdk_subprocess_cancel_notification_and_late_answer` — real `atlas app-server` subprocess + FakeLLMServer `ask_user`; SDK receives the exact notification once, prompt ends `cancelled`, `respond_input(request_id, ...)` raises `AppServerError(-32602)`, durable `[pending, invalidated]`, one model round only; then a real process restart with the same conversation still rejects the old request and resumes.

## Product-entry boundary

- In scope and implemented: Atlas app-server (`atlas app-server`) and its Python SDK client only. `user-question.cancelled` is a JSON-RPC notification, not a desktop event, so `event_names.py` / `runtimeEvents.ts` / `runtime.ts` are intentionally untouched and the three-source rule does not apply.
- Desktop is out of scope and untouched: `core/atlas/api/run_drive.py`, `runtime_ws_router.py`, renderer timeline/store, and `DESKTOP_EVENTS`.

## Desktop-path remaining gap (separate, out of scope)

- Desktop/WebSocket still has no question-level terminal frame: `run_drive.input_callback` waits on `run.input_futures` and only observes `run.cancel_event`; `input.response` for an unknown/expired `event_id` is silently skipped (no error receipt); the renderer question card is not closed and its optimistic answer is not rolled back. Contract A-2 (`input.cancelled` + three-source sync + frontend projection) remains open.
- Desktop `run.cancelled` stays the only desktop cancellation terminal, per A-3; it was not suppressed or changed.

## Remaining risks

1. Desktop A-2 remains unimplemented (explicitly out of scope), so desktop users still cannot see a per-question cancellation state.
2. The restart scan assumes one live app-server process per conversation. If two processes attach to the same `conversation_id` concurrently, the newer `session/start` will mark the older process's still-live pending row `invalidated` (no liveness proof exists in baseline). In-memory state in the older process can then disagree with the durable audit.
3. The restart scan is bounded at 50k `appserver.request`-bearing rows per conversation; beyond that it deliberately leaves rows pending instead of guessing from truncated history.
4. Legacy `call_id` answers share one global map. Two concurrent sessions using the same `call_id` are ambiguous for legacy-only clients; the new `request_id` path is unambiguous. This is a pre-existing baseline limitation, unchanged.
5. Durable audit failures: an `invalidated` write failure still emits the wire frame (best effort, as in DSH); a `resolved` write failure rejects the answer with `-32603` and leaves the request pending for retry.
6. This patch targets `060071ab`. Main's in-flight `app_server.py` already has `request_id`, `pending_request_meta`, `appserver.request`, and task-cancel machinery; integrating this closure there should reuse that state machine rather than merge the baseline block text. The notification name/payload and `invalidated` state vocabulary are aligned so the port is mechanical, but it was not performed against the in-flight file.
7. No TypeScript SDK exists in this baseline; only the Python SDK consumer was updated.