# G0–G7 completion gates — ZCode lane

Status as of this checkpoint: **WORK IN PROGRESS**. No gate is represented as finally accepted solely because a checkpoint has been pushed.

| Gate | Status | Evidence and remaining condition |
|---|---|---|
| G0 Physical identity | PARTIAL | Exact 3.15.3 installer, app.asar and embedded CJS identity are recorded. Exact local app startup/page correlation observed. 3.15.1 source snapshot remains distinct. Unpacked node-pty companion integrity mismatch confirmed; full extracted-file-to-ASAR integrity reconciliation remains open. |
| G1 Executable code coverage | PARTIAL | ASAR has 27,856 file entries and 22,902 JS/TS/HTML-family entries. Acorn parsed 18,936/18,943 packaged JS/CJS/MJS files; 7 parser failures and 2 directory/link aliases are itemized. All 2,794 `out/` code files parse. TypeScript files, HTML routes, all registries, renderer action map, dependency reachability, and source-to-bundle integrity are not fully analyzed. |
| G2 UI ↔ RPC ↔ Host/Agent ↔ event/state chain | PARTIAL | Main→Host and main→renderer MessagePort setup plus renderer reload reattachment are statically mapped; Host MCP UI/app-tool facade callers, main schemas/registry, sandbox protocol, and renderer app-tool event consumer are mapped. App-tool event producer, renderer mount/consent/forwarding, Host provider handlers, model tool injection/result return remain U. Main task/chat/subagent UI-to-runtime subscription is not closed. |
| G3 Agent core semantics | PARTIAL | CJS contains tool schedule/execute, pending tool persistence helper, background registry/detach, workflow journal/replay anchors. Static evidence does not establish exact UI event mapping, service route, cold restart recovery, or all failures/retries. |
| G4 Local execution | PARTIAL / unsafe to continue with current launch method | Startup and local page were observed; no Agent turn, model request, tool, subagent or pause/restart flow executed. Child command lines used the default user-data directory despite requested isolated flag; app and children were stopped. Do not relaunch until every child path is proven isolated. |
| G5 Atlas comparison | PARTIAL | Atlas `origin/main` SHA pinned to `aa6196f550098cc46081dc6db2c376cb87ddffa5`; implementation backlog adds concrete comparisons. Per-mechanism frontend→adapter→engine audit for the new MCP App/tool/task mechanisms remains open. |
| G6 Evidence package | PARTIAL | Added this gate report, `COVERAGE.md`, `SURFACE-MAP.tsv`, `END-TO-END-TRACES.md`, and `ATLAS-IMPLEMENTATION-BACKLOG.md`; existing core reports are being updated. Evidence classes S/R/U are separated. Peer independent review remains outstanding. |
| G7 Stop rule | WIP | Continue static module-by-module analysis and 3.15.1↔3.15.3 anchor comparison. No completion claim is permitted while local code, UI actions, MCP App result chain or safe test path remain investigable. |

## Explicit unknowns still locally actionable

1. Enumerate renderer routes, actions, IPC/service event subscriptions and lazy-loaded chunks, including mapping all 300 HTML module preloads and the rest of 2,735 renderer assets.
2. Trace `pluginUi.appToolCall` producer to the host RPC/service and follow claim/resolve to the model-visible result; find the renderer mount/forwarding path. Static Main→Host→renderer ServicePort transfer and Host caller methods are now located, but do not close this producer/result chain.
3. Resolve ASAR header mismatch scope and verify extracted `out` hashes against the exact ASAR entries using a reproducible per-entry script.
4. Compare more 3.15.1 source symbols/schema fields with same-version 3.15.3 bundles; current name/route matches are not source equivalence.
5. Inspect all 8 preload files and close task/subagent UI subscription/lifecycle paths.
6. G4 may remain unexecuted if no isolated launch mechanism can be proved; the current `--user-data-dir` command is not sufficient.

The two unpacked native file mismatches and unavailable remote account/model behavior are bounded external/runtime facts, but they do not block independent static investigation of packed JS, host RPC schemas, or renderer bundles. Status is **WIP**, not `RESEARCH COMPLETE WITH EXTERNAL LIMITS`.
