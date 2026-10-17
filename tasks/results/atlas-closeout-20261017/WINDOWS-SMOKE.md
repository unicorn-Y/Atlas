# Windows isolated smoke evidence

## Setup and identity

| Component | Isolated value |
|---|---|
| Source worktree | `D:\atlas-closeout-main-20261017` |
| Integration commit | `6b5da15adaa32e495c7285b36eb9a50e575e739d` |
| Data root | `D:\atlas-closeout-runtime-20261017` |
| Electron user data | `D:\atlas-closeout-runtime-20261017\desktop-profile` |
| API | `127.0.0.1:18765` |
| Fake OpenAI-compatible provider | `127.0.0.1:19191` |
| CDP | `127.0.0.1:19335` |

`start-atlas.bat` exited successfully. Its first cold start at `81b671fa46fd823bf9896bff7c80f2775b3c4360` recorded stamp steps `python`, `python-lock`, `npm`, `electron`, `frontend`; the locked requirements installation and frontend build completed. After the updater-only ATL-017 change, the final launch at `6b5da15adaa32e495c7285b36eb9a50e575e739d` reused those artifacts and wrote `steps: []`. The built frontend loaded in Electron and `/api/health` returned `ok`, with all 11 reported components ready. The final ATL-017 source is therefore verified at launcher/runtime flag level; frontend/backend were built from the immediately preceding integration source.

## Actual UI and chat

Playwright attached to the loopback CDP endpoint, observed the Atlas window, submitted `请只回复 ok`, and observed the fake model response `ok` with UI state `完成`. The screenshot is [windows-fake-chat.png](evidence/windows-fake-chat.png); its SHA-256 is `DC6223D0C1F19C91144DBB2084D354B95ACC05628A80C052739435214BA1C9EC`.

The initial launch inherited no `ATLAS_PORT`, so the app probed the normal default port and observed the running user's Atlas health endpoint. This was discovered before any chat action. Only a read-only `/api/health` request reached that endpoint. The isolated Electron was stopped and relaunched with `ATLAS_PORT=18765`, after which the chat smoke used the isolated API, data root, profile, and fake provider.

## Computer Use preservation and Origin test

The final launcher flags were observed on the running process: `--remote-debugging-address=127.0.0.1 --remote-debugging-port=19335`, with no `--remote-allow-origins=*`.

Controlled A/B results from separate isolated Electron instances:

| CDP launch | No-Origin client / CUA | Synthetic foreign Origin |
|---|---|---|
| Wildcard Origin, port 19335 | Accepted; composer click, text insertion/readback/clear passed | Accepted |
| No wildcard, port 19336 | Accepted; same CUA sequence passed | HTTP 403 |
| Loopback address + no wildcard, port 19337 | Accepted; same CUA sequence passed | HTTP 403 |

All three were observed listening only on `127.0.0.1`. The 19336 and 19337 probe instances were stopped after capture. No local Computer Use capability was disabled.

## Focused test results

- Windows updater transaction tests: 3 passed.
- Memory source/forget regression file: 7 passed; temporary isolated pytest root.
- SSH routing file: 2 passed, 1 failed at import (`No module named 'tools'`); the failing test imports `tools.terminal_scope`, while the checkout contains `core/atlas/tools/terminal_scope.py`. This is an unresolved test-environment/package-path issue, not a passing result.
- Locked dependency installation and frontend build: succeeded during the cold start; build stamp confirms both steps.

## Reproduction

From `D:\atlas-closeout-main-20261017` in PowerShell, with the fake provider available on 19191:

```powershell
$env:ATLAS_DATA_DIR='D:\atlas-closeout-runtime-20261017'
$env:ATLAS_DESKTOP_USER_DATA_DIR='D:\atlas-closeout-runtime-20261017\desktop-profile'
$env:ATLAS_DEBUG_PORT='19335'
$env:ATLAS_PORT='18765'
cmd.exe /c 'start-atlas.bat <nul'
```

This smoke used the fake model only. No real model credentials or user memory were used.
