# T1-KERNEL-TOOL-SEARCH-LOAD-071

Status: `DONE_SCOPED`; generic tier-pruned schemas can again be made callable by an explicit `tool_search` in the same conversation.

## Files and dependency

- Production: `core/atlas/engine/kernel/loop.py`.
- Integration regression: `core/tests/test_terminal_tool_dispatch.py`.
- Dependency: existing `search_tools` session load registry plus the 070 owner-scoped terminal schema/dispatch.

## Root cause and change

The kernel filtered the executable tool catalog by runtime permissions, then tier-pruned it. `tool_search` recorded matching names per conversation and returned a summary, but the next provider request was rebuilt from the same static tier and never re-added those loaded schemas. The terminal tool was therefore discoverable in text yet absent from the provider schema.

After tier pruning, the kernel now restores only names loaded for the current conversation, sourced only from that request's already permission-filtered executable catalog. It does not expose schemas loaded in a different conversation, disabled by runtime permissions, or absent from the current agent's tools.

The integration test first invokes real kernel `tool_search`, checks that a subsequent FakeLLM provider request includes `terminal_open`, then completes the terminal file side effect and the 070 ownership/close assertions. It also checks that another conversation's provider request does not inherit `terminal_open`.

## Red/green evidence

The strengthened assertion first failed against the previous production behavior:

```text
python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_terminal_tool_dispatch.py --basetemp C:\Users\25011\AppData\Local\Temp\atlas-terminal-tools-070-search --tb=short
1 failed, 1 passed, 5 warnings in 11.85s
AssertionError: terminal_open was not offered after the real tool_search dispatch
```

After the loop fix, the focused node passed:

```text
python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_terminal_tool_dispatch.py::test_kernel_dispatches_owner_scoped_terminal_tools_and_hides_them_from_process_api --basetemp C:\Users\25011\AppData\Local\Temp\atlas-terminal-tools-071-green1 --tb=short
1 passed, 5 warnings in 11.06s
```

Final module collection and run:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_terminal_tool_dispatch.py
2 tests collected in 0.81s

python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_terminal_tool_dispatch.py --basetemp C:\Users\25011\AppData\Local\Temp\atlas-terminal-tools-071-final --tb=short
2 passed, 5 warnings in 15.12s
```

Additional checks:

```text
python -m py_compile core/atlas/engine/kernel/loop.py core/atlas/tools/local_execution.py core/atlas/agent/tool_node.py core/atlas/api/tools_router.py core/tests/test_terminal_tool_dispatch.py
exit 0

git diff --check -- core/atlas/engine/kernel/loop.py core/atlas/tools/local_execution.py core/atlas/agent/tool_node.py core/atlas/api/tools_router.py core/tests/test_terminal_tool_dispatch.py
exit 0
```

AST check: the trusted owner call is inside `execute_tools_node` and its dispatch conditional accepts the `local_`/`terminal_` families. A first AST script had an invalid `ast.Elif` class reference, and a second assertion had a wrong expected function line; the corrected check passed. These were check-script mistakes, not production failures.

## Limits

The proof is local FakeLLM + actual Atlas kernel + Windows pywinpty in a temporary workspace. It does not prove real-model usage, Electron visibility, DSH parity, SSH terminal behavior, or POSIX sandboxing. A real `test_local_execution.py` run earlier in this work still had one unrelated failure: `test_shells_executable_cwd_environment_and_nonzero_exit` expected exit code 7 to return `is_error=False`, while production returned `True` (`1 failed, 18 passed`); this batch does not change that contract.
