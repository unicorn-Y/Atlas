# PAR-09-B2 — first-create keybindings race: default-aware conflict baseline

- Date: 2026-11-19 (HKT)
- Worktree: `D:/Atlas/.worktrees/zcode-exec06-keybindings-cas`
- Branch: `zcode/exec06-keybindings-cas`
- HEAD: `060071ab2ecf86d41cab90e98160183ce126bc69` (060071ab), unchanged; no commit/push/merge/stash.
- Scope: `frontend/src/renderer/services/keybindings.ts`, `ShortcutsPanel.tsx`, their tests; temporary uvicorn harness + real dual-Electron-window acceptance. `App.tsx`, Electron main/preload, `core/atlas/api/u6_router.py` and its CAS semantics untouched (backend diff still the PAR-08-B 94/15 only). No real data or credentials touched.

## 1. Baseline and reproduced gap

PAR-08-B left the existing-file replay correct, but a first create still produced a false same-action conflict. Baseline behaviour for `GET /api/u6/keybindings` on a missing file is `{"bindings":{},"updated_at":-1,"revision":null}` (`core/atlas/api/u6_router.py:134-140`). `KeybindingsSync.refresh()` stored `baseline = cloneBindings({})`. When window 1 then created the file with the visible defaults plus its one edit, window 2's replay compared its pending action against `baseline[action] ?? []`, i.e. `[]`, while the file held the default combo. `remoteChanged` was therefore true and the panel asked the user to adjudicate a default value nobody had edited.

Reproduced in the new unit test `uses the visible defaults as the conflict baseline when the file does not exist yet` before the fix (it raised `KeybindingsReplayConflictError` for the untouched default action); the Electron `missing` scenario is the end-to-end reproduction.

## 2. Change

### 2.1 Effective baseline (`keybindings.ts`)

Added `effectiveKeybindings(bindings, defaults)` (`keybindings.ts:161-169`):

- An action present in the file wins, **including an explicit `[]`** (the user unbound it).
- An action absent from the file resolves to the effective default.
- Absence and `[]` stay distinct; comparisons/replay merge/persisted file values never fold one into the other.

`KeybindingsSync` now receives the panel's visible defaults (`constructor(transport, defaults = {})`, `keybindings.ts:199-203`; the panel passes `defaultBindings()` at `ShortcutsPanel.tsx:46`). `refresh()`, the implicit read inside `save()`, and every successful read/write set the baseline from `effectiveKeybindings(...)` (`keybindings.ts:256,273,278,303,346,354`). `retry()` compares the latest effective value and the effective baseline per action (`keybindings.ts:308-326`):

- Missing file → every action's baseline is the default, so a file containing defaults plus a different action's edit is not a remote edit of the default actions.
- Explicit `[]` in the file is a real value; a default is a real value; they conflict only when the file value differs from the effective baseline.
- Pending intents are still only the actions this window edited; untouched remote actions are never rewritten.

### 2.2 Unchanged replay semantics

The PAR-08-B per-action intent model, 409 → latest-revision replay, per-action conflict error, and 保留本机/采用文件 resolution are unchanged. `save()` still snapshots intent versions before queueing and clears only those on success; retry still starts from a clone of the latest raw file, so untouched keys (absent or `[]`) are preserved byte-for-byte in meaning.

### 2.3 Files changed this pass (worktree-relative)

| File | This pass |
|---|---|
| `frontend/src/renderer/services/keybindings.ts` | 333 -> 366 lines. `effectiveKeybindings`; defaults in constructor; effective baseline in refresh/save/retry. |
| `frontend/src/renderer/pages/ShortcutsPanel.tsx` | 171/9 -> 174/9 diff; only the `KeybindingsSync` construction now passes `defaultBindings()`. |
| `frontend/src/renderer/services/keybindings.test.ts` | 370 -> 523 lines (16 -> 23 tests). |
| `frontend/src/renderer/pages/ShortcutsPanel.test.tsx` | 234 -> 273 lines (5 -> 6 tests). |
| `frontend/src/renderer/services/shortcuts.test.ts` | unchanged (4 tests). |
| `core/atlas/api/u6_router.py` | unchanged this pass (94/15, same as PAR-08-B). |
| `core/tests/test_u6_keybindings.py` | unchanged this pass (7 tests). |

`git diff --numstat` for the worktree: `u6_router.py 94/15`, `test_u6_keybindings.py 134/0`, `ShortcutsPanel.test.tsx 273/0`, `ShortcutsPanel.tsx 174/9`, `keybindings.test.ts 523/0`, `keybindings.ts 367/0`, `shortcuts.test.ts 17/1`. `git diff --check` exit 0 (CRLF advice only). No `App.tsx`, `frontend/electron/**`, or other worktree files were touched.

## 3. New coverage

`keybindings.test.ts` (23 tests total, 7 new):

- `effectiveKeybindings` keeps explicit `[]` and fills absent keys from defaults.
- Missing file: baseline is the visible defaults; window 1 creates defaults + palette edit; window 2's newTask 409 replays to 200 with no conflict and keeps window 1's palette.
- Explicit unbind stays `[]` through replay; a missing key is not materialized as `[]`.
- Reset-to-default over an explicit `[]` writes the default.
- Explicit unbind replays when another window only wrote defaults during the first create.
- Same-action first-create race still raises a per-action conflict (baseline = default, file = window 1's value, local = window 2's value), writes nothing before the user chooses, then `local` resolution wins.
- Existing-file replay test now passes defaults to prove the previous semantics are unchanged.

`ShortcutsPanel.test.tsx` (6 tests, 1 new): mount with `revision:null`, another window creates the file with defaults + palette edit, newTask edit gets 409, retry PUTs `expected_revision` = latest with palette preserved and no `data-keybindings-replay-conflict` row; cache and status match.

## 4. Commands and exit codes

| Check | Command | Result |
|---|---|---|
| Backend | `cd D:/Atlas/.worktrees/zcode-exec06-keybindings-cas/core && python -m pytest tests/test_u6_keybindings.py -q -p no:cacheprovider --basetemp=../.tmp/pytest-par09b2` | **EXIT 0**, 7 passed, 5 warnings (`evidence/par09-b2-pytest.txt`) |
| Frontend targeted | `cd .../frontend && D:/Atlas/node_modules/.bin/vitest run --root . src/renderer/services/keybindings.test.ts src/renderer/services/shortcuts.test.ts src/renderer/pages/ShortcutsPanel.test.tsx` | **EXIT 0**, 3 files / 33 tests passed (keybindings 23, shortcuts 4, panel 6; was 25) (`evidence/par09-b2-vitest-targeted.txt`) |
| Frontend full | `cd .../frontend && D:/Atlas/node_modules/.bin/vitest run --root .` | **EXIT 0**, 83 files / 398 tests passed (was 390) (`evidence/par09-b2-vitest-full.txt`) |
| Renderer tsc | `cd ... && D:/Atlas/node_modules/.bin/tsc -p frontend/tsconfig.renderer.json --noEmit` | **EXIT 0**, no output (`evidence/par09-b2-tsc.txt`) |
| Electron harness | `cd .../.tmp/par09b2-harness && bash run_electron.sh` | **EXIT 0**, overall `result: PASS`, window1/window2/validate exit 0 in all three scenarios (`evidence/par09-b2-electron-summary.json`, per-scenario `...-summary.json`/`...-run.log`) |

Harness: esbuild bundle of the actual worktree `ShortcutsPanel.tsx` (bundle SHA-256 `33b6d1e8062b71a36a512457c237ffaf375403d8a841789052e4bd78373c8dac`; panel SHA-256 `d41c8a35...`; service SHA-256 `78941bb8...`), served by a temporary uvicorn host that mounts the real `atlas.api.u6_router`; Electron 44.7.0; each window its own `--user-data-dir` and `app.setPath('userData')`; real button clicks and `KeyboardEvent` dispatches; `capturePage()` PNGs. Temporary data and per-run dirs: `.tmp/par09b2-run/<scenario>/data-root`.

## 5. Real dual-window acceptance — three initial states

### a. Initial file missing

Baseline: `GET` returned `{"bindings":{},"updated_at":-1,"revision":null}` (`...-missing-baseline-get.json`); window2's ready snapshot had no localStorage cache, confirming it mounted on defaults, not on file data.

Sequence (`...-missing-backend.log`):

```
PUT /api/u6/keybindings 200 OK    # window1 first create, expected null, defaults + palette Ctrl+Alt+U
PUT /api/u6/keybindings 409 Conflict   # window2 newTask save, expected null
PUT /api/u6/keybindings 200 OK    # window2 retry on latest revision, replays newTask only
```

Observed: window2 409 banner (`...-missing-window2-409.json`); after retry status `已重放本机改动并保存，其他窗口的修改已保留`, conflict banner gone, `replayConflict` null, zero per-action rows, file has `palette=["Ctrl+Alt+U"]`, `newTask=["Ctrl+Alt+N"]`, `settings=["Ctrl+,"]` (every other default unchanged). Window1's post snapshot sees both edits (`...-missing-window1-after.json`). Final `...-missing-keybindings-after.json` SHA-256 `17d2c1acd0777dff6a551e21bd2d9f0af44e4b09410640cc17e947427426f63e`. Exit codes: window1 0, window2 0, validate 0. Screenshots: `...-missing-window2-{ready,409,retry}.png`, `...-missing-window1-{saved,after}.png`.

### b. Initial file present (different actions, PAR-08-B regression)

Baseline: `{"palette":["Ctrl+K"],"newTask":["Ctrl+N"]}`, revision `0a0dfafa...`. Sequence (`...-existing-backend.log`):

```
PUT /api/u6/keybindings 200 OK    # window1 palette Ctrl+Alt+U (rev 0a0d... -> b012...)
PUT /api/u6/keybindings 409 Conflict  # window2 newTask, expected rev 0a0d...
PUT /api/u6/keybindings 200 OK    # window2 retry on rev b012...
```

Final file `palette=["Ctrl+Alt+U"], newTask=["Ctrl+Alt+N"], settings=["Ctrl+,"]`, same SHA-256 as (a). Window2 retry snapshot: no conflict, no rows, status `已重放本机改动并保存，其他窗口的修改已保留`; window1 post snapshot sees both. Exit codes 0/0/0. Evidence: `...-existing-window2-{ready,409,retry}.json/.png`, `...-existing-window1-{saved,after}.json/.png`, `...-existing-keybindings-after.json`.

### c. Same action — explicit per-action adjudication

Baseline same file/revision as (b). Window1 saved palette `Ctrl+Alt+U` (200); window2 saved palette `Ctrl+Alt+O` (409), then clicked 用本机改动重试保存. Retry read the latest file and raised the per-action conflict without a PUT:

```
status: 有 1 项快捷键与文件冲突，请逐项选择保留本机或采用文件
row: 搜索与命令（palette） 本机：Ctrl+Alt+O 文件：Ctrl+Alt+U
file palette still ["Ctrl+Alt+U"]   # nothing overwritten before the choice
```

(`...-same-action-window2-replay-conflict.json/.png`). Clicking 保留本机 then 按选择保存 wrote the merged map (200): final file `palette=["Ctrl+Alt+O"]`, `newTask=["Ctrl+N"]`, all other defaults intact, SHA-256 `6467823c45e4159a7bb574a6a3bbf8b817d1e2bcac7c8b7b2db7e26feadb3857`; window2 status `已按选择保存，本窗口改过的操作已重放，其他窗口的修改已保留` (`...-same-action-window2-resolved.json/.png`). Backend log has exactly two 200 PUTs and one 409 PUT (the conflicted retry performs GETs, no PUT until resolution). Exit codes 0/0/0. Window1's local palette cache remains `Ctrl+Alt+U`, the file is `Ctrl+Alt+O` after the explicit choice — intentionally visible in `...-same-action-window1-after.json`.

Overall: `evidence/par09-b2-electron-summary.json` → `result: PASS` with three scenario entries, each `backend_put_200: 2`, `backend_put_409: 1`, `problems: []`.

## 6. Evidence index (all under `tasks/dsh-parity/zcode-glm-20261118/evidence/`)

- `par09-b2.md` (this receipt)
- `par09-b2-pytest.txt`, `par09-b2-vitest-targeted.txt`, `par09-b2-vitest-full.txt`, `par09-b2-tsc.txt`
- `par09-b2-electron-summary.json`
- Per scenario `missing|existing|same-action`:
  - `par09-b2-electron-<scenario>-summary.json`, `...-run.log`, `...-backend.log`, `...-baseline-get.json`
  - `...-initial-keybindings.json` (missing: absent by design)
  - `...-keybindings-after.json`
  - `...-window{1,2}-driver.log`
  - `...-window1-{ready,saved,after}.json/.png`
  - `...-window2-ready.json/.png`, `...-window2-409.json/.png`, `...-window2-retry.json/.png` (a/b), `...-window2-replay-conflict.json/.png` and `...-window2-resolved.json/.png` (c)
- `par09-b2-electron-harness-{backend_app.py,driver.cjs,harness.tsx,index.html,run.sh}`; run command lines are in each `...-run.log` (argv includes both `--user-data-dir`s, Electron version, source/bundle hashes).

## 7. Not verified / boundaries

- The dual-window runs used a temporary uvicorn **host app** mounting the real u6 router and static-served real bundled panel, not the full `atlas.server` lifespan or a packaged desktop client. No models/LLM involved.
- The `missing` scenario's two windows start with empty localStorage; a machine that already has local rebinds cached but no file was not exercised. The conflict baseline follows `defaultBindings()` per the dispatch; the panel's older mount heuristic (local non-default rebinds win over the file) is unchanged.
- Same-action resolution in Electron covered 保留本机 only; 采用文件 is covered by the existing panel/unit tests (`asks per action ... adopts the file value`).
- `App.tsx` still polls `updated_at` every 3s; no broadcast change in this pass.
- A malformed `keybindings.json` still yields GET 422 and there is no explicit corrupt-file repair flow.
- Backend lock remains process-local (`threading.Lock`); content CAS semantics untouched.
- No commit/push/merge; worktree HEAD is still `060071ab`. Main `D:/Atlas` was not edited except required evidence files under `tasks/dsh-parity/zcode-glm-20261118/evidence/`.