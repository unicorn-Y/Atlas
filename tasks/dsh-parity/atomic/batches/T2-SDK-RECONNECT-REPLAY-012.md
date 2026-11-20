# T2-SDK-RECONNECT-REPLAY-012

- Status: DONE_SCOPED
- Capability atom: SDK process restart on an existing conversation and replay of only the committed attempt into the next provider request.
- Files: `core/tests/test_app_server_sdk_subprocess_attempts.py`; `sdk/python/atlas_sdk/app_server.py` only if the current API cannot reopen a conversation; `core/atlas/tools/app_server.py` only if the production session-start/resume path loses canonical history; this batch record, capability/edge/queue ledgers and progress.
- Dependencies: T2-SDK-CLI-ATTEMPT-REPLAY-011 actual child process rollback/result/SessionDB evidence.
- Acceptance (binary): first real SDK-spawned `atlas app-server` child completes OLD→rollback→NEW and exits; second SDK process opens the exact existing `conversation_id`, submits another prompt, and the actual FakeLLM request history contains NEW but not OLD. Reopen SessionDB after the second process: assistant transcript remains NEW-only for the first answer and keeps the OLD discarded-attempt audit.
- Rollback boundary: temp roots and loopback fake provider only; do not touch installed CLI, user config/data, credentials, or user ports.
- Exact green command from `D:\Atlas\core`: `python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py --tb=short`; output `1 passed, 5 warnings in 12.50s`, exit `0`. The test runs two separate SDK clients and two naturally exiting repository CLI app-server child processes over one private data root.
- First process does OLD→rollback→NEW and persists only NEW as assistant text plus a discarded OLD `model/attempt` row. The second SDK process reopens the same `conversation_id`; FakeLLM receives the follow-up prompt with NEW in the replayed assistant history and no OLD; the final reopened SessionDB has NEW and FOLLOW-UP answers, no OLD transcript text, and retains the discarded attempt audit.
- Fixture construction first failed because the test rebuilt the same private root for process two (`FileExistsError` before the second child started); fixed the fixture to reuse its already-isolated environment. This was not a product-path failure.
