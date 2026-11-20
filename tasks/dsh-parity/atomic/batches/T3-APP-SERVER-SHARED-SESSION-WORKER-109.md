# T3-APP-SERVER-SHARED-SESSION-WORKER-109

## Scope

Dependencies: T3-106 separate-process enqueue receipt, T3-107 atomic worker claim, and T3-108 cancel/start serialization.

Files changed:

- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- this report
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`

## Behavior covered

Added a subprocess integration case with two actual `python -m atlas.cli` app-server processes. Both attach SDK sessions to the same conversation and concurrently enqueue the same request ID and prompt. The test requires the same durable receipt, exactly one `inbox.enqueued`, `inbox.started`, and `inbox.consumed` lifecycle, one FakeLLM provider request, session closure, and both child processes to exit naturally with code 0.

The first runs exposed an intermittent SessionDB `state.db-shm` preflight error; this was not counted as a pass or dismissed as test noise. Batch 110 recorded the exception and batch 111 fixed the specific disappearing-sidecar race before this slice was accepted.

## Verification

After batch 111's fix, the focused subprocess test was run five times:

```text
python -m pytest -q -p no:cacheprovider tests/test_app_server_sdk_subprocess_attempts.py -k test_two_app_server_processes_deduplicate_same_session_enqueue_and_worker
RUN_1 EXIT=0: 1 passed, 26 deselected, 5 warnings in 6.65s
RUN_2 EXIT=0: 1 passed, 26 deselected, 5 warnings in 6.65s
RUN_3 EXIT=0: 1 passed, 26 deselected, 5 warnings in 6.60s
RUN_4 EXIT=0: 1 passed, 26 deselected, 5 warnings in 6.65s
RUN_5 EXIT=0: 1 passed, 26 deselected, 5 warnings in 6.68s
```

The full SDK/app-server subprocess file plus the sidecar regression was then collected and run together:

```text
python -m pytest -q -p no:cacheprovider tests/test_app_server_sdk_subprocess_attempts.py tests/test_atlas_state_repair_preflight.py
29 passed, 5 warnings in 177.67s (0:02:57)
exit code: 0
```

The test itself asserts one provider request, the exact three lifecycle events, and natural process exit code 0. Its model is FakeLLMServer, not a live provider.

## Limits

This closes only matching same-request enqueue/worker deduplication between two CLI app-server processes. Different queued requests competing for one conversation, FIFO across server instances, active-run routing, approval/input restart recovery, durable subscriptions and the rest of Task 3 remain open. It is not full Task 3 or superiority evidence.
