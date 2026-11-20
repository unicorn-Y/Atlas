# T1-SSH-STALE-OBSERVATION-073

Status: `DONE_SCOPED` for cross-run stale remote content detection at the real API consumer. SFTP atomic compare-and-swap remains unsupported/open.

## Scope

- Extended `core/tests/test_c1_websocket_acceptance.py::test_websocket_ssh_read_file_uses_authority_and_replays_tool_result`.
- The test uses the isolated backend process, local FakeLLM provider, and test-only AsyncSSH listener. It does not use user credentials, live model services, port 8765, or user data.
- No production code changed. Existing `SSHWorkspaceManager.local_edit` revalidates the observed remote digest before writing; a new API interaction test now proves the public production path preserves that behavior across runs.

## Scenario and binary result

1. The first `/ws/chat` run calls `read_file` and SessionDB replay is checked.
2. The test externally changes the remote fixture before a later run in the same conversation.
3. `local_edit` returns `STALE_FILE`; the error does not contain the private fixture body and the target still exactly equals the external version.
4. A new `read_file` refreshes the observation; a subsequent edit succeeds and the target contains the expected updated bytes.

Exact collection from `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_ssh_read_file_uses_authority_and_replays_tool_result
1 test collected in 0.76s
```

Exact run from `D:\Atlas\core`:

```text
python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_ssh_read_file_uses_authority_and_replays_tool_result --basetemp C:\Users\25011\AppData\Local\Temp\atlas-ssh-stale-read-073-red --tb=short
1 passed, 5 warnings in 20.67s
```

`python -m py_compile core/tests/test_c1_websocket_acceptance.py` exited 0 and scoped `git diff --check` exited 0. The node is explicitly marked `pytest.mark.unit`.

## Limits

The evidence shows stale bytes are rejected before mutation after an intervening run. It does not prove SFTP atomic CAS between the final verification read and write, authority changes during a write, persistence through manager restart, or full DSH `fs-observation-policy` equivalence. No proactive session observation purge was added because current behavior revalidates remote bytes and the existing multi-run read/edit contract is intentional; changing that would require separate pinned-source evidence.
