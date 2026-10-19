# Runtime comparison anchors: ZCode 3.15.3 CJS vs 3.15.1 source

## Version and evidence boundary

The runtime artifact analyzed here is the SHA-verified 3.15.3 CommonJS bundle `zcode.cjs` (`31965ce1...f506a54`). The available source archive is a distinct 3.15.1 snapshot at commit `aac4755666d09fdcd70272fcf063c077a639015f`. Do not attribute a 3.15.1 symbol/path to the 3.15.3 bundle unless a same-version desktop artifact directly establishes it. The CJS parsed successfully using packaged Acorn 8.16.0; offsets below are UTF-8 byte offsets in the verified CJS bytes, not Acorn UTF-16 code-unit offsets.

## Same-version 3.15.3 package evidence

| Mechanism | 3.15.3 evidence | What it establishes | What it does not establish |
|---|---|---|---|
| Tool lifecycle | `qwt` 13,205,979–13,210,657 emits `tool_queued` around 13,207,831 then calls `executeTools` around 13,208,003; `gBe` 13,192,839–13,193,404 persists pending tool parts | Queue/persist/execute ordering is bundled | UI rendering or durable persistence result |
| Background subagent | child runner around 12,715,173 emits `SubagentSpawned`; `backgrounded` handling around 12,716,232 detaches parent while child callbacks remain; background task port around 12,719,281 requests registry backgrounding | Parent detachment and registry-mediated background lifecycle exist in the bundle | Desktop controls, IPC route, or runtime success |
| Task registry | `InMemoryRuntimeTaskRegistry` around 5,042,044–5,044,543; `activeBranchGeneration` near 5,042,191; `requestBackground` near 5,042,679 | In-memory task/waiter and branch-generation state is bundled | Cross-process durability; name indicates memory-only implementation |
| Workflow journal/replay | migration region 1,515,023–1,543,238; `0019_dwf_journal` at 1,540,263; `dwf_run` at 1,540,320; replay helpers 12,513,514–12,524,192 with `InputHashMismatch` at 12,524,144 | Journal schema and replay input-hash logic are bundled | Schema application, DB creation, transaction behavior, or end-to-end replay |
| Model retry | parser `qXr` 4,007,148–4,007,440; diagnostic builder `HB` 4,097,229–4,097,847; retry source classifier `sHs` 4,099,067–4,099,316 | Provider retry headers and structured decision diagnostics are bundled | Association to a specific release-note fix or parallel-agent call site |

## 3.15.1 source comparison: matched / changed / unknown

The prior lane source reports and source tree are explicitly version 3.15.1. They establish older source-level feature descriptions, but are not a line-by-line source map for the 3.15.3 CJS/app.asar: no source map was found in the retained release collection, and the 3.15.3 runtime is webpack-wrapped/minified. Correlation below is therefore deliberately granular.

| Mechanism | Comparison state | 3.15.1 source anchor | 3.15.3 package anchor | Safe conclusion |
|---|---|---|---|---|
| Tool queue/persist/execute vocabulary | **MATCHED anchor names/contracts** | `apps/zcode-cli/packages/core/src/runtime/methods/turn-tools.ts` lines 30–168; `persistPendingToolPart` and `tool_queued` recorded in source report | CJS `qwt` 13,205,979–13,210,657; `gBe` 13,192,839–13,193,404 | Same observable tool queue/persistence terms and order are present; functions are not proven byte-for-byte or control-flow equivalent |
| In-memory task registry / background waiters | **MATCHED named state family** | `apps/zcode-cli/packages/core/src/runtime-task/registry.ts` lines 105–245 | CJS `InMemoryRuntimeTaskRegistry` 5,042,044–5,044,543 | Name and broad responsibility align; full fields, notification rules and race semantics need direct comparison |
| Child detach and task result delivery | **PARTIAL anchor match** | `subagent/runner.ts` lines 110–405; `runtime/methods/subagent-messages.ts` lines 25–107 | CJS child region 12,715,173–12,719,281 | Spawn/background/detach vocabulary exists in the package. The package-to-parent command/re-entry result path is not yet closed |
| Workflow journal/replay | **MATCHED schema/vocabulary; implementation equivalence UNKNOWN** | `dynamic-workflow/src/engine/scheduler.ts` lines 125–289; `engine-resume.ts` lines 17–44; `dwf-journal.ts` lines 1–84 | CJS migration 1,515,023–1,543,238; replay region 12,513,514–12,524,192 | DWF journal/table/input-hash/replay markers align; initialization, transaction and recovery semantics not matched |
| MCP App event and UI | **MATCHED protocol/event anchor; caller/result UNKNOWN** | UI transport/host bridge and desktop sandbox source anchors in EVIDENCE-INDEX entries 021–022 | app.asar renderer `pluginUi.appToolCall` consumer (`parts-1PK4PulD.js` @5,622; `styles-CSpM3qgc.js` @1,044,668); host routes and main registry in `END-TO-END-TRACES.md` | Event/protocol contract and same-version desktop components are visible, but app attachment and model tool result path are not connected |
| Main/host/preload ownership and RPC transport | **3.15.3-only observed structure; 3.15.1 equivalence UNKNOWN** | Source host/sandbox files listed in EVIDENCE-INDEX entries 001, 021–022 | `DESKTOP-IPC-ANCHORS.md`: typed service facade, remote MessagePort client, narrow plugin preload, instance registry | Current release packages the structure; process caller/port transfer and full exposed preload API still need coverage |
| Renderer route/action map | **UNKNOWN** | 3.15.1 UI source was reviewed but no same-version source map binds route modules | `COVERAGE.md`: 2,736 renderer code files; 300 static preloads; 307 live scripts loaded in one page observation | Package asset inventory and one runtime state are not an exhaustive action/route map |

“MATCHED” here means only named byte/schema anchors visible on both sides. There is currently no positive claim of complete semantic equivalence or a proven source-to-bundle function mapping. A “changed” implementation is not asserted because the 3.15.1 source snapshot and 3.15.3 bundles cannot currently be compared with a reliable map; uncorrelated code remains **UNKNOWN**, not implicitly unchanged.

## Open work

The 3.15.3 desktop ASAR was statically inventoried and role-based JS groups were parsed, and one retained app startup reached a local Electron page; details and limitations are in `COVERAGE.md` / `END-TO-END-TRACES.md`. A complete desktop module graph and route/action map remain open. The two unpacked node-pty binary mismatches are independently confirmed; their issue is bounded to those native companions, while exact per-entry integrity checks for retained JS are still incomplete. The launch was stopped when child processes used the default user-data path. No Agent task or runtime CJS execution occurred.
