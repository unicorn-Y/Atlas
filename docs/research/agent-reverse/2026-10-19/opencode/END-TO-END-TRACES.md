# End-to-end traces (checkpoint)

All source paths below refer to exact v2.0.32 commit `843a6c514e606b436a7fe713422ace0a93ad3d61`; package entry anchors are the separately verified shipped ASAR listed in `evidence-extracted/PACKAGE-ARTIFACTS.md`. Static source traces are **S**, live local observations are **R**.

## Trace A — visible desktop launch and renderer RPC (partially observed)

1. `packages/desktop/src/main/index.ts`: configure and acquire single-instance lock; register `oc` renderer scheme; on ready, create early window before importing full `./desktop` service graph, then await renderer assets burst and import desktop runtime.
2. R: the shipped Electron executable launched the `oc://renderer/index.html` route and displayed a visible window titled `OpenCode` after 12 seconds (Electron 44.4.5). REA could not hook the process (`hook_conflict`), so no click, preload, IPC channel, or event was observed.
3. S: `packages/desktop/src/main/ipc.ts:62-70` creates MessageChannel, hands port to `IpcPortHandoff`, and transfers peer via `webContents.postMessage(IpcTransportPort, ..., [port])`.
4. S: renderer `packages/desktop/src/renderer/ipc-client.ts:38-57` receives that message, stores a MessagePort, subscribes to `DesktopEvents`, encodes each RPC as `{_tag:"Request", id, tag, payload, headers:[]}`; abort posts `Interrupt`, chunks are acked, and terminal `Exit` resolves/rejects pending caller.
5. S: main `packages/desktop/src/main/ipc-transport.ts:24-107` binds at most one port per `WebContents`, decodes inbound requests through RPC schemas, forwards responses and unbinds event streams on disconnect/destruction. The `DesktopRpc` contract is in `packages/desktop/src/shared/ipc-rpc/index.ts` and grouped RPC schemas.

Unclosed: renderer interaction target to exact RPC caller; runtime IPC capture; authenticated server request triggered by that action.

## Trace B — composer to persisted inbox (static complete; synthetic API R complete)

1. S: `packages/app/src/session/composer/queue.ts:88-114` prepares admission; `data.session.prompt(admission)` is the API invocation. The queue path uses stable IDs and error recovery around the call (`:170-195`).
2. S: `packages/protocol/src/groups/session.ts:396-415` declares `POST /api/session/:sessionID/prompt`, carrying `Prompt`, optional metadata and delivery (`steer|queue`), and optional `resume`; API description says it durably admits input and schedules the agent loop unless `resume:false`.
3. S: `packages/server/src/handlers/session.ts:308-329` forwards to `Session.prompt`, mapping prompt conflict, busy and missing-session errors.
4. S: `packages/core/src/session/session.ts:150-181` creates an inbox admission and selects execution behavior; `packages/core/src/session/inbox.ts` serializes per-session transitions, reconciles duplicate IDs and persists the inbox state. SQLite row model is in `packages/core/src/session/sql.ts:125-145`; projector/event transitions in `packages/core/src/session/projector.ts`.
5. R: local extracted v2.0.32 CLI served only loopback with scratch identity/data. `POST /api/session` returned a session at scratch workspace. `POST /prompt` with a synthetic message, `delivery:queue`, `resume:false` returned `type:user`; `GET /inbox` returned that item. The server was force-stopped and restarted against the same scratch HOME; GET returned the same message ID, text, and delivery, with SQLite DB retained under `D:\temp\opencode-g4\home\.local\share\opencode\opencode.db` (6,799,360 B at observation). No model endpoint was configured and `resume:false` prevented model dispatch.

This verifies session/inbox persistence across server process restart. It does **not** verify active-turn recovery or Agent execution.

## Trace C — turn, tool, and interruption/recovery (source only)

1. `core/src/session/execution.ts:65-143`: start claims execution, promotes eligible inbox messages, runs a turn, and releases claim on terminal outcome. Interrupt may resume promoted input when `resume:true` (`:145-170`).
2. `core/src/session/runner/llm.ts:65-101, 160-180`: LLM loop drains/promotes inbox at turn/step boundaries; `runner/step.ts:180-320` joins stream completion and tool fiber outcomes, distinguishes interruptions and retry eligibility. `runner/retry.ts:31-93` bounds retry-after and timeout retry count, with plugin hook decision.
3. Tool calls route to core Tool runtime; the built-in `subagent` plugin (`core/src/tool/plugin/subagent.ts:110-242`) creates/reuses child sessions, prompts child session, then registers a recoverable Job and backgrounds it or returns foreground result. Completion uses `SubagentCompletion` to deliver to parent and mark background work complete.
4. On server boot, `core/src/session/execution/restart.ts:17-225` reconciles pending jobs, handles shell and subagent recoveries, increments durable attempt count, enqueues synthetic “continue after restart” notice, resumes abandoned execution claims, and terminalizes after max attempts. Comments explicitly characterize execution recovery as at-least-once: an external side effect can repeat if the process dies after side effect but before recording completion.

Unclosed: exercise provider transport with a local deterministic model; perform tool execution against synthetic file; child lifecycle/parent notice; kill and restart during active generation; correlate actual events and DB state. Do not interpret persisted event re-subscription as active execution recovery.

## Trace D — Browser pane/CDP attach (source only)

Browser is a built-in GUI extension host, separate from agent plugins. `packages/gui-extensions/src/browser/main.ts` supplies main-side extension lifecycle; `ipc.ts` declares `browser.pane`; `pane.ts` binds registration to the owning window, validates supported server origin, detects replacement/suspension and closes tunnel resources. Renderer Browser UI invokes pane model operations (`model.ts`, `panel.tsx`). Agent-side `packages/plugin-browser/src/connection.ts` serves typed Browser RPC operations; per-session attachment is checked before browser methods and tunnel operations; `tunnel.ts` enforces one outstanding read and timeout/closed-state checks; `chromium.ts` hosts the Chromium/WebContents CDP access. Exact detailed closure is in prior `DISCOVERY-LEDGER.md` OPENCODE-018/019 and `EVIDENCE-INDEX.md`.

Unclosed: desktop UI click → attach lease → agent browser tool call → tunnel data → result/event, dynamically observed in shipped app.
