# End-to-end code traces — Claude Desktop 2.42304.0

Authority: shipped package static (S) unless stated. Offsets are character positions in the original UTF-8 minified bundle. No line break or prettification is implied. Fixed input digest and package identity are in `COVERAGE.md` / `evidence/README.md`.

## T1 — Cowork artifact scheduled task invocation (S, partial lifecycle)

1. **Artifact renderer bridge** — `.vite/build/coworkArtifact.js` (SHA256 `21f4dfed39f8290444e31a153fe8d68596b10d6d3b44af6e94b4d472c9c14e45`, 2,687 bytes) exposes `window.cowork.runScheduledTask(taskId)`; it attaches `navigator.userActivation.isActive` as preload context. The renderer bridge sends `ipcRenderer.invoke` with a generated channel in the `claude.coworkArtifact` family.
2. **Main receiver registration** — `.vite/build/index.chunk-lzaSYO3Q.js` around char 5,836,915 registers the handler family under a top-level-frame-only `cowork-artifact:` origin check. It is not a generic renderer IPC exemption.
3. **Policy and task validation** — handler around chars 5,863,754+ checks feature rollout, run permission, the artifact being visible, task lookup, imported-task enabled state, and a recent user gesture (gesture path around char 5,864,600). Rejected states produce explicit result/error categories.
4. **Scheduler invocation** — valid action calls scheduler `runNow` with `personStarted:true`, then returns a session identifier or error. A separate task-dispatch path can ask the VM manager to start the legacy local guest when scheduled work is not dispatch-ready (around char 5,791,271).
5. **Unclosed tail** — this proves scheduling request reaches scheduler code. It does not establish which agent/runtime handles the task, what is committed to durable DB, model/tool calls, child-task behavior, retry policy, resume semantics, or cloud ownership. Those remain U.

## T2 — Artifact MCP tool invocation (S, partial tool lifecycle)

`window.cowork.callMcpTool(tool,args)` in the same bridge sends a distinct generated IPC method. Main code around char 5,860,203 checks artifact visibility and argument validity, resolves task-artifact handling separately, resolves server/tool, applies managed tool policy and disabled state, and requires confirmation for destructive tools unless remembered approval applies. A cache branch is eligible only for a narrow read-only remote call. The server invocation is reached, but the exact backend transport, transcript/tool event schema and persistence are not linked in this trace.

## T3 — Legacy local Windows VM service protocol (S, app-to-service connection; Go body partial)

1. `.vite/build/index.chunk-lzaSYO3Q.js` defines the ClaudeVM request/event API near char 1,977,078. Main VM manager invokes a configure/start routine; a scheduled-task readiness callback can request startup around char 5,791,271.
2. Windows client connects to `\\.\pipe\cowork-vm-service` around char 2,979,600. Packaged builds require native `connectNamedPipeSystemOwned`; missing binding fails closed. Only unpackaged development builds can fall back to ordinary `net.createConnection`.
3. Messages use a 4-byte big-endian length prefix, maximum 10 MiB, and JSON `{id,method,params}` request envelopes. Pending request IDs correlate success/result or error replies. Idempotent methods can be retried after pipe closure; non-idempotent behavior must not be generalized from that code.
4. The client sends methods including `configure`, `startVM`, `stopVM`, `isRunning`, `isGuestConnected`, `spawn`, `kill`, and `writeStdin`. Event stream names include stdout, stderr, exit, error, networkStatus, apiReachability, startupStep. Main VM manager configures then calls `startVM(bundle,memory,cpu,"gvisor",probeURL,guestProxy,...)` near char 4,341,793 and surfaces status/error callbacks.
5. `cowork-svc.exe` is the signed Go x64 Hyper-V management service; identity/import/help metadata and strings are recorded in `evidence/svc-identity.json`, `svc-imports.txt`, `svc-symbols.tsv`. Available Ghidra analysis has 12,769 procedures, but Go pclntab names survive only as strings and procedures remain mostly unnamed. No verified Go call edge proves service install/start parent, request dispatch, or DB writes. No service process was launched. Keep service-side behavior U.

## G4 — live UI / Agent execution attempt

Attempted, but no UI/R result. (1) REA provider-owned Electron scenario with the exact extracted `Claude.exe`, exact app root, and `--user-data-dir=D:\_tmp\claude-desktop-research-disposable` returned `Transport closed`; post-check found no Claude process. (2) Direct launch with `--user-data-dir=D:\_tmp\claude-desktop-research-disposable\UserData`, APPDATA/LOCALAPPDATA/TEMP/TMP directed to sibling disposable directories, `--no-first-run`, background networking disabled, and host resolution mapped to loopback exited code 1 within eight seconds with no window and no temp-profile files. The current-user Appx inventory had no matching registered package. No Claude crash event was found in the recent Application log, so the cause is **unknown**; the direct launch does not establish that package registration is the cause. No login or existing account/session inspection occurred. Consumer equivalent is unavailable. No claim of observed UI, Agent→model→tool run, child task, pause, interruption or recovery is made. Further safe execution requires an isolated Windows package registration/profile and must stop before sign-in or account data access.

