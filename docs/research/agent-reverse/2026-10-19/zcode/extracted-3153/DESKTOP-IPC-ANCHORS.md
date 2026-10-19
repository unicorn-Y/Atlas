# ZCode 3.15.3 desktop linkage anchors

## Artifact boundary

Installer SHA-256 is `bc8100ba4377256fbe1531d549b4775f18e3ba21768b6294ca50751cd461faca`. Retained `resources/app.asar` is 340,516,766 bytes, SHA-256 `3fb4104ddcd79e9808eede75192299a22057bd9c336e15b9c2bb1825b4120283`. Selected retained extracted-bundle SHA-256 values:

| File | Bytes | SHA-256 |
|---|---:|---|
| `out/main/index.js` | 786385 | `afa4a85ed1775e18a5364c4b66bd8bdc8074fefc2d2b60a6ce05547998005bee` |
| `out/main/chunk-JS2T33SG.js` | 16980 | `f9c6cd919121ab4c1d5374bf6069ccfa2de0bb5b46f053e1c788f30e08ba1b80` |
| `out/host/index.js` | 1681899 | `dfa58d6a16de14c5cc43a0d0bc0c8f8d7da6f50d7454d987841e35203efa6fe3` |
| `out/host/chunk-OUCOFHX4.js` | 823914 | `e87794b90a7b781003406d13d59a53903443818e5a133f8dfd26cd8a41b58cb1` |
| `out/host/chunk-T2GB4I3K.js` | 135089 | `3d2a2178786ea7eb6d373555734882eda9be1fffa645a2eb6ff65975a3bd1e0c` |
| `out/preload/index.cjs` | 754590 | `a7dc05057a1380de7d72d77d4c08c668ea9f6dd4c93db8f498b53149bf62dfe9` |
| `out/scheduler/index.js` | 1044837 | `200ef2c01df5a2b92b62c741745dae63223775e11cee83a0191f742816d39396` |

These bundle files are present under the retained `app.asar.extracted/out` tree. Their byte hashes are recorded to make subsequent analysis reproducible. This evidence does not substitute for individual entry integrity validation against ASAR metadata; that graph is incomplete due the separate node-pty integrity contradiction and REA timeouts. EXE and application were not launched.

## Concrete desktop-to-host structure

1. `out/main/index.js` contains Electron main-process logic, imports `ipcMain` (minified local alias `Ca` in the captured bundle segment), creates plugin sandbox MessageChannelMain instances, and installs request handlers. The relevant plugin-sandbox segment around byte 440,360 passes `createMessageChannel: () => new MessageChannelMain`; around 440,446 and 440,506 it registers owner-webContents and copy-image `ipcMain.handle` operations with sandbox ID, owner ID, and init ID checks.
2. `out/preload/index.cjs` exposes a dedicated `zcodePluginSandbox` API. At byte 731,937 it calls `contextBridge.exposeInMainWorld`; at 732,032 onward methods use `ipcRenderer.invoke` for copy image, owner-webContents ID, and sandbox disposal. This establishes a concrete narrow preload bridge; no unrestricted generic IPC exposure is inferred.
3. A generated service facade in `out/main/chunk-JS2T33SG.js` groups clients for `zcodeAgentService`, task/session/window services, subagents, commands, hooks, memory, MCP sync, plugin UI bridge/sampling/app tools, plugin management and other domains (byte range 900–4,724; `pluginUiBridgeService` at 1,337, `subagentsService` at 1,464, and `zcodeAgentService` at 2,388). Matching host client setup appears in `out/host/chunk-T2GB4I3K.js` around 129,653–130,939.
4. `out/host/index.js` has a `zY` connection-scope constructor at byte 1,485,097, which wraps a MessagePort-like object and constructs RPC client `JN`; typed service clients `zcodeAgentService`, `zcodeTaskService`, `zcodeSessionService`, and `modelSelectionService` appear at byte 1,485,152 onward, ending about 1,485,368. The remote transport construction is observed, but the main/utility-process caller that transfers this port was not yet connected.
5. Host schemas at `out/host/chunk-OUCOFHX4.js` byte 803,509 define settings navigation sections including subagents/plugins/MCP and the page enum at 803,771 includes a plugin marketplace route. These are serialized navigation contracts, not proof of all UI routes being rendered. Other packaged bridge surfaces are listed in `UI-SURFACES.tsv`.

## Newly closed MCP App / plugin UI section

- Main bundle `out/main/index.js` byte 417,930 onward contains a `mcp-app` UI instance registry. The idempotency key includes owner WebContents ID, workspace identity/path, session, content kind, plugin ID, scope ID, server name, and instance token. Registration rejects missing plugin/server provenance for MCP Apps, while Gen UI is prohibited from claiming plugin/server identity or permissions (around 418,765–419,204).
- Each registered instance gets a unique sandbox ID and an app-specific shell URL and session partition. Gen UI gets a `gen-ui-<appIdentity>` partition; MCP app partition is derived from app identity. Main constructs a CSP header from requested CSP/relaxations and records owner, session, plugin/server/scope, HTML, permission list, resource metadata, and UI hints. The registry expires unpinned instances, supports pin/unpin, and only allows one-shot user gesture consumption (same block through ~420,500). It records camera/microphone/geolocation/clipboard-write as sensitive permission names and unsafe-eval/WASM-eval CSP relaxations around `host/chunk-OUCOFHX4.js` byte 522,497.
- `host/chunk-OUCOFHX4.js` byte 682,652 enumerates typed `mcp/ui*` routes: list/read resource and templates; subscribe/unsubscribe; register/unregister app tools; claim/resolve app tool calls. The parameter/result schemas for register/claim/resolve appear around 685,647–685,796. Host connection methods in `host/index.js` around 343,997 and 347,156 issue `mcpUiOpenInstance` and `mcpUiRegisterAppTools` requests with workspace/session/plugin/server/scope/instance/generation and tools. This establishes host RPC surface and provenance propagation, while the server/provider handlers and model-visible tool injection are not yet linked.
- Bundled `plugin-sandbox/gen-ui.js` and alias include the MCP Apps `ui/initialize`, `ui/resource`, and `ui/resource-teardown` protocol schemas and a browser `window` message transport (`postMessage` at ~595,913). It is an SDK protocol implementation in a sandbox artifact; the exact outer renderer iframe caller and runtime tool context remain open. Do not equate this DOM postMessage channel to Electron MessageChannelMain or the host RPC socket.

The concrete MCP App chain is therefore partial but materially established: host requests an app instance and app tools through typed remote RPC → main tracks a provenance-bound sandbox record and returns an app shell URL/partition/CSP/permissions → packaged sandbox implements the MCP Apps UI protocol. Unknown arrows: actual renderer caller/attachment; sandbox resource loading and validation at runtime; individual `ui/*` message forwarding and consent UI; plugin-server tool registration to model context; app-tool call result return to model; teardown/reconnect behavior.

## Implications and open linkage

The package is not a single Electron renderer directly invoking agent code: it contains a typed service facade, host-side remote RPC clients, explicit plugin/MCP App sandbox registry, preload calls, and separate `main`, `host`, `renderer`, `scheduler` outputs. The 3.15.3 runtime CJS remains a separate artifact; its `tool_queued -> executeTools` and background subagent paths do not by themselves prove that the UI subscribes to these states. Remaining high-value work is exact host transport boot caller, renderer app attachment/message forwarding, model context injection/result return for UI app tools, and per-file verification against ASAR entry metadata.
