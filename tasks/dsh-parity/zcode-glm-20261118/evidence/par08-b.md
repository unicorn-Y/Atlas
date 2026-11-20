# PAR-08-B — keybindings client 409 retry replay + per-action conflicts (worker B rework)

- Date: 2026-11-19 (HKT)
- Worktree: `D:/Atlas/.worktrees/zcode-exec06-keybindings-cas`
- Branch: `zcode/exec06-keybindings-cas`
- Baseline/HEAD: `060071ab2ecf86d41cab90e98160183ce126bc69` (060071ab), unchanged; no commit/push/merge/stash.
- Scope: keybindings client (`keybindings.ts`), `ShortcutsPanel.tsx`, panel/service tests, temporary uvicorn + real dual-Electron-window acceptance. `App.tsx`, Electron main/preload, the backend CAS route (`u6_router.py`) and its semantics (revision/409/atomic replace) were not modified. No real data or credentials touched.
- Prior state read: `par07-codex-acceptance-20261119.md` row B and `par07-b.md`. Gap: window 2's retry PUT the whole local table with the latest revision, so window 1's edit of a different action disappeared.

## 1. Intent model

`KeybindingsSync` now keeps, per action, the window's actual edit intent, separate from the full local UI map:

| Edit kind | Recorded value | Replay effect |
|---|---|---|
| `set` | action -> non-empty `string[]` | assign that value on the latest file |
| `delete` | action -> `[]` (existing product/data semantics: `saveBindings` keeps `action: []`; backend accepts empty arrays) | assign `[]` |
| `reset` | action -> the default combo array | assign the default |
| `reset-all` | expands to one `reset` per entry of the supplied defaults map | assign defaults for all those actions |

- `record()` replaces the pending intent for the same action, so rapid edits coalesce to the newest one: set then delete = delete; delete then set = set; reset then edit = set/edit (covered by tests). `set` with an empty array is normalized to `delete`.
- The sync stores `baseline` = bindings of the last file it read/wrote, plus the revision of that read. Pending intents are never persisted into the file until a save/retry succeeds.
- `save()` snapshots per-action intent versions before queueing; a successful PUT clears only intents that were present in that snapshot, so an edit made while a PUT was in flight stays pending for the next save.
- `retry()` flow: `GET` latest -> start from a clone of the latest bindings -> for each pending action: if the file already equals the intent, do nothing; if the file changed that action relative to this window's baseline, raise a per-action conflict unless the caller chose a resolution; otherwise write the intended value into the merged map. Untouched actions keep the latest file value. Only the merged map is PUT, with the latest revision.
- Per-action conflict (`KeybindingsReplayConflictError`) carries `{ action, kind, local, file, baseline }`. `ShortcutsPanel` renders one row per action with the label, 本机 value, 文件 value, and `保留本机` / `采用文件` buttons; `按选择保存` stays disabled until every row is resolved. `local` writes the intended value; `file` drops that intent and keeps the file value. With no conflict left and no effective changes, retry adopts the file without a no-op PUT.
- Deliberate consequence: a local intent that equals the baseline is still recorded. If the remote changed that action meanwhile, the user gets a prompt rather than a silent local loss. `reset-all` therefore touches every default action; a concurrent remote edit to any of them is listed per action.

## 2. Files changed this pass (worktree-relative)

| File | This pass |
|---|---|
| `frontend/src/renderer/services/keybindings.ts` | 171 -> 333 lines. Added `KeybindingsEdit`, `KeybindingsActionIntent`, `KeybindingsResolution`, `KeybindingsConflictDetail`, `KeybindingsReplayConflictError`, baseline tracking, `record()`, versioned intent clearing, and the intent-replay `retry(resolutions)`. |
| `frontend/src/renderer/pages/ShortcutsPanel.tsx` | Approval/clear/add/restore/restore-all call sites now pass intents; retry uses recorded intents instead of the old full-map PUT; added per-action conflict rows with 保留本机/采用文件/按选择保存. |
| `frontend/src/renderer/services/keybindings.test.ts` | 167 -> 370 lines, 5 -> 16 tests. |
| `frontend/src/renderer/pages/ShortcutsPanel.test.tsx` | 131 -> 234 lines, 2 -> 5 tests. |
| `frontend/src/renderer/services/shortcuts.test.ts` | unchanged this pass (4 tests). |
| `core/tests/test_u6_keybindings.py` | unchanged this pass (7 tests). |
| `core/atlas/api/u6_router.py` | unchanged this pass; CAS semantics preserved. |

Overall worktree diff/status (includes the prior pass's files, no commit): tracked `git diff --numstat` — `u6_router.py` 94/15, `ShortcutsPanel.tsx` 171/9, `shortcuts.test.ts` 17/1; new files — `keybindings.ts` 333 lines, `keybindings.test.ts` 370, `ShortcutsPanel.test.tsx` 234, `test_u6_keybindings.py` 133. `git diff --check` exit 0 (only CRLF advice warnings). Source hashes used by the Electron run are in `evidence/par08-b-electron-run.log`.

## 3. Commands, exit codes, counts

| Check | Command | Result |
|---|---|---|
| Backend | `cd D:/Atlas/.worktrees/zcode-exec06-keybindings-cas/core && python -m pytest tests/test_u6_keybindings.py -q -p no:cacheprovider --basetemp=../.tmp/pytest-par08b` | **EXIT 0**, 7 passed, 5 warnings (`evidence/par08-b-pytest.txt`) |
| Frontend targeted | `cd .../frontend && D:/Atlas/node_modules/.bin/vitest run --root . src/renderer/services/keybindings.test.ts src/renderer/services/shortcuts.test.ts src/renderer/pages/ShortcutsPanel.test.tsx` | **EXIT 0**, 3 files / 25 tests passed (keybindings 16, shortcuts 4, panel 5; was 11) (`evidence/par08-b-vitest-targeted.txt`) |
| Frontend full | `cd .../frontend && D:/Atlas/node_modules/.bin/vitest run --root .` | **EXIT 0**, 83 files / 390 tests passed (was 376) (`evidence/par08-b-vitest-full.txt`) |
| Renderer tsc | `cd ... && D:/Atlas/node_modules/.bin/tsc -p frontend/tsconfig.renderer.json --noEmit` | **EXIT 0**, no output (`evidence/par08-b-tsc.txt`) |
| Electron dual-window | harness `run_electron.sh` (rebuild bundle + start uvicorn + two Electron processes) | **EXIT 0**, window1 exit 0, window2 exit 0, summary `result: PASS` (`evidence/par08-b-electron-run.log`, `...summary.json`) |

New test coverage: replay on the latest map preserving untouched remote actions; delete/unbind; single-action reset; reset-all (including an untouched file key and a per-action conflict); rapid coalescing for set->delete, delete->set, reset->edit; same-action conflict with no silent write, then `local` resolution and `file` resolution; same-value convergence; first create null; legacy document; HTTP transport body/409. Panel tests: 409 keeps local edit + reload adopts file; 409 -> retry preserves two different actions from two windows; delete replay preserves another window's edit; same-action conflict rows show action/local/file and `采用文件` keeps the file without a write; `保留本机` overwrites only that action.

## 4. Real dual-Electron-window acceptance (hard requirement)

Setup (all temporary, worktree `.tmp/par08b-run`, evidence under `D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence/`):

- Backend: worktree `core` on `PYTHONPATH`, `ATLAS_DATA_DIR=<temp>/data-root`, a temporary uvicorn host app that mounts the actual `atlas.api.u6_router` (`GET/PUT /api/u6/keybindings`), initial `data/keybindings.json` = `{"palette":["Ctrl+K"],"newTask":["Ctrl+N"]}`. Served on a random localhost port.
- Frontend: actual worktree `frontend/src/renderer/pages/ShortcutsPanel.tsx`, bundled with esbuild from the worktree sources (bundle/source SHA-256 in the run log), rendered in Electron 44.7.0.
- Two separate Electron processes, `--user-data-dir=<temp>/userdata-window1` and `.../userdata-window2`, each pinned with `app.setPath('userData', ...)`; argv and resolved `userDataPath` are in every snapshot JSON.
- Driver uses `executeJavaScript` to click the real binding buttons, dispatch real `keydown` events (Ctrl+Alt+U for the palette, Ctrl+Alt+N for newTask), click the real 重试 button, and `capturePage()` for PNGs.
- Ordering: window 2 mounts first and reads revision 1; window 1 mounts, reads revision 1 and saves action A; window 2 then edits action B and gets 409; window 2 clicks 用本机改动重试保存; window 1 captures the final state.

Observed sequence (backend log, `...backend.log`):

```
PUT /api/u6/keybindings 200 OK    # window1 saves palette Ctrl+Alt+U (rev 1 -> 2)
PUT /api/u6/keybindings 409 Conflict  # window2 tried expected_revision=rev1
PUT /api/u6/keybindings 200 OK    # window2 retry: GET rev2, replay only newTask (rev2 -> 3)
```

Final temp `keybindings.json` (`...keybindings-after.json`): `palette = ["Ctrl+Alt+U"]`, `newTask = ["Ctrl+Alt+N"]`; SHA-256 `17d2c1acd0777dff6a551e21bd2d9f0af44e4b09410640cc17e947427426f63e`. Window 2's 409 snapshot shows `保存冲突`, local cache `newTask=["Ctrl+Alt+N"]`, server rev 2 still with window 1's palette; post-retry snapshot shows no conflict, status `已重放本机改动并保存，其他窗口的修改已保留`, local cache palette Ctrl+Alt+U + newTask Ctrl+Alt+N. Window 1's post-retry snapshot still holds its palette edit. Evidence files:

- `evidence/par08-b-electron-summary.json` (PASS, exit codes, final values/hash)
- `evidence/par08-b-electron-run.log` (worktree/HEAD, source+bundle hashes, argv with both `--user-data-dir`)
- `evidence/par08-b-electron-backend.log` (real 200/409/200 request statuses)
- `evidence/par08-b-electron-window1-ready.json/.png`, `...window1-saved.json/.png`, `...window1-after-window2-retry.json/.png`
- `evidence/par08-b-electron-window2-ready.json/.png`, `...window2-409.json/.png`, `...window2-retry.json/.png`
- `evidence/par08-b-electron-initial-keybindings.json`, `...baseline-get.json`, `...keybindings-after.json`
- `evidence/par08-b-electron-window1-driver.log`, `...window2-driver.log`
- `evidence/par08-b-electron-harness-*` (backend app, driver, page, run script), `...-commands.txt`

## 5. Product entry

- UI: `frontend/src/renderer/pages/ShortcutsPanel.tsx`, still the same component rendered from the settings sheet in `frontend/src/renderer/App.tsx` (`sheet === 'shortcuts'`, around App.tsx:3622) with `apiBaseUrl`/`models`. `App.tsx` was not touched.
- Backend: `core/atlas/api/u6_router.py` `GET/PUT /api/u6/keybindings`, already mounted by the existing u6 router; no router registration change. CAS (`expected_revision`, 409, atomic temp+fsync+replace) untouched.
- Electron main/preload: untouched.

## 6. Not verified / boundaries

- The dual-window run used a temporary uvicorn **host app** mounting the real u6 router and the real bundled panel, not the full `atlas.server` lifespan or a packaged desktop client. No models/LLM involved.
- The same-action conflict UI (per-row 保留本机/采用文件/按选择保存) is covered by `react-test-renderer`/vitest, not by the dual-window Electron run; the dual-window run covers the different-action replay acceptance gap.
- `App.tsx` still polls `updated_at` every 3s; there is no ≤1s broadcast, and this pass did not change that (protected in-flight file).
- A malformed `keybindings.json` still yields GET 422 and the panel has no explicit repair/overwrite-corrupt-file flow; unchanged from the prior pass.
- The backend lock remains process-local (`threading.Lock`); content CAS still rejects stale revisions.
- Mount adoption heuristic unchanged: local non-default rebinds win over the file; the file is adopted on a machine with defaults only.
- `reset-all` is treated as an intent over every supplied default action, so a concurrent remote edit to any of them produces a conflict row rather than being silently kept or overwritten.
- No commit/push/merge; worktree HEAD is still `060071ab`. Main `D:/Atlas` worktree was not edited except required evidence/receipt files under `tasks/dsh-parity/zcode-glm-20261118/evidence/`; `App.tsx` in main was untouched.