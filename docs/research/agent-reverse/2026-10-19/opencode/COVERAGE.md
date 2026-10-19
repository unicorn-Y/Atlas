# Coverage and completion gates (OpenCode v2.0.32)

Status: **WORK IN PROGRESS**. This checkpoint accounts for the shipped application inventory and closes a synthetic HTTP session/inbox persistence path plus a mock-provider Agent/tool/subagent turn. It does not claim semantic coverage of every code asset, hosted-model behavior, or crash recovery.

## G0 — physical identity: PASS for requested artifacts

See `evidence-extracted/PACKAGE-ARTIFACTS.md`. The cached source and release bytes were re-hashed before this continuation; v2 source commit is `843a6c514e606b436a7fe713422ace0a93ad3d61`, v1 is `60c9be092129745688bb3c3a752affc6cbd66ede`. The shipped desktop ASAR is 176,346,919 bytes and includes 8,307 files. Desktop, CLI sidecar and standalone Windows CLI all report v2.0.32. Desktop and npm binary have equal reported sizes but different hashes; their relation beyond shared version/size remains unknown.

## G1 — executable code coverage: PARTIAL, inventory complete

Inventory from extracted `resources/app.asar` (`D:\agent-client-staging\opencode-zcode\OpenCode\desktop\v2.0.32\extracted-installer\application\resources\app.asar.extracted`):

| Bundle group | Files | Bytes | Static semantic status |
|---|---:|---:|---|
| `out/main/**` and other `out` host code | included in total | included in total | Entry and selected bundles traced; full symbol/IPC registry enumeration remains open |
| `out/renderer/**` | included in total | included in total | Main renderer bundle anchors inspected; full component/action registry remains open |
| `node_modules/**` shipped JS/TS | included in total | included in total | Third-party/runtime code indexed; not all vendor modules semantically read |
| all `.js` | 6,599 | 65,960,775 | Enumerated; REA whole-ASAR graph timed out; per-bundle AST/symbol pass open |
| all `.ts` | 487 | 3,515,579 | Enumerated; focused source/bundle linkage only |
| all `.cjs` | 102 | 1,217,911 | Enumerated; semantic scan open |
| all `.mjs` | 43 | 689,522 | Enumerated; semantic scan open |
| all `.tsx` | 15 | 43,490 | Enumerated; semantic scan open |
| all `.html` | 6 | 31,844 | Enumerated; entry/resource scan open |
| non-code resources | remaining inventory | indexed in extraction manifest | Classified only; icons/fonts/locales/wasm/media are not semantic code coverage |

Total executable/script/HTML files: **7,252**. Overall inventory: **8,307 files**. Top-level extracted split: `out` 2,497 files / 95,458,095 bytes; `node_modules` 5,751 / 77,822,460 bytes; `resources` 58 / 2,562,142 bytes; root `package.json` 836 bytes. Counts are disjoint top-level groups; extension counts include each file exactly once. The earlier REA ASAR analysis failure was caused first by the isolated `OpenConsole.exe` integrity mismatch and then by a 300-second analyzer timeout; the latter is not treated as a blocker. Continue by chunk and directory; inspect only the mismatching resource under a separate integrity record.

REA per-directory syntax batches (separate from semantic code review): `out/main` parsed 645/645 JavaScript files (2,677,049 bytes; 566,679 AST nodes; 2,340 findings; zero parse failures). `out/renderer` parsed 1,648/1,648 JavaScript files (36,535,169 bytes; 2,942,342 AST nodes; 7,136 findings; zero parse failures). The renderer batch returned partial/truncated semantic relationships due to analyzer result budget (430 call-flow, 15,456 data-flow, 8,776 object-flow relations retained; 2,974 limitations); this is explicit analyzer incompleteness, not a parse failure. Exact REA evidence IDs are indexed in `EVIDENCE-INDEX.md`. Subsequent isolated batches cover the behavior-bearing renderer entry, desktop main, and browser host assets, but the remaining main/extension/feature chunks still require segmentation and review.

One-file actionable renderer bundle batch (`out/renderer/assets/main-CZyBNj5O.js`, copied byte-for-byte into an isolated analysis directory) parsed successfully: 1 file, 1,321,667 B, 363,244 AST nodes, 1,202 findings, zero parse failures; semantic relations remained partial/empty under the 90 s/1 GiB analyzer profile. Isolated desktop `desktop-CiR2Cmvk.js` parsed 1/1 (189,882 B, 53,488 AST nodes, 23 findings, zero parse failures; REA saw one BrowserWindow construction and two explicit webPreferences shapes, while semantic relations were partial/empty). Isolated Browser host `host-R1JTLSvD.js` parsed 1/1 (65,932 B, 15,208 AST nodes, 738 findings, zero parse failures; 431 call-flow, 6,497 data-flow, 669 object-flow, and 125 promise-ownership relations retained, with unresolved relationships preserved as unknowns). These results establish per-chunk syntax analysis, not full relationship closure. Continue with other behavior-bearing main/extension chunks and use source/bundle byte-string anchors where graph extraction stays incomplete.

Main shipped anchors from the ASAR: `out/main/index.js` (819,133 B; SHA256 `a43fc9bd7ce7e27cc215d1f1b630087a93b4e7b889075860ae6864c76429c9fc`), `out/main/desktop-CiR2Cmvk.js` (189,882 B), `out/main/host-R1JTLSvD.js` (65,932 B), `out/main/main-CFnF_jTV.js` (16,371 B), `out/main/pane-bxT5y0e5.js` (81,715 B), `out/renderer/assets/main-CZyBNj5O.js` (1,321,667 B), and `out/renderer/assets/model-CFhkIZEf.js` (11,089 B). These are entry/feature anchors, not the full 7,252-file semantic pass.

## G2 — surface and lifecycle trace: PARTIAL

`SURFACE-MAP.tsv` currently covers the renderer MessagePort RPC contract, extension subscription, app composer queue to server prompt endpoint, persistent inbox schema, and interrupt/restart implementation. Remaining surface enumeration includes all UI menus/commands/routes, all desktop IPC RPC groups, all server events in both directions, and feature-gated registration sites.

## G3 — agent semantics: PARTIAL

Source links in `IMPLEMENTATION-TRACE.md` describe admission, execution claims, LLM/tool step, background subagent job, and recovery. Exact model/tool execution order and error paths are source-supported. A synthetic local provider completed a packaged CLI parent→child→read-tool turn (G4 R3); hosted-model behavior, background Job crash recovery, and interrupted active-turn recovery remain unobserved.

## G4 — local execution: PARTIAL

R1: exact shipped Electron app started under REA; window title `OpenCode`, URL `oc://renderer/index.html`, visible=true, Electron 44.4.5, 12 s startup observation. REA hook coverage failed as `hook_conflict`; no IPC was captured. Initial cleanup was uncertain; a process-list check found none of captured PIDs remaining. Do not infer clicks or runtime IPC from the visible window.

R2: exact standalone v2.0.32 CLI sidecar served HTTP only on `127.0.0.1:49374` from `D:\temp\opencode-g4\workspace` with synthetic Basic credentials and scratch HOME/USERPROFILE/APPDATA/LOCALAPPDATA/config. `POST /api/session` created synthetic session `ses_ead18d81effeAC5SgVijWCTnnY`; `POST /api/session/{id}/prompt` with `resume:false` returned an admitted `queue` inbox item; `GET /api/session/{id}/inbox` returned it. The server was stopped and restarted against the same scratch HOME; the same inbox ID and text remained visible and SQLite `opencode.db` grew to 6,799,360 bytes. No model provider was configured for this run; `resume:false` explicitly prevented model dispatch. This verifies local HTTP API + persistence/reopen, not an Agent turn, model, tool, or execution cold recovery.

R3: the exact CLI then ran an isolated parent turn against a synthetic HTTP/SSE OpenAI-compatible provider bound to loopback `127.0.0.1:49375`; the fake provider emitted a `subagent` tool call, the `explore` child made a built-in `read` tool call on `D:\temp\opencode-g4\workspace\proof.txt`, then child and parent completed. Parent session `ses_ead0b8494ffePjK25w7AvAvC5Z` links child `ses_ead0b80f6ffe3q2t7zVuvxgEx4` (`parentID` matches); the parent tool record is completed, child `read` is completed and returned synthetic file text `SYNTHETIC-READ-TOOL-RESULT-73`, child and parent outcomes are `succeeded`, and final assistant content is `SYNTHETIC-TOOL-CHAIN-OK`. The server made exactly four logged `/v1/chat/completions` requests to the local provider (one parent planning request, two child requests around the read tool, and one parent completion request); the provider stub logs only method/path/model/byte count and stores no request body. This is a real packaged Agent/tool/subagent execution with deterministic mock model responses—not a real hosted-model run. No non-loopback provider was configured; both listeners were stopped after capture. Reproduction helper: `evidence-extracted/runtime/mock-openai-provider.ps1` plus scratch config described in `FINISH-GATES.md`.

## G5 — Atlas comparison: PARTIAL

The prior `ATLAS-GAP.md` is anchored to Atlas `main@aa6196f550098cc46081dc6db2c376cb87ddffa5`. The new gate-specific backlog is not yet complete; finish source-to-source paths for composer, tool approval/result events, child session, background task, and restart before prioritization.

## G6 — evidence packet: PARTIAL

Existing evidence is in `EVIDENCE-INDEX.md` and `evidence-extracted/`. The five required gate artifacts are present as of this checkpoint; `FINISH-GATES.md` keeps unclosed gates explicit. Runtime observations here are synthetic and isolated. No personal config, keys, or user sessions were used.

## G7 — stop condition: OPEN

This is a checkpoint only. Do not mark complete while code-semantic enumeration, UI action closure, model/tool/subagent execution, desktop IPC capture, or Atlas backlog evidence remain incomplete.
