# ZCode 3.15.3 coverage ledger (checkpoint, WIP)

## Artifact identity and method

The selected installer is the 181,367,144-byte Windows x64 ZCode 3.15.3 release asset, SHA-256 `bc8100ba4377256fbe1531d549b4775f18e3ba21768b6294ca50751cd461faca`. Its retained `resources/app.asar` is 340,516,766 bytes, SHA-256 `3fb4104ddcd79e9808eede75192299a22057bd9c336e15b9c2bb1825b4120283`. The embedded runtime CJS is 15,127,039 bytes, SHA-256 `31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54`. Release asset identity is cross-checked in `extracted-3153/ASSET-HASHES.txt`.

The ASAR header was inventoried with `@electron/asar` from the exact local archive, and its JS-family files were extracted in memory one at a time and parsed with Acorn 8.16.0. No app code was executed for this static pass. Code here means files ending in `.js`, `.cjs`, `.mjs`, `.ts`, `.cts`, `.mts`, `.jsx`, `.tsx`, or `.html`; declarations, tests, postinstall scripts, source snippets, and package dependencies remain included in counts where they carry those suffixes.

## Inventory and parser coverage

| Package area | Inventory | Parsed/inspected | Result |
|---|---:|---:|---|
| Complete ASAR | 27,856 file entries; 22,902 JS/TS/HTML-family files; 274,190,048 bytes for that suffix set | 18,943 `.js/.cjs/.mjs` entries attempted from ASAR; 18,936 parsed | 7 parser failures and 2 non-file aliases are itemized below; TypeScript-family and HTML entries are inventoried but not TypeScript-parsed |
| `out/main` | 22 JS files, 2,080,867 bytes | 22/22 | Acorn parse success; REA evidence view `ev_b48ea35577ef69b96dec6ae5d732e98e72abd9c097e22cea6e9b9c2855129e7c`; REA semantic relations partial/truncated |
| `out/host` | 18 JS files, 2,985,871 bytes | 18/18 | Acorn parse success; REA evidence view `ev_7f0b59b9fbb70743ecaa18d8dc8c6de7e408180b77dadc7a17a0fd7bea35799f`; semantic relations partial/truncated |
| `out/preload` | 8 JS/CJS files, 5,129,447 bytes | 8/8 | Acorn parse success; no REA semantic graph yet |
| `out/scheduler` | 3 JS files, 1,048,326 bytes | 3/3 | Acorn parse success; REA evidence view `ev_d89be61cdcd988ea604688441526ccf4d64a5d0b5df0580406ed7395dafcc221`; semantic relations partial/truncated |
| `out/plugin-sandbox` | 7 JS files, 2,191,878 bytes | 7/7 | Acorn parse success; REA evidence view `ev_420285686f1ecb83efb2e40f3fd7e143cee3d1ca323d51aaa2c8c6d71f767c10`; semantic relations partial/truncated |
| `out/renderer` | 2,736 JS files, 38,367,669 bytes | 2,736/2,736 | Acorn parse success; 2,735 are under `assets/`; no complete route/action graph yet |
| Embedded `resources/glm/zcode.cjs` | 1 CJS, 15,127,039 bytes | 1/1 | Acorn parse success and AST counts in `extracted-3153/CJS-MODULE-INDEX.tsv`; REA scan of `resources/glm` has partial semantic coverage |

All 2,794 JS/CJS/MJS entries in the extracted `out/` tree parsed successfully (51,804,058 bytes). The top-level ASAR also contains 18,945 apparent `.js/.cjs/.mjs` paths; the 2 extra entries are `node_modules\\chart.js` and `node_modules\\highlight.js`, which `@electron/asar.extractFile` identifies as directory/link aliases. Seven real files were not accepted by Acorn's module-then-script parse: `has-symbols/test/shams/{core-js.js,get-own-property-symbols.js}`, `has-tostringtag/test/shams/{core-js.js,get-own-property-symbols.js}`, `protobufjs/scripts/postinstall.js` (top-level `return`), `node-domexception/.history/index_20210527213843.js` (historical fragment), and `tiny-invariant/src/tiny-invariant.flow.js` (Flow syntax). These are not silently counted as parsed. No alternate Flow parser or wrapper extraction has yet been applied.

Renderer asset classification is currently mechanical: 2,735 JS assets (37,321,455 bytes), 2,022 files <=1 KiB, 285 between 1–10 KiB, 376 between 10–100 KiB, and 52 >100 KiB. The largest include UI-heavy styles (6,475,933 bytes), office previews/XLSX renderer, code-editor language bundles/workers, diagrams, PDF.js, syntax highlighters, and workspace UI chunks. This grouping does not yet identify every route/action owner. The primary `renderer/index.html` declares one module entry and 300 modulepreloads. Passive live CDP observed one `index.html` page, 1,491 DOM nodes, and 307 loaded JS scripts at the time of observation (Evidence `ev_dc5735b0dfdda2f1527d9551626b2ed373b9d12085b6a5b4ce9474316277f966`). This is one runtime state, not complete static renderer coverage.

## ASAR integrity discrepancy

The prior whole-application REA report identified the unpacked entry `node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node`. I independently inspected the ASAR header entry and the corresponding retained file:

| Entry | ASAR declaration | Retained `.asar.unpacked` file | Finding |
|---|---|---|---|
| `node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node` | 134,656 bytes; SHA-256 `879dd94cfc79f1e263a00077597ae9448a5394b7d193381aaa50d992a1f91090` | 146,840 bytes; SHA-256 `d7acf2441dc6e39cfe0838cb87b3c54595624afdad7d1e42be9740016639becc` | Confirmed mismatch; no executable behavior is attributed to this native file |
| `node_modules/node-pty/prebuilds/win32-x64/pty.node` | 303,104 bytes; SHA-256 `ae323edd0835ee7b9e18cc96a7b2bb4b8173ff768317d178af2788406feb71ff` | 315,288 bytes; SHA-256 `6bd6fb6cefd46ed90a85187bdaae82bf7b9f3018c2d54453215bdceee03e4d66c` | A second mismatch in the same unpacked native family |

This contradicts the retained unpacked native companions, not the packed `out/` JavaScript parse results. Static UI/host/runtime findings are bounded to the verified bytes read from `app.asar`/the retained `out` tree. Terminal/PTY runtime claims are not made. Strict whole-application integrity remains **PARTIAL** until unpacked companions are reconciled against a trusted matching extraction; replacing bytes or retrying installer execution is out of scope.

## Group coverage still open

* Enumerate and label all 22,902 code-family entries by production/dependency/test/declaration/sample/generated resource and link their importing owner where feasible.
* Parse the seven parser failures with a compatible parser or record a narrowly reproducible parser incompatibility; distinguish test-only/source-only modules from reachable runtime code.
* Complete renderer route/action inventory across the 2,735 asset chunks and map the 300 static preloads to lazy/dynamic imports.
* Verify every retained extracted file against ASAR header metadata; the source extraction tree is not a substitute for entry-by-entry integrity evidence.
* Read/parse the eight preload bundles' exposed API inventory and connect each exposed member to caller and handler.
* Main/host/scheduler/plugin-sandbox REA inventories parsed all files in each selected directory, but their semantic graphs are partial/truncated and do not establish all call paths.

Coverage status: **WIP**, not whole-package completion.
