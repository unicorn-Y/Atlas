# T3-SEPARATE-PROCESS-ENQUEUE-RACE-106

## Scope

This batch extends the T3-103 idempotency proof from two SQLite connections in one process to two independent Python child processes opening the same temporary SessionDB.

Files changed:

- `core/tests/test_durable_enqueue_retry.py`
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`
- this report

Dependencies: the transactionally deduplicated SessionDB enqueue receipt and inbox stale-snapshot refresh implemented in T3-103.

## Change

Added a ready/go barrier harness that starts two separate Python interpreters, lets both restore an independent `DurableInbox` over the same temporary SQLite database, and releases both writers together. It exercises matching and conflicting payloads under the same request ID. The parent checks each child’s JSON result, exit code, and the final durable event list. Any child still alive on failure is terminated and waited for only as test-fixture cleanup; cleanup is not treated as a passing exit.

The existing transaction implementation passed both cross-process cases, so this batch changed no production storage code.

## Verification

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py
....                                                                     [100%]
4 passed, 5 warnings in 4.59s
exit code: 0

python -m py_compile tests/test_durable_enqueue_retry.py
exit code: 0

git diff --check -- tests/test_durable_enqueue_retry.py
exit code: 0
```

The two cross-process tests each observed both child interpreters exit naturally with code 0. Matching payloads returned the same event ID with exactly one `created=True`; conflicting payloads produced one success and one `ValueError`. Each case left exactly one `inbox.enqueued` event in the temporary SessionDB.

## Boundary

These were real separate Python processes and SQLite connections, but not two full app-server processes. The tests do not verify competing active workers, per-session FIFO across server instances, provider requests, restart retry-budget consumption, approval/input reconnection, the full subscription contract, or Task 3 completion.
