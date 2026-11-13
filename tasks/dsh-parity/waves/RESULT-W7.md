# W7 result: sandbox and per-call escalation

Date: 2026-11-14
Branch: `zcode/dsh-w7`
Rows: E14, E18
Real-model port: 8827

## Row outcomes

- **E14 — PARTIAL.** The current branch already has per-call Docker behavior in `core/atlas/sandbox.py`: `read-only` runs in a disposable container with a read-only workspace bind mount; `workspace-write` runs in the run container; each result reports `sandbox_permissions` and `sandbox_enforced`; `danger-full-access` is rejected with `sandbox_enforced: false`. New W7 tests cover these command boundaries and reporting. The Windows host executor still has no general per-call OS isolation implementation. Docker CLI was present, but Docker Engine was unavailable (`Server: null`, Docker Desktop Linux pipe missing), so Docker execution itself was not exercised on this machine.
- **E18 — PARTIAL.** The current branch already validates `sandbox_permissions` and non-empty `justification`, sends one approval request marked `_approval_no_always`, and routes the accepted mode only to the current Docker call. An unavailable executor fails closed. The focused unit tests pass, but a real model call did not reach tool/approval execution; live end-to-end UI approval and tool dispatch remain unobserved.

## Files changed

- `core/tests/test_dsh_w7_sandbox.py` — added unit coverage for one-call approval metadata, Docker read-only/workspace-write invocation shape, result reporting, and fail-closed `danger-full-access`.
- `docs/parity/DSH-GAP-LEDGER.md` — updated E14 and E18 status/evidence to PARTIAL.
- `tasks/dsh-parity/waves/RESULT-W7.md` — this batch record.

The enforcement implementation was already present at the W7 starting HEAD (introduced by commit `8ebf6316`); this batch adds missing focused coverage and records the verified limits rather than claiming a new host sandbox implementation.

## Focused tests

Command (from `core`):

```text
python -m pytest -q -p no:cacheprovider -m unit tests/test_dsh_w7_sandbox.py tests/test_kernel_sandbox_escalation.py
```

Final output:

```text
......                                                                   [100%]
============================== warnings summary ==============================
... 5 FastAPI/Pydantic deprecation warnings ...
6 passed, 5 warnings
```

The first run had one Windows path-format assertion failure in the new test; the assertion was changed to validate the stable Docker mount options. The final rerun above passed.

## Real-process/model attempt on 8827

Started the backend from this worktree with:

```text
python -m uvicorn atlas.server:app --port 8827
```

The server started and accepted the live WebSocket. Docker status was:

```text
Client Version: 29.6.2 (Windows, amd64)
Server: null
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
```

Attempted the targeted escalation prompt through:

```text
python scripts/dsh_live_ws_check.py 8827 "Use local_shell to run `echo W7_ESCALATION_PROBE` exactly once. For that tool call set sandbox_permissions to read-only and justification to Verify a one-call sandbox escalation request. Do not run any other tool. Then report the tool result in one sentence."
```

Observed output:

```text
[event] run.started
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' ..."}
[reply] ''
[result] terminal=run.failed chars=0
```

Backend logs show model candidates failed before a response (TLS EOF); the worktree-created config selected `https://api.monkeyapi.net`, rather than the runner's stated `https://d1api.xin/v1`. The subsequent kernel `int(None)` failure is outside W7 ownership. Therefore no live model output, approval event, or tool execution is claimed. The backend process was stopped after the attempt.
