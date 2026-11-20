# T1-WORKING-DIRECTORY-SESSION-IMPL-060

Status: PARTIAL (this implementation atom is verified; the DSH capability family remains open)

## Scope

Pinned plan: `docs/glm-hammer/plans/2026-11-17-atlas-dsh-atomic-parity-and-superiority.md`  
Pinned SHA256: `1999ad5e478f041fb1cb8ba74c9cbd14a29da41b488e5b179093052d662eae4e`  
Working tree baseline: branch `wave3`, HEAD `060071ab2ecf86d41cab90e98160183ce126bc69`.

Implemented a trust-root-preserving per-session working directory for the Python app-server/SDK path. Session `workspace` remains the authority root; `working_directory` is stored separately under conversation metadata, restored on reopen, validated as an existing local directory within the trusted workspace, and cannot be changed while the session has an active run. App-server run dispatch carries the selected directory through `RunRequest` and `AgentRunContext`.

The actual app-server execution probe exposed and fixed the production defaulting defect: `tool_node` populated missing local process `cwd` with the workspace before the session working-directory logic ran. It now leaves shell/exec/process cwd selection to the process-specific branch, which applies the session directory while preserving the workspace as the authorization root.

Files in this atom: `core/atlas/tools/app_server.py`, `core/atlas/agent/__init__.py`, `core/atlas/agent/run_phases.py`, `core/atlas/agent/tool_node.py`, `core/atlas/engine/tool_registry.py`, `sdk/python/atlas_sdk/app_server.py`, `core/tests/test_app_server_sdk_subprocess_attempts.py`, `core/tests/test_c1_local_workspace_cwd.py`, and `core/tests/test_agent_run_phases.py`. These files also contain unrelated pre-existing/earlier-session dirty changes; they were preserved.

## Red/Green Evidence

- The first real SDK/app-server subprocess marker run put `cwd-marker.txt` in the workspace root instead of the selected nested directory. A prior direct node test had supplied `cwd: ""`, which masked the production bug because `setdefault` did not fill the key. The regression now omits `cwd` entirely.
- The actual fix is the early `local_*` cwd default in `tool_node`: process tools no longer receive workspace cwd before the session-specific default is applied.
- Exact explicit collection from `D:\Atlas\core`:

  ```text
  python -m pytest --collect-only -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_is_scoped_and_persisted tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_reaches_real_local_exec tests/test_c1_local_workspace_cwd.py::test_direct_local_exec_defaults_to_session_working_directory tests/test_c1_local_workspace_cwd.py::test_tool_registry_process_cwd_keeps_workspace_authority_separate tests/test_agent_run_phases.py::test_legacy_run_adapter_preserves_session_working_directory
  tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_is_scoped_and_persisted
  tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_reaches_real_local_exec
  tests/test_c1_local_workspace_cwd.py::test_direct_local_exec_defaults_to_session_working_directory
  tests/test_c1_local_workspace_cwd.py::test_tool_registry_process_cwd_keeps_workspace_authority_separate
  tests/test_agent_run_phases.py::test_legacy_run_adapter_preserves_session_working_directory
  5 tests collected in 1.04s
  ```

- Exact final focused command:

  ```text
  python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_is_scoped_and_persisted tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_working_directory_reaches_real_local_exec tests/test_c1_local_workspace_cwd.py::test_direct_local_exec_defaults_to_session_working_directory tests/test_c1_local_workspace_cwd.py::test_tool_registry_process_cwd_keeps_workspace_authority_separate tests/test_agent_run_phases.py::test_legacy_run_adapter_preserves_session_working_directory --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t1-working-directory-060-focused-final --tb=short
  5 passed, 5 warnings in 12.10s
  ```

  The output included `local_execution.started cwd=...\workspace\nested\selected`; the app-server test verified the real child wrote the marker only in that selected directory. SDK/app-server process exited naturally with code 0.

- `python -m py_compile` over the nine listed Python source/test files exited 0. Target AST owner checks passed for `run_prompt`, `_phase_begin`, and `execute_tools_node`. `git diff --check` for this atom exited 0; Git printed only existing LF-to-CRLF notices.

## Remaining Obligations

- This does not close `T1-WORKING-DIRECTORY-SEMANTIC-GAP-058`: the fixed DSH base component has 235 semantic units, of which 42 are mapped and 193 remain unresolved; the whole pinned source universe remains substantially unresolved.
- Model-facing working-directory selection, remaining SDK/app-server/desktop surfaces, filesystem/LSP/terminal/workflow/child consumers, and cross-component state transitions still require source mapping and production implementation.
- SSH working-directory operations remain separate from local session directory selection. No live model, visible Electron, packaged desktop, or cross-platform proof was run here.
- No commit or push was made. No user data, real credentials/config, port 8765, `data/memory`, or `origin_guard` was touched.
