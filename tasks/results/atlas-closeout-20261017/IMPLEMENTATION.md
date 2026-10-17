# Atlas closeout implementation

Status: `AWAITING_GPT6_WINDOWS_REVIEW`

Integration branch: `integration/atlas-fixes-20261017`
Integration tip: `6b5da15adaa32e495c7285b36eb9a50e575e739d`

## Delivered source batches

- ATL-007 `617bf70f6df131bd1d7f293a644fe9b1c4e42acc`: SSH write/patch results disclose that remote edits do not have Atlas LSP diagnostics. This is an honest limitation notice; remote LSP transport remains unavailable.
- ATL-015 `8ae67d2c0c9a8c501db3fa0c39f6436f951dc4b3` and `81b671fa46fd823bf9896bff7c80f2775b3c4360`: exact-source tombstones exclude forgotten derived memory from search, browse, facts, episodes, and extraction while leaving raw session history available. Missing UIDs report the coverage boundary; identical text with different message UIDs stays distinct.
- ATL-017 `6b5da15adaa32e495c7285b36eb9a50e575e739d` (upstream worker commit `5e5fc26d5fa9ff93a97ca54c84e3cf0bfd98ce10`): CDP binds explicitly to `127.0.0.1`; wildcard Origin permission is removed. Atlas-style no-Origin CUA remains available.

All three batches are present on the remote integration tip. No change was made to `D:\Atlas`.

## Windows isolated run

- Isolated source: `D:\atlas-closeout-main-20261017`, integration commit above.
- Isolated data root: `D:\atlas-closeout-runtime-20261017`.
- Isolated Electron profile: `D:\atlas-closeout-runtime-20261017\desktop-profile`.
- Isolated API: `127.0.0.1:18765`; fake provider: `127.0.0.1:19191`; CDP: `127.0.0.1:19335`.
- `start-atlas.bat` completed with exit 0. The first cold start at `81b671fa46fd823bf9896bff7c80f2775b3c4360` recorded `python`, `python-lock`, `npm`, `electron`, and `frontend` steps; locked requirements installation and frontend production build completed. After the updater-only ATL-017 change, the final relaunch at `6b5da15adaa32e495c7285b36eb9a50e575e739d` reused those built artifacts; its stamp has `steps: []`. Thus the Windows app/chat run used the final launcher source with the previously built UI/backend source.
- Electron loaded the built `file://` UI. The API health response was `ok` with 11 components ready. The first smoke attempt exposed an isolation-port mismatch; I stopped the isolated Electron and restarted with `ATLAS_PORT=18765`. The only request made to the pre-existing `D:\Atlas` API was a read-only `/api/health` probe; no conversation or mutation request was sent there.
- Through the isolated Electron UI, submitted `请只回复 ok`; the local fake provider returned `ok` and the UI reported completion. Screenshot: [windows-fake-chat.png](evidence/windows-fake-chat.png), SHA-256 `DC6223D0C1F19C91144DBB2084D354B95ACC05628A80C052739435214BA1C9EC`.
- The launched command line contained `--remote-debugging-address=127.0.0.1 --remote-debugging-port=19335` and no wildcard Origin flag.

## Focused Windows checks

- `node --test scripts/atlas-update-transaction.test.mjs`: 3 passed, 0 failed.
- `core/tests/test_memory_source_search_rework.py`: 7 passed on Windows, including exact UID forgetting and missing-UID boundary; temporary pytest data only.
- `core/tests/test_hermes_ssh_routing.py`: 2 passed, 1 failed. The failure is test import setup: `ModuleNotFoundError: No module named 'tools'` at `from tools.terminal_scope import get_terminal_scope`; no assertion failed. Worker-reported focused notice/routing checks passed separately.
- ATL-017 A/B, performed in isolated Windows Electron instances: original wildcard-origin instance accepted both no-Origin CUA and a synthetic foreign Origin; no-wildcard and proposed loopback/no-wildcard instances accepted no-Origin CUA and rejected the synthetic foreign Origin with HTTP 403. CUA exercised composer click, `Input.insertText`, text readback, and clearing. All listeners were `127.0.0.1`; second and third instances were stopped.

## Boundaries

No live production model, real Atlas memory, shared user profile, installer, microphone, or LAN test was used. ATL-016 remains conditional on a second writer becoming active. The API health observation of `D:\Atlas` was read-only. See [ISSUE-25-STATUS.md](ISSUE-25-STATUS.md) and [CUTOVER.md](CUTOVER.md).
