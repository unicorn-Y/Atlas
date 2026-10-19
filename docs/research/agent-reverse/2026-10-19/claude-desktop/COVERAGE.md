# Claude Desktop 2.42304.0 coverage checkpoint

**Status: WORK IN PROGRESS.** Static scope is the fixed enterprise Windows x64 MSIX and its `app.asar`; no user profile or live application was opened. Locations below refer to exact package paths, not a different Claude Setup build.

## G0 — package identity: PASS (static identity)

The cached Release asset was re-hashed on 2026-10-19: `claude-desktop-x64-2bf309665f.msix`, 297,191,037 bytes, SHA256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`. Its extracted `app/resources/app.asar` is 49,338,428 bytes, SHA256 `8f4d3dec5e4f3ddffb150321060b18807d83a40f3a65618fe4f29325379da9db2`; `cowork-svc.exe` is 13,761,360 bytes, SHA256 `934e5b671813ef3d5684c0ee0d1d18835af74e9ecfb114575e0d8fdbb663ba8f`. All values match existing `evidence/README.md` and manifest. Appx identity is Claude x64 2.42304.0.0, entry `app\Claude.exe`, `Windows.FullTrustApplication` (`evidence/identity.json`). The ASAR package main is `.vite/build/index.pre.js`; main BrowserWindow preload is `.vite/build/mainView.js` (see `evidence/trace-snippets/renderer-ipc.md`).

This is the enterprise package. The consumer installer/consumer MSIX is still unavailable; enterprise/consumer and account-rollout equivalence remain U. The legacy `D:\_claude_desktop` Setup extraction is a different 0.14.10 artifact and is excluded from matched-version conclusions.

## G1 — shipped-code inventory and parser coverage: PARTIAL

The exact ASAR path index contains 548 entries (`evidence/asar-tree.txt`). The fixed package REA pass examined 452 relevant files and 40,616,215 text bytes; it parsed 437 JavaScript-bearing files, visited 9,550,272 AST nodes, and reported zero parse failures. Analysis recorded 15 BrowserWindow constructions, 41 explicit web preferences, 52 contextBridge exposures / 16 exposed members, 3 utility-process constructions, and 1,535 IPC operations. Semantic results were **partial/truncated**, not a complete application graph.

Independent filesystem inventory of the previously extracted exact ASAR payload under `.vite/` and package resources found 505 files / 76,219,698 bytes total, including 431 `.js` (30,790,879 bytes), 4 `.mjs` (8,804,193 bytes), 16 `.css` (339,382 bytes), 6 `.html` (1,003,745 bytes), 6 `.skill` (529,810 bytes), 3 `.jsc` (6,870,280 bytes), and 3 `.node` (833,520 bytes). Remaining files are runtime libraries, JSON/config, docs, fonts and assets. Inventory and parser units differ (archive paths, extracted resources, JS-bearing parser inputs); do not add or equate these counts.

| Executable/code group | Observed inventory | Analysis / entry relation | State |
|---|---:|---|---|
| `.vite/build/**` host, main chunks, workers and runtime bundles | 380 code-like assets / 23,527,553 bytes | 437 parsed JS-bearing files include host code; main entry imports/load graph is not fully enumerated | PARTIAL; symbol and registration scan is continuing |
| `.vite/renderer/**` UI pages/chunks | 38 code-like assets / 4,558,512 bytes | UI roots include main, quick, buddy, about, find-in-page and local-exec-consent; main UI includes `main-9C0encc1.js`, `attachReactWithSelector-Bf7MO2XB.js`, `MainWindowPage-BM1J3SeB.js`, `clawdQuestEngine-CdvdlRdl.js` | PARTIAL; all chunks are inventoried, routes/actions are not all paired |
| packaged `node_modules/**` JS dependencies | present in parser inventory; exact submodule totals are in ASAR listing | Third-party code has no complete capability interpretation in this checkpoint | PARTIAL |
| `.jsc` compile-cache payloads | 3 / 6,870,280 bytes | Not source-parsed; compile cache is not treated as a source map or complete code substitute | U |
| `.node` native addons / `.dll` / executables | 3 `.node`, one 3,261,536-byte `.dll`, host/service executables are separately indexed | PE and selected service identity inspected; native addon binding resolution and all native behavior not mapped | PARTIAL/U |
| HTML/CSS/skills/config/resources | 6 HTML, 16 CSS, 6 skills, JSON plus locale/media | Counted/classified; not each asset semantically interpreted | PARTIAL |

Analysis mechanics: REA full-ASAR parsing completed within the selected worker limits without JS syntax failures. The application semantic graph then hit a 100,000-node ceiling and 0-byte semantic result budget, with dynamic channel generation dominating; this explains why global graphing did not close route/action or IPC pairs. Per-file/per-chunk analysis is the active fallback. No source map files were indexed. `evidence/summary-counts.tsv`, `asar-tree.txt`, and `msix-tree.tsv` retain the machine-readable baseline.

Focused fallback: copied only the exact `coworkArtifact.js`, `mainView.js`, and 7,081,117-byte `index.chunk-lzaSYO3Q.js` into a temporary analysis directory, then parsed those three files independently. The parser completed all 3 files / 7,255,080 bytes with 0 parse failures and recovered 442 call-flow, 3,848 closure, 16,659 data-flow, and 515 object-flow relations; semantic graph still reached its 100,000-node ceiling and retained 7,446 unknowns. Dynamic IPC expressions remain expressly unresolved, so this improves local module coverage without falsely closing the IPC inventory.

Renderer entrypoint scan: six HTML roots are present (`main_window`, `quick_window`, `buddy_window`, `about_window`, `find_in_page`, `local_exec_consent`). Main window HTML loads `main-9C0encc1.js`, which lazy-loads `MainWindowPage-BM1J3SeB.js` and `attachReactWithSelector-Bf7MO2XB.js`; that page chunk references `react-intl-CW2bLHOS.js` and `clawdQuestEngine-CdvdlRdl.js`. A bounded literal slash-path scan of these renderer pages found only the managed-settings path, but this is not proof that all app routes are absent: most code is chunked/generated and route/action classification remains open.

## G2 surface sampling from observed code

The concrete artifact scheduled-task surface is closed through main-side scheduling, not through a claimed model turn: UI authoring instruction → `window.cowork.runScheduledTask` → generated `CoworkArtifactBridge_$_runScheduledTask` invoke → top-frame `cowork-artifact:` guard → rollout/permission/visibility/task/enabled/user-gesture checks → scheduler `runNow(..., {personStarted:true})` → returned session ID/error. See `END-TO-END-TRACES.md`, `evidence/module-traces.md`, and `evidence/trace-snippets/renderer-ipc.md`.

Generated IPC, all renderer route/action/state joins, and core agent turn/message persistence remain incomplete. This example does not stand in for the primary chat send path or establish generic Cowork execution ownership.

## G3–G6 status snapshot

G3 PARTIAL: app-side named-pipe JSON RPC plus legacy VM status/event vocabulary are mapped; complete Go handler semantics, task/session persistence, child-agent lifecycle, and cold recovery are not. G4 BLOCKED: REA provider-owned Electron capture failed with `Transport closed`. A local launch of the extracted `Claude.exe` with explicit disposable `--user-data-dir` and isolated APPDATA/LOCALAPPDATA/TEMP exited with code 1, no window, and no temp profile files; no crash event with a Claude entry was found in the recent Application log. No cause was established, no login occurred, and no existing session was inspected. The exact package is not registered for the current user (`Get-AppxPackage -Name '*Claude*'` returned no package); do not infer that registration alone would permit login-free UI access. G5 PARTIAL: `origin/main` SHA `aa6196f550098cc46081dc6db2c376cb87ddffa5` is confirmed, but related Atlas anchors need to be tied to each newly enumerated surface. G6 PARTIAL: prior ledger and evidence indexes exist; this checkpoint adds structured supplemental maps and must not be treated as final acceptance.

