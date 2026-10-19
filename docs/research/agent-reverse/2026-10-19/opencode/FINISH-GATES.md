# FINISH-GATES — OpenCode lane

Checkpoint branch `research/agent-reverse-20261019-opencode`. State: **WORK IN PROGRESS**.

| Gate | State | Evidence / remaining condition |
|---|---|---|
| G0 physical identity | PASS | `evidence-extracted/PACKAGE-ARTIFACTS.md`; five exact bytes/SHA; sidecar and npm package identity relation beyond version/size still unknown |
| G1 executable coverage | PARTIAL | `COVERAGE.md` accounts 8,307 extracted files and 7,252 executable/script/HTML files; REA parsed 645 main and 1,648 renderer JS files with zero parse failures, but semantic graphs are partial/truncated. Continue isolated actionable chunks, route/command/event/IPC registry inventory. |
| G2 UI↔IPC↔host↔agent↔state | PARTIAL | `SURFACE-MAP.tsv`, `END-TO-END-TRACES.md`; renderer MessagePort RPC and prompt-to-inbox chain mapped statically, but UI click-to-server request and complete events reverse mapping not runtime-closed. |
| G3 Agent semantics | PARTIAL | execution/retry/tool/subagent/restart source paths recorded; a synthetic local-provider parent→child→read-tool turn now runs. Background Job crash recovery, timeout retry, and active execution interruption/restart remain unobserved. |
| G4 local execution | PARTIAL | R: visible real desktop window (IPC hooks conflict); R: scratch local API session + queue inbox persisted after server restart; R: packaged CLI synthetic provider response → built-in read tool → explore child session → parent completion. No desktop click/IPC, no hosted model, no active execution interruption/recovery R. |
| G5 Atlas main comparison | PARTIAL | Prior Atlas baseline main SHA recorded; backlog rows provide tentative source paths. Re-fetch current `origin/main` and trace each mechanism fully before PASS. |
| G6 complete evidence packet | PARTIAL | Five gate artifacts created and prior reports indexed. Add exact package module inventory and event/symbol registry extracts; inspect citations and rerun reproducibility. |
| G7 final stop | OPEN | No completion claim. Continue as source/runtime work remains locally possible. |

## Reproducible local R recipes

- Desktop attempt used exact extracted installer application with `capture_electron_scenario`; returned visible `OpenCode` window `oc://renderer/index.html` (12s), but status `hook_conflict`, zero IPC events, and cleanup uncertainty. Captured process PIDs were checked with `Win32_Process`; none remained. Reproduction requires the same isolated artifact and REA provider; no click has yet succeeded.
- API test used exact extracted npm Windows x64 CLI executable, a synthetic-only server password, `HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA` beneath `D:\temp\opencode-g4`, config under that scratch root, workdir `D:\temp\opencode-g4\workspace`, and loopback port 49374. Create session; POST prompt with `resume:false`; GET inbox; stop and restart with identical scratch environment; GET same inbox ID. Server only listened on 127.0.0.1. No provider/model was configured. Process must be stopped after evidence; do not reuse user profile data.
- Agent/tool/subagent run used the same scratch tree and local provider config: `providers.local.package=@ai-sdk/openai-compatible`, `providers.local.settings.baseURL=http://127.0.0.1:49375/v1`, fake `apiKey=synthetic`, model `local/dummy`; only local provider script `evidence-extracted/runtime/mock-openai-provider.ps1` was exposed. Its `-Mode subagent` returned one parent subagent call, one child `read` call, and deterministic assistant completions. Provider request log records 4 local POSTs without body data. Server and mock provider processes were stopped and both ports verified unbound.

## External boundaries vs remaining work

No unresolvable external boundary is established for source enumeration, dynamic UI click capture, desktop IPC, background Job crash recovery, or active execution interruption. REA hook conflict is a tool limitation for this launch attempt, not proof UI/IPC is inaccessible. Cloud credentials were unnecessary: a local synthetic provider completed one real packaged Agent/tool/subagent turn. Therefore G7 remains open.
