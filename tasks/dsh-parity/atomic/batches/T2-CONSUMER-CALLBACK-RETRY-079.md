# T2-CONSUMER-CALLBACK-RETRY-079

Status: DONE_SCOPED

## Files and dependencies

- `core/atlas/engine/kernel/model_call.py`
- `core/tests/test_retry_attempt_isolation.py`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- Dependency: existing `complete_stream` attempt lifecycle and retry/fallback isolation.

## Binary acceptance

When the downstream `on_text` consumer raises `TimeoutError` after receiving partial text:

1. The provider is requested once; neither retry nor fallback is started for a consumer failure.
2. The partial attempt is recorded as `consumer_callback`, is discarded, and is not returned as a successful result.
3. Cancellation continues through the existing `CancelledError` behavior; provider disconnect→NEW success still returns NEW only.

## Red evidence

The exact regression command before the production fix was:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_attempt_isolation.py::test_consumer_timeout_does_not_retry_provider_or_commit_partial_text --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-consumer-timeout-079-red3
```

Actual result: `1 failed, 5 warnings in 3.01s`, exit 1. The callback timeout was classified as provider retryable; the primary stream ran and then the configured fallback stream ran (`streams == 2`, expected 1).

## Production change

Consumer callbacks for text, lifecycle events and attempt results now convert ordinary callback exceptions to non-retryable `ModelCallError(category="consumer_callback")`. The candidate loop stops on this category, so it cannot start another provider/fallback request after a consumer has rejected the stream. `CancelledError` is re-raised unchanged. No retry budget, provider error classifier, tool execution, or normal max-output continuation behavior was changed.

## Final verification

Exact command from `D:\Atlas\core`:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_attempt_isolation.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-consumer-timeout-079-final
```

Actual output: `3 passed, 5 warnings in 2.34s`, exit 0. The five warnings are existing FastAPI/Pydantic deprecations.

```text
python -m py_compile atlas/engine/kernel/model_call.py
```

Exit 0. `git diff --check -- core/atlas/engine/kernel/model_call.py core/tests/test_retry_attempt_isolation.py` also exited 0; Git emitted its existing LF-to-CRLF normalization notice.

Ledger schema/reference regression:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-consumer-ledger-079
```

Actual output: `38 passed, 5 warnings in 12.73s`, exit 0.

## Evidence limits

This closes one deterministic local `complete_stream` consumer-callback behavior using an isolated provider fixture. It is not live-model, visible Electron, packaged desktop, DSH parity, or superiority evidence. Broader Task 2 and all Task 1 source obligations remain open.
