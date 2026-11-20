# T2-WEBSOCKET-CANCEL-049 — preserve attempt rollback on server WebSocket cancellation

## Scope and dependencies

- Files changed: `core/atlas/api/runtime_ws_router.py`, `core/atlas/api/run_drive.py`, `core/tests/test_c1_websocket_acceptance.py`, this record, progress and atomic ledgers.
- Dependencies: batches 045–048 and the isolated backend fixture in `test_c1_websocket_acceptance.py`.
- Binary acceptance: an actual isolated uvicorn process on an OS-selected loopback port receives `run.cancel` after the client has received an OLD `message.delta`; it must emit the matching `message.rollback` before `run.cancelled`, make one provider request, persist discarded/cancelled OLD audit, and leave no OLD assistant message in reopened SessionDB.

## Root cause and fix

- First live attempt proved the server received and discarded OLD (`partial_text=OLD`, `status=discarded`, `category=cancelled`) but emitted no `message.rollback` to its WebSocket client.
- Removing `run.task.cancel()` after setting `cancel_event` was not sufficient; a second real run reproduced the same missing event. This result is retained as diagnostic evidence, not a passing fix.
- The confirmed drop was `run_drive._execute_run`: its per-event cancellation gate returned before mapping any queued event, including `message.rollback`. The gate now forwards that rollback, then processes cancellation on the subsequent event.
- `runtime_ws_router` now relies on the run's cancellation event pump rather than cancelling its outer task immediately. The run task is still awaited, and trust waiters are still explicitly resolved.

## Verification

Command from `D:\Atlas\core`:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_cancel_discards_consumed_partial_attempt_and_persists_only_audit tests/test_c1_websocket_acceptance.py::test_websocket_steering_queue_and_stop --tb=short
```

Actual summary:

```text
..                                                                       [100%]
2 passed, 5 warnings in 16.84s
```

The new node asserts OLD arrives on the real WebSocket before cancellation; same-attempt rollback with category `cancelled` follows; terminal event is `run.cancelled`; one loopback model request occurs; reopened private SessionDB has the discarded OLD audit but no OLD assistant text. The existing steering and early-stop node also passed after changing cancellation scheduling.

## Limits

This is a real isolated Python backend/WebSocket process with a local scripted provider. The existing fixture forcibly terminates its uvicorn process during fixture teardown, so this batch does not claim natural backend process shutdown. The event path is not a launched Electron desktop and uses no real model. Remaining Task 1 semantics, packaged Electron runtime, other cancellation races, wait/approval/timeout/tool-error combinations, and superiority remain open.
