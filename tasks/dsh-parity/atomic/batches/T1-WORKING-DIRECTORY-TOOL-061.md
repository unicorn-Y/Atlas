# T1-WORKING-DIRECTORY-TOOL-061

Status: PARTIAL (the tool/runtime atom is verified; the DSH capability family remains open)

## Scope and DSH source contract

Pinned plan: `docs/glm-hammer/plans/2026-11-17-atlas-dsh-atomic-parity-and-superiority.md`  
Pinned SHA256: `1999ad5e478f041fb1cb8ba74c9cbd14a29da41b488e5b179093052d662eae4e`  
Working tree baseline: branch `wave3`, HEAD `060071ab2ecf86d41cab90e98160183ce126bc69`.

Read the pinned DSH source `packages/session/tool-working-directory/src/index.ts` and its companion `packages/session/working-directory/src/index.ts`. The tool accepts optional `cd`; omission reads/ensures current directory, relative paths resolve from current directory, and success returns `{cwd}`. DSH commits per-session state and says already-running shells/processes keep their own cwd. `ensure` restores the original session directory if the current path vanished. Atlas keeps the existing security boundary that `workspace` is the trusted authority root, so local `cd` is constrained to an existing directory at or beneath it.

Atlas now exposes `working_directory` on local-execution agents, approves a `cd` through the existing tool approval gate, routes updates through a closure bound to the current app-server run, persists conversation metadata and a SessionDB change event, updates current-run execution state, and projects the current cwd into the next turn's volatile `<turn_context>` user-message surface. The kernel copies runtime objects per tool dispatch, so it now copies the successful tool result back to the shared run runtime before the next tool call.

Files in this atom: `core/atlas/agent/tool_catalog.py`, `core/atlas/agent/__init__.py`, `core/atlas/agent/run_phases.py`, `core/atlas/agent/tool_node.py`, `core/atlas/engine/kernel/loop.py`, `core/atlas/tools/app_server.py`, `core/tests/test_app_server_sdk_subprocess_attempts.py`, and `core/tests/test_c1_local_workspace_cwd.py`. These files also contain pre-existing and earlier atom changes; they were preserved.

## Red/green findings

- A first app-server attempt showed the tool approval and local-exec approval are separate existing interactions; the test now validates each tool name and allows both. Another assertion was corrected to inspect JSON-escaped Windows paths in the actual provider payload.
- The first runtime callback owner check compared `asyncio.current_task()` to the session worker. `ToolScheduler` executes tool dispatch in a child task, so that check rejected the run's own callback. Binding authorization to the captured active cancel-event identity fixed the ownership mismatch without taking an owner ID from model arguments.
- After persistence succeeded, the next same-run process still used the old directory because `AtlasKernel._dispatch` passes a shallow runtime copy to each tool. Updating the shared run runtime from the successful `{cwd}` tool result fixed the propagation.
- Early red commands and their actual failure classes remain in this session output; they are not counted as passing evidence. The final acceptance below is the stable cutoff.

## Verification evidence

- Exact collection from `D:\Atlas\core`:

  ```text
  python -m pytest --collect-only -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_is_scoped_and_persisted tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_reaches_real_local_exec tests/test_c1_local_workspace_cwd.py::test_direct_local_exec_defaults_to_session_working_directory tests/test_c1_local_workspace_cwd.py::test_tool_registry_process_cwd_keeps_workspace_authority_separate tests/test_c1_local_workspace_cwd.py::test_working_directory_tool_reads_and_changes_relative_to_current_directory tests/test_agent_run_phases.py::test_legacy_run_adapter_preserves_session_working_directory
  ...
  6 tests collected in 1.36s
  ```

- Exact focused run from `D:\Atlas\core`:

  ```text
  python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_is_scoped_and_persisted tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_reaches_real_local_exec tests/test_c1_local_workspace_cwd.py::test_direct_local_exec_defaults_to_session_working_directory tests/test_c1_local_workspace_cwd.py::test_tool_registry_process_cwd_keeps_workspace_authority_separate tests/test_c1_local_workspace_cwd.py::test_working_directory_tool_reads_and_changes_relative_to_current_directory tests/test_agent_run_phases.py::test_legacy_run_adapter_preserves_session_working_directory --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t1-working-directory-tool-061-final2 --tb=short
  6 passed, 5 warnings in 18.87s
  ```

  The app-server test drove SDK JSON-RPC through the actual CLI child, approved `working_directory` and `local_exec`, observed a marker under the selected directory during the same run, observed another marker under it on the next run, and reopened the conversation in a new app-server process to read the persisted directory. The two app-server subprocesses exited naturally with code 0. The captured second provider request's latest user message includes `Current working directory` and the JSON-escaped selected path in `<turn_context>`.

- `python -m py_compile` for the eleven touched Python source/test files exited 0. AST checks confirmed `set_working_directory_from_run` is nested under `run_prompt` and runtime cwd synchronization is nested under `AtlasKernel.run.dispatch_tool`; parse/target-parent check exited 0. Focused `git diff --check` exited 0 with only an LF-to-CRLF notice for an existing dirty test file.

## Remaining obligations

- This does not close the complete DSH working-directory component. `T1-WORKING-DIRECTORY-SEMANTIC-GAP-058` still reports 193 of 235 base-component semantic units unmapped; the whole fixed source universe remains unresolved.
- The `tool-working-directory` source file still needs exact unit identities/digests and semantic decision-ledger accounting; this batch read and implemented its principal runtime behavior, but did not claim complete per-method source mapping.
- The new tool is currently exposed when local execution is configured. Local cwd remains restricted to the trusted workspace; SSH cwd transitions are not handled here. App-server external get/set and SDK surfaces exist, but visible Electron component wiring is not proven.
- Evidence uses an isolated temporary root and local FakeLLM provider. There is no real-model, desktop-visible, packaged-runtime, POSIX or SSH cwd evidence here.
- No commit or push was made. No user data, real credentials/config, port 8765, `data/memory`, or `origin_guard` was touched.
