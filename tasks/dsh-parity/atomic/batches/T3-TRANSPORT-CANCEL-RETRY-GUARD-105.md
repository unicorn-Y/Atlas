# T3-TRANSPORT-CANCEL-RETRY-GUARD-105

## Scope

Dependencies: durable retry recovery classification (`T3-DURABLE-ENQUEUE-RECEIPT-102`) and cross-instance enqueue receipt identity (`T3-CROSS-INSTANCE-ENQUEUE-IDEMPOTENCY-103`).

Files changed:

- `core/atlas/models/router.py`
- `core/tests/test_model_router.py`
- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`
- this report

## Reproducer and change

The SDK subprocess test cancelled a task during its second provider request and correctly observed durable `outcome_unknown/do_not_replay`. With a bounded two-second fake hang, the process later exited naturally but the still-running synchronous transport retried after the peer disconnected. The red run observed three provider requests for the cancelled task.

The managed blocking stream now exposes its abort state to the pooled transport. `open_stream` rechecks that state after a transport exception or retryable HTTP response, immediately before deciding to retry. This keeps existing retries when the stream has not been aborted while preventing an abandoned worker thread from replaying after local cancellation. The SDK process test closes stdin, requires a natural zero exit under a 12-second deadline, and verifies after exit that only the original two requests occurred.

## Verification

Red production-path regression before the retry guard:

```text
python -m pytest -q -p no:cacheprovider tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_cancelled_retry_is_unknown_through_sdk_without_replay
1 failed, 5 warnings in 13.63s
exit code: 1
AssertionError: cancelled attempt triggered a later provider replay; assert 3 == 2
```

Final focused verification, including aborted transport, ordinary retry, real SDK subprocess cancellation/recovery, and restart recovery:

```text
python -m pytest -q -p no:cacheprovider tests/test_model_router.py::test_stream_transport_does_not_retry_after_managed_abort tests/test_model_router.py::test_stream_transport_keeps_retrying_when_not_aborted tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_cancelled_retry_is_unknown_through_sdk_without_replay tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_recovery_classifies_inflight_retry_after_process_restart
4 passed, 5 warnings in 22.28s
exit code: 0
```

Additional checks:

```text
python -m py_compile atlas/models/router.py tests/test_model_router.py tests/test_app_server_sdk_subprocess_attempts.py
exit code: 0

git diff --check -- atlas/models/router.py tests/test_model_router.py tests/test_app_server_sdk_subprocess_attempts.py
exit code: 0
```

## Boundary

This closes only the tested cancellation-to-transport-retry path. It used FakeLLMServer, not a live provider, and does not establish prompt replay, pending approval/input restart recovery, separate-process enqueue races, all subscriptions, packaged desktop behavior, or Task 3 completion. Earlier 12-second timeout attempts used a 30-second Hang fixture and are diagnostic runs, not evidence of a production shutdown defect.
