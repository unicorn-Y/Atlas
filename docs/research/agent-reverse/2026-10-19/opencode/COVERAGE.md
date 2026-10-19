# Coverage and completion gates (OpenCode v2.0.32)

Status: **WORK IN PROGRESS**. This checkpoint accounts for the shipped application inventory and closes one synthetic HTTP session/inbox persistence path. It does not claim semantic coverage of every code asset or a completed model/tool turn.

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

Main shipped anchors from the ASAR: `out/main/index.js` (819,133 B; SHA256 `a43fc9bd7ce7e27cc215d1f1b630087a93b4e7b889075860ae6864c76429c9fc`), `out/main/desktop-CiR2Cmvk.js` (189,882 B), `out/main/host-R1JTLSvD.js` (65,932 B), `out/main/main-CFnF_jTV.js` (16,371 B), `out/main/pane-bxT5y0e5.js` (81,715 B), `out/renderer/assets/main-CZyBNj5O.js` (1,321,667 B), and `out/renderer/assets/model-CFhkIZEf.js` (11,089 B). These are entry/feature anchors, not the full 7,252-file semantic pass.

## G2 — surface and lifecycle trace: PARTIAL

`SURFACE-MAP.tsv` currently covers the renderer MessagePort RPC contract, extension subscription, app composer queue to server prompt endpoint, persistent inbox schema, and interrupt/restart implementation. Remaining surface enumeration includes all UI menus/commands/routes, all desktop IPC RPC groups, all server events in both directions, and feature-gated registration sites.

## G3 — agent semantics: PARTIAL

Source links in `IMPLEMENTATION-TRACE.md` describe admission, execution claims, LLM/tool step, background subagent job, and recovery. Exact model/tool execution order and error paths are source-supported. CLI real-model/tool execution and interrupted active-turn recovery remain unobserved.

## G4 — local execution: PARTIAL

R1: exact shipped Electron app started under REA; window title `OpenCode`, URL `oc://renderer/index.html`, visible=true, Electron 44.4.5, 12 s startup observation. REA hook coverage failed as `hook_conflict`; no IPC was captured. Initial cleanup was uncertain; a process-list check found none of captured PIDs remaining. Do not infer clicks or runtime IPC from the visible window.

R2: exact standalone v2.0.32 CLI sidecar served HTTP only on `127.0.0.1:49374` from `D:\temp\opencode-g4\workspace` with synthetic Basic credentials and scratch HOME/USERPROFILE/APPDATA/LOCALAPPDATA/config. `POST /api/session` created synthetic session `ses_ead18d81effeAC5SgVijWCTnnY`; `POST /api/session/{id}/prompt` with `resume:false` returned an admitted `queue` inbox item; `GET /api/session/{id}/inbox` returned it. The server was stopped and restarted against the same scratch HOME; the same inbox ID and text remained visible and SQLite `opencode.db` grew to 6,799,360 bytes. No model provider was configured for this run; `resume:false` explicitly prevented model dispatch. This verifies local HTTP API + persistence/reopen, not an Agent turn, model, tool, or execution cold recovery.

## G5 — Atlas comparison: PARTIAL

The prior `ATLAS-GAP.md` is anchored to Atlas `main@aa6196f550098cc46081dc6db2c376cb87ddffa5`. The new gate-specific backlog is not yet complete; finish source-to-source paths for composer, tool approval/result events, child session, background task, and restart before prioritization.

## G6 — evidence packet: PARTIAL

Existing evidence is in `EVIDENCE-INDEX.md` and `evidence-extracted/`. The five required gate artifacts are present as of this checkpoint; `FINISH-GATES.md` keeps unclosed gates explicit. Runtime observations here are synthetic and isolated. No personal config, keys, or user sessions were used.

## G7 — stop condition: OPEN

This is a checkpoint only. Do not mark complete while code-semantic enumeration, UI action closure, model/tool/subagent execution, desktop IPC capture, or Atlas backlog evidence remain incomplete.
