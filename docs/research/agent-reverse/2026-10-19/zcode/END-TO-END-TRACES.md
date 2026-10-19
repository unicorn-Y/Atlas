# End-to-end trace status (3.15.3 package and bounded local probe)

All byte offsets in this document are offsets in the UTF-8 bytes of the exact named bundle; see `extracted-3153/DESKTOP-IPC-ANCHORS.md` for file hashes. Static package facts are marked **S**. Runtime observations are marked **R**. Unknown transitions are not drawn as completed arrows.

## A. Main process → Host service port → renderer attachment (S, partial)

* `out/main/index.js` at offset 516,642 forks the Host utility process with `utilityProcess.fork(...)`.
* At offset 524,824 the main startup path creates a `MessageChannelMain`, transfers one port to the Host child with `postMessage(...,[port])`, and transfers the other to the renderer WebContents on the internal `ServicePort` channel.
* At offset 588,765 the window `dom-ready`/reattach path creates a fresh channel, sends the Host port in `AttachServicePort` with `clientMode:"desktop-continuous"` and `scope:{kind:"local"}`, then sends the peer port to the renderer's `ServicePort` channel. The adjacent log identifies this as renderer reload reattachment to an existing Host process.
* `out/host/index.js` at offset 343,993 implements `openMcpUiInstance(g)` through the typed remote service client. At 347,156, 347,644, and 347,895 the Host facade issues app-tool register, claim, and resolve RPC requests. The service map re-exposes these methods around offset 1,527,677.

This establishes process creation and the two service-port handoffs, including renderer reload attachment to a live Host. It does **not** establish that Agent execution, background tasks, pending tools, or journaled workflows survive a Host/process restart. The `AttachServicePort` path is a transport/client reattachment observation only.

## B. Desktop startup → renderer page (R, partial)

1. Launched the retained `ZCode.exe` from the extracted 3.15.3 application directory with `--user-data-dir=D:\Atlas\.worktrees\reverse-zcode\work\zcode-profile-3153 --remote-debugging-port=9339 --no-first-run --disable-background-networking` and an initially unowned local port 9339.
2. Main PID 55060 remained alive; CDP browser user agent identified ZCode/3.15.3, Electron 41.0.3, Chromium 146.0.7680.80. `list_electron_targets` found one `ZCode` page at `app.asar/out/renderer/index.html` (Evidence `ev_49e6e6ea5689b868e98358ce0348ca05ec529fb74d25a2ad8391cf86c235c0d2`).
3. Passive page inspection found one top frame, 1,491 DOM nodes, and 307 loaded JS scripts (Evidence `ev_dc5735b0dfdda2f1527d9551626b2ed373b9d12085b6a5b4ce9474316277f966`). A screenshot request was rejected with `target_not_allowed` for this file-origin target; `analyze_web_bundle` returned the same policy reason.
4. Process command lines showed all six children (crashpad, GPU, renderer, and three utility processes) using `--user-data-dir=C:\Users\25011\AppData\Roaming\ZCode`, despite the requested isolated worktree profile on the parent process. This means the probe cannot be certified as isolated and is **inconclusive/unsafe for synthetic G4**. PID 55060 was stopped immediately; all six descendants exited and 9339 stopped listening. No message, tool, subagent, or existing conversation was touched by the probe.

The launch confirms that the retained app reaches an Electron page, but does not validate a new task or establish the actual product UI controls. The default user-data path was not inspected. Do not relaunch unless a code or provider-owned launch path can be proved to isolate every child first.

## C. Renderer event → MCP App client (S, partial)

* `out/renderer/assets/parts-1PK4PulD.js` at UTF-8 offset 5,622 defines the `pluginUi.appToolCall` event shape, including activity, cancelled, plugin/server provenance, subscribers, call ID, and tool name.
* `out/renderer/assets/styles-CSpM3qgc.js` at offset 1,044,692 dispatches the `pluginUi.appToolCall` case to `notifyAppToolCall({activity,cancelled,callId,toolName,...})` on an MCP Apps client; the helper invokes the MCP Apps SDK client's `execute(...)`. At 1,122,039 the renderer dispatch predicate includes this operation among plugin UI events.
* **Unknown:** which main/host service event emits this payload; any event subscription registry linking a specific `pluginId/serverName/instanceId`; the app-tool response handler to the model-facing tool result.

This closes packaged renderer decoding and client notification, not the producer or result path.

## D. Host RPC → main MCP App sandbox registry → plugin sandbox protocol (S, partial)

1. `out/host/index.js` at offset 343,993 implements `openMcpUiInstance(g)` and sends typed RPC `mcpUiOpenInstance` with workspace/session and plugin/server/scope/resource metadata. The exact same-version host app-tools facade methods are at 347,156 (register), 347,644 (claim), and 347,895 (resolve); the map exposes them again near 1,527,677.
2. Host route definitions in `out/host/chunk-OUCOFHX4.js` at offset 682,652 declare `mcp/uiOpenInstance` and app tool registration/unregistration/claim/resolve methods with request/result schemas (register/claim/resolve schemas near 685,647–685,796). Main's corresponding route-name table/schema appears in `out/main/chunk-OW6EUS2G.js` around offsets 717,781–721,431.
3. `out/main/index.js` around 417,930–420,500 contains a provenance-aware instance registry. Its idempotency key binds owner WebContents, workspace/session, content kind, plugin, scope, server and instance token. MCP App identities require plugin/server provenance; the registry assigns an app-specific shell URL, sandbox ID, partition, CSP, permission/resource state, and supports TTL, pinning and one-shot user-gesture consumption. Gen UI receives a separate restricted identity/permission path.
4. `out/plugin-sandbox/gen-ui.js` at offsets 603,656, 612,362 and 619,917 packages MCP Apps `ui/resource`, `ui/initialize`, and resource teardown schemas/handlers. A browser-window `postMessage` transport is present near offset 595,913.
5. **Unknown:** host service handler that receives the RPC and returns the shell resource; renderer code that mounts/attaches this URL and forwards protocol messages; origin/resource validation at runtime; visible consent path; plugin-server tool registration into model context; claim/resolve handlers and result return; close/reconnect interaction across the transport boundaries.

Keep DOM `window.postMessage`, Electron `MessageChannelMain`, and the host's MessagePort RPC separate. The main→Host and main→renderer service-port transfer is now statically located, but the MCP App sandbox DOM transport is not yet shown forwarding through that service port.

## E. Agent tool / child / workflow state (S, partial; no R)

* Embedded runtime CJS contains `scheduleTools → tool_queued → executeTools` in region 13,205,979–13,210,657; pending tool persistence helper `persistPendingToolPart` at 13,192,839–13,193,404.
* `InMemoryRuntimeTaskRegistry` at 5,042,044–5,044,543 tracks active branch generation, tasks, background waiters and terminal waiters. `requestBackground` at 5,042,679 marks background state and resolves waiters.
* Child run emits `SubagentSpawned` at 12,715,173; background path calls `detachParent()` at 12,716,232 and task port uses the background registry at 12,719,281.
* Workflow journal/migration/replay helpers are in regions 1,515,023–1,543,238 and 12,513,514–12,524,192. These show SQLite-oriented schema/helper and input-hash replay checking in the artifact. They do not prove journal initialization or that an in-progress model/tool request resumes after process exit.
* **Unknown:** live UI subscription to tool/subagent/task state; child-result command re-entry in same-version 3.15.3; restart behavior for background task registry; distinction between restored view, resumed event subscription, and cold execution recovery.

No G4 Agent/model/tool/child execution occurred. The only live trace is startup/page observation in A.
