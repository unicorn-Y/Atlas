# T2-APPSERVER-RETRY-APPROVAL-057 — OLD rollback while retry waits for approval

Status: DONE_SCOPED

## Files and dependencies

- `core/tests/test_app_server_sdk_subprocess_attempts.py`: actual Atlas CLI app-server subprocess driven through the Python SDK and the local loopback `FakeLLMServer`; the module is marked `pytest.mark.unit`.
- This batch report, `BEYOND-DSH-PROGRESS.md`, and the atomic capability, interaction-edge, and batch-queue ledgers.
- Dependencies: existing attempt rollback persistence, durable app-server pending approval requests, SDK `enqueue` / `pending_requests` / `respond_approval` / `wait`, and SessionDB audit/transcript APIs.
- No production change was required for this interaction.

## Binary acceptance

1. A real app-server child receives an OLD partial response that disconnects, then retries into `request_permissions`; its persisted pending approval contains only the NEW request arguments.
2. The second provider request excludes OLD. After approval, the durable task completes; SessionDB keeps OLD only in the discarded attempt audit and excludes it from the canonical transcript.
3. The child exits naturally with code 0.

## Verification

Collection was checked explicitly: the exact node reported `1 test collected`.

Exact green command from `D:\Atlas\core`:

```text
python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_rollback_stays_private_while_retry_waits_for_approval --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-approval-oldnew-057-verified --tb=short
```

Actual output: `1 passed, 5 warnings in 11.05s`, exit 0. The warning set is the existing FastAPI `on_event` and Pydantic class-config deprecations. The real repository CLI child returned 0 after SDK shutdown. The loopback fixture saw three model requests: OLD disconnect, retry tool request, and completion after approval. The pending durable approval carried the exact `request_permissions` arguments including `scope: "this request"`; the retry request did not contain OLD; the persisted transcript contained `APPROVAL_RETRY_COMPLETED` but not OLD; the discarded attempt audit contained exactly the streamed prefix `OLD attempt `; the approval audit transitioned `pending` then `resolved`.

Three earlier executions of this new node failed due to test-construction assertions, not production behavior: the expected approval omitted the protocol's fixed `scope`, the test expected a tool-call response to appear in the request that elicited it, and the audit assertion expected the entire source string although the fixture sent only 12 characters. The final node preserves the intended production assertions and passes.

## Limits

This is local fixture-provider evidence through the real SDK and app-server subprocess, not real-model or Electron-visible evidence. Other wait/timeout/tool-error interactions, the complete source-semantic ledger, and superiority remain open. Overall Task 2 and the full plan are not complete.
