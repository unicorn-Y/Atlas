# T1-TERMINAL-OWNER-TOOLS-070

Status: `DONE_SCOPED` for the local Windows model-facing terminal tool slice. This is not full DSH terminal parity.

## Production surface

- `core/atlas/tools/local_execution.py` provides bounded `terminal_open/send/read/signal/close/list` operations over the existing local PTY runtime. Each session is bound to a trusted owner supplied by dispatch context, uses an opaque session id, and is excluded from generic process list/read/kill/stdin routes.
- `core/atlas/agent/tool_node.py` derives the owner id from the trusted conversation/runtime context, rejects terminal use in plan/sandbox modes, and dispatches through the existing local runtime.
- `core/atlas/api/tools_router.py` hides terminal PTYs from generic `/api/processes` operations.
- `core/tests/test_terminal_tool_dispatch.py` exercises the actual AtlasKernel/FakeLLM loop, an actual Windows pywinpty process, a file side effect, cross-conversation denial, generic process API isolation, explicit close, and runtime shutdown cleanup.

## Evidence

Exact collected nodes from `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_terminal_tool_dispatch.py
tests/test_terminal_tool_dispatch.py::test_kernel_dispatches_owner_scoped_terminal_tools_and_hides_them_from_process_api
tests/test_terminal_tool_dispatch.py::test_local_execution_shutdown_reaps_unclosed_terminal_session
2 tests collected in 0.81s
```

Exact final focused run from `D:\Atlas\core`:

```text
python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_terminal_tool_dispatch.py --basetemp C:\Users\25011\AppData\Local\Temp\atlas-terminal-tools-071-final --tb=short
2 passed, 5 warnings in 15.12s
```

The first test confirms the unique marker was written to the private temporary workspace file and read from the terminal output. It also verifies another conversation receives a denial, generic process endpoints hide/404 the PTY, and the closed process reaches a non-running state. The second test closes the runtime with an open terminal and awaits process completion.

Additional exact checks:

```text
python -m py_compile core/atlas/engine/kernel/loop.py core/atlas/tools/local_execution.py core/atlas/agent/tool_node.py core/atlas/api/tools_router.py core/tests/test_terminal_tool_dispatch.py
exit 0

git diff --check -- core/atlas/engine/kernel/loop.py core/atlas/tools/local_execution.py core/atlas/agent/tool_node.py core/atlas/api/tools_router.py core/tests/test_terminal_tool_dispatch.py
exit 0
```

The tool-node AST check found the trusted `terminal_owner_id` call at line 1891 inside `execute_tools_node` (line 182) and confirmed its `local_`/`terminal_` dispatch branch. No DSH test, real model, Electron UI, SSH terminal, or POSIX confinement test was run. Existing focused `test_local_execution.py` had one separate expectation mismatch (`local_exec` exit 7 expected `is_error=False` but implementation returned true); 18 other tests passed. That mismatch is not claimed fixed by this batch.

## Remaining terminal obligations

DSH terminal UI/bundle/component lifecycle, job history, output/event protocol, workspace/SSH variants, packaged desktop behavior, full parity and superiority remain open. Windows pywinpty evidence does not prove Linux/macOS PTY or sandbox parity.
