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

## 3.15.1 source comparison

The prior lane source reports and source tree are explicitly version 3.15.1. They establish older source-level feature descriptions, but they are not a line-by-line source map for this 3.15.3 CJS: no source map was found in the retained release collection, and the 3.15.3 bundle is webpack-wrapped/minified. Therefore semantic resemblance is a lead, not version equivalence. Source-path correlations remain `UNKNOWN` until same-version desktop bundles or a reliable embedded source map is recovered.

## Open work

The 3.15.3 desktop ASAR main/renderer/preload modules have not been recovered into a trusted module graph. Strict REA validation reported a mismatch between declared integrity and the unpacked `node-pty` companion; a record-and-continue whole-app analysis timed out. Do not infer desktop IPC or UI wiring from the CLI runtime bundle. The installer and runtime were not executed.
