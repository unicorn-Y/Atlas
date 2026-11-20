# T2-API-ATTEMPT-PERSISTENCE-003

Status: `DONE_SCOPED` for canonical conversation-message replay through the production API after the direct SessionDB reader closes. Task 2 remains OPEN.

## Scope

- Modified only `core/tests/test_c1_websocket_acceptance.py`.
- Reused the existing isolated Uvicorn subprocess, loopback FakeLLM, real `/ws/chat`, SessionDB and `GET /api/conversations/{id}/messages` route.
- The existing API test already verified OLD deltas before `message.rollback`, NEW deltas after it, `message.completed=NEW answer`, canonical SessionDB transcript without OLD, and a discarded `model/attempt` audit row with the OLD prefix.
- Added a public-history read after the direct SessionDB context closes. The route response must contain only NEW assistant text and no OLD attempt text.
- No production edit was needed: the public history route reads the canonical SessionDB transcript. This is test evidence, not a new production fix.

## Exact collection and result

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_retry_rollback_and_reopened_session_db_contain_only_new_answer
1 test collected in 0.80s

python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_retry_rollback_and_reopened_session_db_contain_only_new_answer --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-api-replay-003-redgreen --tb=short
1 passed, 5 warnings in 14.55s
```

The live-model lane was not run. This is an isolated FakeLLM/API/SessionDB result and does not prove real provider behavior, frontend reload rendering, or Task 2 completion.
