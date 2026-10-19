# ZCode 3.15.3 MCP Apps/plugin UI trace (static, partial)

**Selected retained file hashes and ASAR boundary:** `DESKTOP-IPC-ANCHORS.md`. The main/host files were SHA-rehashed, but not checked individually against ASAR entry metadata; full ASAR validation has one observed unpacked node-pty integrity contradiction and REA timeouts.

```text
host Agent connection service method openMcpUiInstance [out/host/index.js @343,997..344,329]
  -> remote RPC mcpUiOpenInstance with workspace/session/plugin/server/scope/resource URI/owner WebContents [~344,045]
  -> app instance registration/validation [UNKNOWN handler path]

main MCP App instance registry [out/main/index.js @417,930..420,500]
  -> provenance + idempotency key includes workspace/session/plugin/scope/server/token [@417,930]
  -> require plugin/server provenance; Gen UI is identity/permission restricted [@418,765..419,204]
  -> create sandbox id, shell URL, app-specific partition, CSP, permission/resource state [@419,204 onward]
  -> TTL/pin/unpin/one-shot user gesture lifecycle [same registry block]

host plugin UI app-tool method [out/host/index.js @347,156..347,470]
  -> typed mcpUiRegisterAppTools RPC with workspace/session/instance/plugin/server/scope/generation/tools
  -> typed route schemas also define unregister/claim/resolve [out/host/chunk-OUCOFHX4.js @682,652..685,796]
  -> expose app tools to the model and return claimed tool results to the app/model [UNKNOWN]

packaged plugin sandbox [out/plugin-sandbox/gen-ui.js @595,913; @603,656; @612,362]
  -> browser window postMessage transport + MCP Apps ui/resource and ui/initialize schemas
  -> renderer attachment, origin checks, consent UX, host message forwarding [UNKNOWN]
```

Do not collapse DOM `window.postMessage`, Electron `MessageChannelMain`, and host remote service RPC into one transport. The data flow above is evidence-backed only through the marked packaged contracts and local code regions; unobserved arrows are explicit unknowns.
