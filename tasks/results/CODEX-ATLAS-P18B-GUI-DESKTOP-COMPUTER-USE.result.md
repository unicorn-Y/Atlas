# CODEX-ATLAS-P18B-GUI-DESKTOP-COMPUTER-USE Result

STATUS: BLOCKED — implementation and validation are incomplete; the P18B Acceptance Gate is not met.
BASE_HEAD: 30aaa064dd8dc3f0b2fa2ed08c3eeb7cce6c36f9

## Delivered in this attempt

- Added a Windows desktop runtime using `mss` and Win32 APIs for screen observations, monitor/window discovery, window management, mouse/keyboard input, and clipboard operations.
- Registered the runtime in the existing server lifecycle and Agent tool loop alongside P18A local execution and MCP tools.
- Passed screenshot image data back to the next Agent model call and emit a clear capability failure when the selected model rejects image input.
- Added the default `computer_use.permission_mode = "full_access"` configuration and native desktop/Agent coverage.

## Verification

- `tests/test_agent.py`: 29 passed.
- P18A local execution, Agent, MCP, Skill, and full `tests/test_server.py` regression selection: 160 passed.
- Windows `npm run dist:win`: completed and produced the unpacked product and NSIS installer.
- P17 packaged clean-user acceptance: 1 passed.
- P17 installer install/uninstall/reinstall acceptance: 1 passed; isolated install root and installer processes were removed.
- Ruff on the changed Python files: passed.
- `git diff --check`: passed.
- P18B native desktop test: the observation, monitor, window enumeration/focus, Unicode typing, and clipboard assertions were reached successfully, but the explicit real-click assertion failed: the test window's Tk button callback remained at 0 after `computer_mouse(click)`.

## Acceptance gaps

- Fix and verify actual click delivery. The live Windows test shows the cursor can be moved to the target, but the target control does not activate. Mouse click, double click, drag, and scroll therefore do not have sufficient end-to-end evidence.
- Run the required Notepad save/read workflow and a two-application workflow through the normal Agent loop.
- Run a real observe → reason → act → observe loop and demonstrate mixed P18A CLI/P18B GUI tool use in the same Agent run.
- Run a P18B-specific packaged/installed GUI workflow. The P17 release acceptance verifies the package lifecycle, not the P18B GUI workflow.

This result records a blocked delivery rather than claiming P18B acceptance. The taskbook's packaged full-desktop Acceptance Gate remains unmet.
