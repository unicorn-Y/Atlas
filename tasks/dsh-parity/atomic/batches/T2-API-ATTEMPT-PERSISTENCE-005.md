# T2-API-ATTEMPT-PERSISTENCE-005 — actual isolated API WebSocket OLD→NEW

- `batch_id`: `T2-API-ATTEMPT-PERSISTENCE-005`
- `atomic_ids`: `ENG-API-WS-ATTEMPT-ROLLBACK`, `ENG-API-SESSIONDB-ATTEMPT-AUDIT`
- `phase`: P1
- `dependencies`: `T2-ATTEMPT-ROLLBACK-002`, `T2-DURABLE-CLIENT-004`
- `implementation_dependencies`: existing `run_drive` rollback/final-response projection, kernel SessionDB `model/attempt` lifecycle persistence, C1 isolated backend process and FakeLLMServer.
- `verification_dependencies`: isolated uvicorn subprocess, local loopback FakeLLMServer, `/ws/chat`, reopened SessionDB.
- `global_completion_gates`: real provider/model, desktop session and full application session replay remain separate gates.

## Files

- Modify `core/atlas/api/run_drive.py` only for a reproduced API path gap.
- Modify `core/tests/test_c1_websocket_acceptance.py` with a unit-marked process/WebSocket/SessionDB regression and fail-closed provider isolation.
- Update atomic capability, interaction-edge, queue, batch and progress records.

## Binary acceptance

1. The isolated backend is a separate process on an ephemeral loopback port and consumes only a local FakeLLMServer endpoint.
2. `/ws/chat` records an OLD attempt delta, matching rollback, NEW deltas, and a completed event. Final `message.completed` content is `NEW answer`.
3. Reopening the isolated process's SessionDB finds only NEW in canonical assistant messages and a separate discarded `model/attempt` row containing the received OLD prefix and the matching attempt ID.
4. No user data, credentials, 8765 service or live model endpoint is used. Any escaped provider fallback is blocked inside this subprocess.

## Implementation and evidence

- The first process-level run failed before model execution because `_execute_run.emit` referenced `sandbox_type`, a local defined only inside `_handle_run_start`. `_execute_run` now derives it from the passed `RunState.sandbox`; AST confirms the assignment is a direct local at line 3000.
- A pre-hardening diagnostic run then resolved an OpenAI public endpoint and received 401 using the isolated fake fixture key. No user credential was read or used. The subprocess harness now fixes the custom model `base_url` to the local fixture, clears fallback configuration in its private root, and installs a loopback-only fail-closed proxy after removing inherited proxy settings. The final test run used the local FakeLLMServer and passed.
- Exact final command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_retry_rollback_and_reopened_session_db_contain_only_new_answer --tb=short`.
- Output: `1 passed, 5 warnings in 13.49s`, exit code 0. The test launches the isolated uvicorn process, exercises `/ws/chat`, sees OLD→rollback→NEW and `run.completed`, then reopens the private SessionDB and checks canonical NEW plus discarded OLD audit.
- A separate explicit run of the existing `test_websocket_multiturn_keeps_tool_transcript` failed: its forced `read_file` tool call persisted `Unknown tool: read_file`, so the assertion for a `TRANSCRIPT_FIXTURE` tool message failed. That is a separate tool registration/fixture contract gap, not evidence against this rollback test; it is queued for investigation and not hidden by `-m unit` deselection.
- `python -m py_compile` on the touched production and test Python files exited 0. AST confirmed `sandbox_type` is a direct local assignment in `_execute_run`. `git diff --check` exited 0 with only repository line-ending conversion notices.
- Batch status stays PARTIAL: this atomic rollback path is verified locally, but the unrelated read_file transcript path, actual CLI subprocess, provider/model and desktop runtime gates remain open.

## Later narrow recheck — 2026-11-18

- The prior `Unknown tool: read_file` observation is retained as a historical failure. Current checked-in test source separates the multi-turn transcript case (which calls `grep`) from `test_websocket_read_file_is_offered_executed_and_replayed`.
- Exact recheck from `D:\Atlas\core`: `python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_multiturn_keeps_tool_transcript tests/test_c1_websocket_acceptance.py::test_websocket_read_file_is_offered_executed_and_replayed --basetemp C:\Users\25011\AppData\Local\Temp\atlas-tool-transcript-089-repro --tb=short` → `2 passed, 5 warnings in 18.44s`, exit 0.
- The earlier unknown-tool failure was not reproduced by these current source nodes. No production fix is claimed from this recheck, and the broader persistence batch remains PARTIAL for its other gates.
