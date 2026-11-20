# PAR-07-B — keybindings client CAS path + 409 conflict UI (worker B)

- Date: 2026-11-19
- Worktree: `D:/Atlas/.worktrees/zcode-exec06-keybindings-cas`
- Branch: `zcode/exec06-keybindings-cas`
- Baseline/HEAD: `060071ab2ecf86d41cab90e98160183ce126bc69` (060071ab), unchanged; no commit/push/merge performed.
- Scope: end-to-end renderer path for `keybindings.json` content-revision CAS, 409 reload/retry UI, client/service regressions. Electron main untouched. Only this receipt file written outside the worktree.
- Pre-existing in worktree (not authored this pass): `core/atlas/api/u6_router.py` GET revision / PUT `expected_revision` / atomic write, and its initial `core/tests/test_u6_keybindings.py`. Main HEAD is also `060071ab`; this file was clean in main.

## 1. Product contract read (worktree + read-only main)

The baseline product file did exist in both trees and was byte-identical (`diff` exit 0), so no copy into the worktree was needed.

- `frontend/src/renderer/pages/ShortcutsPanel.tsx` (worktree and main, baseline): saves via `saveBindings(next)` to localStorage, then `PUT /api/u6/keybindings` with `json: { bindings: next }` — no `expected_revision`. This is the actual product contract at baseline (the task's "current ShortcutsPanel PUTs without expected_revision" is accurate).
- `frontend/src/renderer/App.tsx:560-570` still polls GET every 3s and compares `updated_at`; it ignores the new `revision` field. Not touched because main has an unrelated in-flight modification to this file (`frontend/src/renderer/App.tsx` is `M` in main; target keybindings files are clean).
- `frontend/src/renderer/services/shortcuts.ts` continues to own `localStorage['atlas.shortcuts']`, including the legacy single-string format.
- Backend `core/atlas/api/u6_router.py`: GET returns `bindings`, `updated_at`, content sha256 `revision` (null when the file is absent); PUT accepts `expected_revision` (null = create, mismatch = 409, omitted = legacy/unconditional), writes temp + fsync + chmod + `os.replace`.

Boundary decision: local rebinds win over the file on mount, because older builds can have preferences only in localStorage. The file is adopted only when this machine has no rebinds of its own; `keybindings.json` remains the cross-device source of truth once saves happen.

## 2. Files changed (worktree-relative)

New:

| File | Change |
|---|---|
| `frontend/src/renderer/services/keybindings.ts` | 171 lines: response normalization (incl. legacy payloads without `revision`), HTTP transport that always PUTs `{bindings, expected_revision}`, 409 → `KeybindingsConflictError`, serialized `KeybindingsSync` with read/adopt-revision, first-create null, refresh and explicit retry. |
| `frontend/src/renderer/services/keybindings.test.ts` | 167 lines, 5 tests: two same-revision writers, refresh-then-retry, first create null, legacy document read, HTTP body/409 mapping. |
| `frontend/src/renderer/pages/ShortcutsPanel.test.tsx` | 131 lines, 2 tests: 409 keeps local edit and reload adopts winner; retry re-reads revision then saves pending local edit. |

Modified:

| File | Change |
|---|---|
| `frontend/src/renderer/pages/ShortcutsPanel.tsx` | +77/−3: mount GET revision; adopt file only when local cache has no rebinds; save through `KeybindingsSync`; conflict banner with `重新加载` and `用本机改动重试保存`; edits blocked while conflicted. |
| `frontend/src/renderer/services/shortcuts.test.ts` | +17/−1: legacy single-string localStorage cache read test. |
| `core/tests/test_u6_keybindings.py` | initial file from prior pass; this pass added `hashlib` import and `test_legacy_keybindings_file_stays_readable_and_updatable` (old action→array file is read, hash matches bytes, CAS PUT succeeds). |

`git diff --stat` for tracked files: **4 files, +322/−19** (includes the pre-existing `u6_router.py` change). Untracked new files add 469 lines.

## 3. Behavior implemented

1. **GET then PUT CAS** — panel reads the file revision on mount; every save sends `{bindings, expected_revision}`. A save issued before the mount read completes queues behind it.
2. **Adopt returned revision** — `KeybindingsSync` replaces its stored revision with the PUT response revision, so the next save uses the new baseline.
3. **First create** — a missing file yields revision `null`; PUT sends `expected_revision: null` (asserted in service test and backend test).
4. **Old keybindings.json readable** — the old plain `action -> string[]` file is read with a fresh content revision (backend regression), and the frontend normalizer accepts a legacy GET payload without a `revision` field as a null baseline.
5. **Local preferences/cache preserved** — `saveBindings` still runs immediately; localStorage remains the cache. On mount, non-default local rebinds are not replaced by the file. On conflict, the pending local edit stays in localStorage; reload is an explicit user action. Reload of a missing file keeps local bindings.
6. **409 conflict UX** — `role="alert"` banner shows the server detail, plus two explicit actions:
   - `重新加载`: GET latest, apply its bindings/revision, clear conflict.
   - `用本机改动重试保存`: GET latest revision, then PUT the pending local map with that revision (explicit overwrite chosen by the user). A second 409 re-arms the banner and keeps the pending map.
   While conflicted, further recording edits are refused with a note instead of silently writing.
7. **Serialization** — rapid edits are queued; each save uses the revision returned by the previous save, so a window does not conflict with itself.

## 4. Exact commands, exit codes, counts

Backend:

```
cd D:/Atlas/.worktrees/zcode-exec06-keybindings-cas/core
python -m pytest tests/test_u6_keybindings.py -q -p no:cacheprovider
```

- Python 3.11.16, pytest result: **7 passed**, 5 warnings, **EXIT 0**.
- Tests cover: missing file/null revision; create null + stale create 409; same-baseline writer 409/no overwrite; **legacy file read/update**; invalid shape writes nothing; replace failure keeps old file and cleans temp; malformed file reported/repairable.

Frontend (worktree has no `node_modules`; binaries were run from the read-only main checkout, and Node module resolution walked up to `D:/Atlas/node_modules` because the worktree is under `D:/Atlas/.worktrees`):

```
cd D:/Atlas/.worktrees/zcode-exec06-keybindings-cas/frontend
D:/Atlas/node_modules/.bin/vitest run --root . src/renderer/services/keybindings.test.ts src/renderer/services/shortcuts.test.ts src/renderer/pages/ShortcutsPanel.test.tsx
```

- vitest 5.0.4, Node v24.18.1: **3 files passed, 11 tests passed, EXIT 0**.
- Breakdown: keybindings 5, shortcuts 4, ShortcutsPanel 2.

```
cd D:/Atlas/.worktrees/zcode-exec06-keybindings-cas/frontend
D:/Atlas/node_modules/.bin/vitest run --root .
```

- **83 files passed, 376 tests passed, EXIT 0** (full frontend suite).

```
cd D:/Atlas/.worktrees/zcode-exec06-keybindings-cas
D:/Atlas/node_modules/.bin/tsc -p frontend/tsconfig.renderer.json --noEmit
```

- tsc 7.0.2: no output, **EXIT 0**.

```
cd D:/Atlas/.worktrees/zcode-exec06-keybindings-cas
git diff --check
```

- no whitespace errors, **EXIT 0**.

The required test scenarios map as follows: same-version two clients → `keybindings.test.ts` "rejects the second writer..." + backend `test_stale_revision_is_rejected_and_matching_revision_updates`; refresh then retry → `keybindings.test.ts` "succeeds after refresh..." + `ShortcutsPanel.test.tsx` retry test; first create null → `keybindings.test.ts` + backend `test_create_with_null_revision...`; legacy config read → backend new legacy test + frontend legacy normalization/localStorage tests.

## 5. Product-entry boundary

- Entry component: `frontend/src/renderer/pages/ShortcutsPanel.tsx`, rendered from `App.tsx` settings sheet (`sheet === 'shortcuts'`, around `App.tsx:3622`) with the same props (`apiBaseUrl`, `models`). No route/event/service-injection changes were needed.
- Backend route: `core/atlas/api/u6_router.py` `GET/PUT /api/u6/keybindings`, already mounted by the existing u6 router; no new router registration.
- Electron main process: **untouched**. No preload/IPC/broadcast changes.
- `App.tsx` polling: **untouched** (main has an unrelated in-flight edit). Cross-window updates still arrive through its existing 3s `updated_at` poll, not through broadcast and not within 1s.

## 6. Merge notes

Main HEAD equals this worktree baseline (`060071ab`), and all target paths (`ShortcutsPanel.tsx`, `shortcuts.ts`, `shortcuts.test.ts`, `u6_router.py`, `test_u6_keybindings.py`) are clean in main. The only conflict-free caveat is `frontend/src/renderer/App.tsx`, which main shows as `M` for an unrelated `timelineProjection` change; this pass does not touch it, so no textual conflict is expected. New files must be added explicitly (`keybindings.ts`, `keybindings.test.ts`, `ShortcutsPanel.test.tsx`) when porting the worktree diff. No commit/push was performed.

## 7. Remaining risks / not verified

- **No real two-window Electron run.** Verification is pytest + vitest + `react-test-renderer`; no live dev Electron, no real backend process, no actual dual-window click-through. Per `AGENTS.md`, this is not claimed as "真机真模型" validation.
- **Cross-window latency is still 3s.** `App.tsx` polls `updated_at` every 3s; the acceptance note's "≤1s or broadcast" is not met. Fixing it would require touching the in-flight `App.tsx` (or adding a renderer broadcast), both outside this worker's protected boundary.
- **Corrupt `keybindings.json` cannot be repaired from the new UI.** GET returns 422, so the client has no revision baseline; `expected_revision` CAS cannot open a save path. The backend still supports repair by an old/unconditional PUT (covered by `test_malformed_existing_file_is_reported_but_repairable`), but the new panel will report "文件同步失败". A future explicit "repair/overwrite corrupt file" flow could send an unconditional PUT.
- **Backend lock is process-local** (`threading.Lock`), inherited from the prior backend pass; two separate backend processes writing the same data dir are not serialized by this lock (content CAS still rejects stale revisions).
- **Mount adoption heuristic** is "local rebinds win, defaults adopt file". A user whose local cache is exactly defaults intentionally (after a reset) and whose file is stale will adopt the stale file on panel mount; the explicit reload/retry actions remain available.
- **No live verification of i18n locale strings** for the new banner/note text; the existing `en-US` dictionary does not contain the new Chinese strings, matching the current panel's pattern of untranslated runtime notes.