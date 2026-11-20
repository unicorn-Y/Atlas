# T3-APP-SERVER-DISTINCT-REQUEST-FIFO-112

## Scope

Dependencies: T3-109 same-request dual app-server execution, T3-107 cross-process start claim, and T3-108 cancel/start boundary.

Files changed:

- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- this report
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`

## Red reproducer

Two actual CLI app-server subprocesses attach separate SDK sessions to the same conversation. The first request is held inside a loopback FakeLLM responder gate. A second, distinct request ID is enqueued through the other process. The test verifies it stays queued while the head is running, releases the head, then requires the second request to start and complete without another client action. It also verifies provider order, durable lifecycle sequence and natural exit code 0 for both children.

Before the production fix, the first completed, but the second remained queued. The recorded lifecycle contained first `enqueued/started`, second `enqueued`, first `consumed`, and no second `started`; the provider saw one request.

```text
python -m pytest -q -p no:cacheprovider tests/test_app_server_sdk_subprocess_attempts.py::test_two_app_server_processes_drain_distinct_same_session_requests_in_fifo_order
1 failed, 5 warnings in 13.80s
exit code: 1
```

The first post-fix integration run exposed a harness-only assertion issue: model user content includes the legitimate `<turn_context>` envelope. The test now checks marker order within the actual content rather than requiring the whole content to equal the marker; this assertion correction did not change production code.

## Limits

The test uses the real CLI app-server, SessionDB and SDK over local FakeLLMServer. It covers two distinct next-turn requests in one shared conversation, not approval/input interleaving, terminal recovery, live model, desktop, or all cross-runtime obligations. Production correction is recorded in T3-113.
