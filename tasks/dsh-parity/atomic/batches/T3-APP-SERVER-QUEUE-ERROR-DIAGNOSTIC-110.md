# T3-APP-SERVER-QUEUE-ERROR-DIAGNOSTIC-110

## Scope

Dependency: T3-109's two-app-server same-conversation integration test.

Files changed:

- `core/atlas/tools/app_server.py`
- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- this report
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`

## Investigation

Added server-side exception logging for a failed durable queued-state write, while keeping the JSON-RPC response generic. The subprocess test captures bounded, sanitized event/status and stderr diagnostics if the concurrent enqueue fails; it does not print prompt text or credential/config contents.

Five unmodified production attempts showed an intermittent failure: runs 1 and 3 exited 1; runs 2, 4 and 5 passed. The failed responses were `queued task state could not be durably recorded`. The safe traceback located the error at `SessionDB.__init__ -> _open_writer -> preflight_db_writability`; `sqlite3.OperationalError` claimed `state.db-shm` was read-only and appended that the file no longer existed and likely had been released concurrently. This batch identifies the failing boundary but does not claim to fix it; the production correction and deterministic regression are in T3-111.

## Verification

```text
python -m pytest -q -p no:cacheprovider tests/test_app_server_sdk_subprocess_attempts.py -k test_two_app_server_processes_deduplicate_same_session_enqueue_and_worker
RUN_1 EXIT=1: queued task state could not be durably recorded; traceback ends in preflight_db_writability; state.db-shm had disappeared
RUN_2 EXIT=0: 1 passed, 26 deselected, 5 warnings in 6.88s
RUN_3 EXIT=1: same sqlite3.OperationalError at preflight_db_writability for a vanished state.db-shm
RUN_4 EXIT=0: 1 passed, 26 deselected, 5 warnings in 6.75s
RUN_5 EXIT=0: 1 passed, 26 deselected, 5 warnings in 6.69s
```

The failed command returned exit 1; the three passing commands returned exit 0. Subsequent deterministic test and repeated process evidence is in T3-111.

## Limits

This is root-cause localization only. It does not establish all SQLite sidecar/ACL behavior or all app-server concurrency semantics. No credentials or user configuration were read or logged.
