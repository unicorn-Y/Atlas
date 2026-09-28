# CODEX-ATLAS-REAL-WORLD-AGENT-E2E-WAVE1 Result

## Run identity

- Starting branch: `main`
- Actual `BASE_HEAD` after syncing `origin/main`: `478e26f855ef9bed93cf24198bb960040ec10ff5`
- Source implementation files changed: none. This delivery records the acceptance wave and its observed failures; no product fix was made.
- The user-owned untracked report `Atlas竞品对比报告_2026-09-28.docx` was left untouched.

## Executed scenarios and prompts

### Coding through the normal Agent orchestration path

Prompt:

> Inspect the repository workspace=`<isolated fixture path>` and repair its failing regression. Use the available coding intelligence when relevant, run verification, inspect the Git diff and status, and explain the cause with concrete evidence.

The fixture began with `answer()` subtracting its inputs while its test expected addition. A deterministic test provider drove the ordinary `AgentOrchestrator`, `ToolRegistry`, local execution runtime, and the shared Atlas MCP bridge. It called `coding_repo_map`; `local_file` list/read; `local_shell` pytest (first run failed); `local_file` write (automatic checkpoint event); pytest again (passed); `execute_code`; and `local_git` diff/status. The fixture ended with `answer.py` returning `left + right`, one modified file, and the Agent reporting the initial failure and passing rerun.

This proves the normal Agent tool orchestration path with a deterministic provider. It does not prove the configured Atlas Gemini provider works; a separate minimal request through the configured gateway returned `Invalid token`.

### Browser form

An isolated local HTML fixture was opened in `agent-browser` using a separate restore session. The exact browser actions were: `open file:///.../atlas-wave1-browser-b01719fd/index.html`; `snapshot`; `fill #name "Lin Zhao"`; `fill #email "lin.zhao@example.test"`; `click button[type=submit]`; `get text #result`; `close`.

The snapshot exposed the local form and the rendered DOM result was `Saved: Lin Zhao <lin.zhao@example.test>`. This browser scenario passed using the installed `agent-browser` CLI. Browser Use gateway execution remained unavailable because the configured gateway rejected its token.

### Windows desktop note (attempted; failed)

Prompt:

> Read `desktop_file:<temporary source>`. Create `desktop_target:<temporary target>` with a concise note from those facts, and edit/save it through a real Windows Notepad window. Verify by reading the saved text through Atlas `local_file`.

The Agent read the source and wrote an initial placeholder, which created an automatic checkpoint. It launched Notepad, listed/focused a window, captured a Computer Use observation, sent Ctrl+A, typed, sent Ctrl+S, and read the file back. The read-back remained the placeholder, so the scenario failed. An earlier Python GUI launch returned Windows `WinError 740`; Notepad's single-instance/tab behavior then routed test files through the pre-existing Notepad process and raised a path dialog. No user document content was intentionally targeted. The resulting task-created `desktop-note*` tabs remain visible in that Notepad window; repeated interaction was stopped to avoid further changing the user's desktop.

The isolated Computer Use runtime did observe and focus a Notepad window, but this is not end-to-end success. The Windows-specific focus test also failed as recorded below.

## Checkpoint and MemoryOS evidence

- The coding Agent emitted `checkpoint_created` before writing the fixture source file. The initial failing pytest run and successful rerun were both observed through `local_shell`.
- The separate isolated restore check mutated `restore-validation.txt`, restored its checkpoint, and verified the original content (`RESTORE_CONTENT_VERIFIED True`).
- Two realistic Agent fixture runs created MemoryOS experience proposals. After closing and reopening the SQLite-backed store, both proposals remained `pending`; `list_facts()` returned empty. No fact was promoted.
- Runtime evidence was written under temporary roots such as `%TEMP%\atlas-real-world-wave1-8wsh0sp1` and `%TEMP%\atlas-real-world-wave1-rn6aj9x9`; browser fixture: `%TEMP%\atlas-wave1-browser-b01719fd\index.html`. These are test artifacts, not product source changes.

## Verification

| Check | Result |
|---|---|
| Agent, capabilities, enrichment, local execution, Computer Use, P18X, MemoryOS, server, and release build-script suites (with the known metadata test deselected) | `228 passed, 1 failed, 1 deselected` in 74.89s |
| Windows-specific failing test | `test_real_desktop_observe_input_clipboard_and_window_management`; Windows refused focus activation for the isolated HWND (`Windows denied focus activation for window 2956706`) |
| Known pre-existing deselection | `test_message_with_metadata`; a prior run failed with `KeyError: metadata` |
| `pip check` using the project core virtualenv | Passed: `No broken requirements found.` |
| `git diff --check` | Passed before writing this result file; repeated at delivery |
| Changed-file Ruff | Not applicable: no source files were changed |
| Process residue | No task-run Atlas/Electron/backend/browser/fixture process remained in the focused post-run query. Pre-existing long-running services were preserved. |

## Packaged desktop evidence

`npm run dist:win` completed successfully from the current checkout. The rebuilt manifest records `git_commit` `478e26f855ef9bed93cf24198bb960040ec10ff5`, Node `v22.23.3`, and the verified Node archive SHA-256 `2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71`. Installer SHA-256: `6a2569fc0d1e88411f09ef6d4c54182638c31d5b7054015c5454f20cfba1d6f0`.

The opt-in packaged Electron acceptance test was attempted three times. Each attempt started the packaged app and passed its health wait, then failed with `httpx.ReadTimeout` during follow-up API reads. The clean packaged conversation and restart assertions therefore remain unverified. The packaged acceptance test reported one skipped installer scenario.

## External backends

- Hermes `v0.21.4`: minimal safe-mode prompt returned `PONG`. CLI emitted a warning that a previous update had not restarted running gateways.
- Pi: CLI unavailable.
- Codex CLI `0.155.0-alpha.16.4`: read-only ephemeral prompt returned `PONG`.
- Claude: launch returned `Access is denied`.
- ZCode `0.16.9`: prompt blocked because its built-in provider config was missing at `D:\zcode\resources\glm\provider\zcode-builtin.json` and `D:\config\provider\zcode-builtin.json`.
- Atlas configured Gemini gateway: minimal normal Agent provider request returned `Invalid token`.

## Product-level failure matrix

| Scenario | Normal Agent | CLI | Coding | Browser | Computer | Checkpoint | Memory | Packaged | Result |
|---|---|---|---|---|---|---|---|---|---|
| Coding regression fixture | Yes, deterministic test provider | local shell/git tools | repo map, read/write, failing then passing pytest | — | — | automatic checkpoint emitted | pending proposal survived restart | — | Passed orchestration path; live Atlas provider remains blocked |
| Browser local form | No Atlas Agent browser provider | installed `agent-browser` | — | open/snapshot/fill/submit/DOM read-back | — | — | — | — | Passed |
| Windows desktop note | Yes, deterministic test provider | local execution/file tools | — | — | window list/focus/observe/type/save attempted | checkpoint emitted before placeholder write | pending proposal survived restart | — | Failed: save/read-back mismatch; desktop path left task tabs |
| Computer Use Windows regression test | — | pytest | — | — | isolated window focus denied | — | — | — | Failed: Windows focus activation denied |
| Packaged desktop | — | Electron packaged acceptance | — | — | — | — | — | build passed; acceptance timed out after health | Partial: packaged API/conversation/restart acceptance unverified |

## Closeout

The browser and deterministic normal-Agent coding paths passed. The desktop note, native Windows focus test, configured Atlas provider, and full packaged acceptance did not pass. These are explicit product/environment gaps; this wave did not create follow-up FIX tasks.
