# End-to-end traces — current lane checkpoint

All paths below refer to OpenAI.Codex 26.1013.4894.0. Evidence is static shipped-artifact evidence unless explicitly called a local process observation. G2 is PARTIAL: no UI click has yet been connected through IPC, RPC handler, runtime event and persisted/reloaded state.

## Renderer mutation vocabulary to host request

1. `webview/assets/app-initial-5851df3f6cb1.js` contains a static classifier that recognizes `thread/start`, `thread/startAeon`, `thread/fork`, `thread/inject_items`, `thread/queue/add`, `turn/addUserMessage`, `turn/start` and `turn/steer`.
2. `.vite/build/main-C4DYk222.js` contains a JSON-RPC client and literal method handling for `thread/start` and `thread/resume`; it also contains `thread/queue/list` followed by `resumeThread` in `wakeQueuedThread`.
3. `.vite/build/preload.js` exposes `electronBridge` with `contextBridge`; `sendMessageFromView` passes messages to `ipcRenderer.invoke`.
4. **Unknown edge:** no action-specific renderer call was followed to the exact preload message, main IPC handler and `sendAppServerRequest` method. The static method list does not prove those calls share a path or that a UI button is reachable.

The UI path alone therefore does not satisfy bidirectional mapping. Approval response, MCP resource widget, subagent start/result, queue lifecycle and computer-use host remain separate traces to close.

## Process and runtime observation

The exact installed version was already running. Process inventory observed ChatGPT.exe, codex.exe, codex-code-mode-host, codex-computer-use-swift and codex-windows-sandbox-service. No ChatGPT-owned loopback CDP listener was identified. Process existence alone does not establish parent-child links, task ownership, RPC frames, persistence, or restart recovery. No user UI was clicked. A REA-owned isolated launch attempt failed with `Transport closed`; see COVERAGE.md.

## Failure and persistence evidence

For the *open-source* `rust-v0.163.0` App Server, retain existing IMPLEMENTATION-TRACE §3–5 evidence separately. It documents thread recovery, listener order, event/state contracts and failure encodings for that source version; it does not establish the Windows package's server implementation. Package-local turn/task persistence, subagent interruption/replay, process relaunch and crash recovery remain unknown.
