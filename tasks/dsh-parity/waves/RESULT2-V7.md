# Wave 2 result: E14 and E18 sandbox evidence

Date: 2026-11-14
Branch: `zcode/dsh2-V7`
Rows: E14, E18
Live backend port: 8837

## Outcomes

- **E14 — PARTIAL.** The existing Docker executor handles per-call `read-only` using a disposable container with a read-only workspace bind mount and `workspace-write` in the run container. Both results report the requested level and `sandbox_enforced: true`; `danger-full-access` is rejected with enforcement false. The focused tests verify the invocation shape and reporting. Docker CLI is installed, but `docker version --format json` reports `Server: null`, so no container actually ran. Windows host execution has no generic per-call OS sandbox executor; record this host portion as a HARD gap.
- **E18 — PARTIAL.** A real `deepseek-v4.1-flash` model turn requested `local_exec` with `sandbox_permissions: read-only` and a non-empty justification. Atlas emitted `approval.required` for `local_exec`; the client returned `allow_once`. Because this run had no executor capable of enforcing the requested host isolation, the call failed closed without executing the command. The run then completed. This observes the model-to-approval path, but not successful host isolation.

## Focused tests

Command (from `core`):

```text
python -m pytest -q -p no:cacheprovider -m unit tests/test_dsh_w7_sandbox.py tests/test_kernel_sandbox_escalation.py tests/test_permission_policy_batch_c.py
```

Output:

```text
31 passed, 5 warnings in 25.83s
```

The warnings are existing FastAPI/Pydantic deprecations.

## Real model evidence

The backend was started from this worktree with `http_proxy=http://127.0.0.1:7897`, `https_proxy=http://127.0.0.1:7897`, `ATLAS_API_BASE=https://d1api.xin/v1`, and port `8837`. The key was resolved through the existing Windows credential store; no key was put in environment variables. A temporary local model definition selected `deepseek-v4.1-flash` through the DeepSeek route and was removed after the run.

Prompt requested exactly one `local_exec` call with `echo E18_APPROVAL_PROBE`, mode `read-only`, and justification `Verify one-call sandbox escalation approval`. Observed output:

```text
[event] approval.required tool=local_exec id=call_00_UMCyhmHIk3IkghdW4xFa3757
[approval_input] {"executable": "echo", "args": ["E18_APPROVAL_PROBE"], "sandbox_permissions": "read-only", "justification": "Verify one-call sandbox escalation approval"}
[event] approval.responded
[backend log] {"tool_call_id": "call_00_UMCyhmHIk3IkghdW4xFa3757", "name": "local_exec", "decision": "sandbox_escalation_unavailable", "approval": "allowed-once", "reason": "The per-call sandbox request was approved, but no executor can enforce that mode; the tool was not run."}
[terminal] run.completed ... "model": "deepseek-v4.1-flash" ...
```

The evidence is in `data/logs/runs/2026-11-13/4889b884-84bb-4cd3-85e5-f0a507b02c8d.jsonl`. The backend log records `allowed-once` followed by `sandbox_escalation_unavailable` and explicitly says the tool was not run. A prior prompt selected `local_process` and therefore did not exercise the escalation; it is not counted as approval evidence.

## Files changed

- `docs/parity/DSH-GAP-LEDGER.md` — updated E14/E18 evidence and statuses.
- `tasks/dsh-parity/COVERAGE.md` — linked current row statuses to this result.
- `tasks/dsh-parity/waves/RESULT2-V7.md` — this record.

No production sandbox code changed: the Wave 2 plan calls for Docker-path evidence and honest HARD reporting where the Windows host executor is absent. The temporary local config model entry was removed after the live run.
