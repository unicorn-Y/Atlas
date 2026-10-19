# MCP-HOSTS.md — `mcp-runtime/nodeHost.js` vs `mcp-runtime/directMcpHost.js`

Both files live at `.vite/build/mcp-runtime/`. They are two **different** roles and are never
alternatives for the same server.

| | `nodeHost.js` (5 907 B) | `directMcpHost.js` (613 700 B) |
|---|---|---|
| role | **stdio shim / Node.js polyfill runner** for a *local* MCP server | **remote MCP client** (HTTP/SSE) running inside one utility process |
| process type | Electron `utilityProcess` (uses `process.parentPort`) | Electron `utilityProcess` (`process.parentPort`), plus `require("electron/utility")` at `@573` |
| what it always wraps | `node <serverEntryPoint> <...args>` via `import(pathToFileURL(resolve(w)))` at `@5712` | nothing — it *is* the MCP client; there is no child for remote servers |
| transports it speaks | **stdio only** (stdin/stdout JSON-RPC piped over a MessagePort) | **Streamable HTTP** (default) and **SSE** (`transport:"sse"`) |
| SDK side | acts as the *child process* the SDK's `StdioClientTransport` expects | hosts the real `Client` (`Qb`/`Tm`) + `McpServer` server-side shim |
| spawn site | `index.chunk-lzaSYO3Q.js@1431866` class `sit` (transport `nodeHostPath`) | `index.chunk-lzaSYO3Q.js@2117899` `RGt()`/`BGt()` (`"Custom 3P MCP Host"`, `@2118273`) |
| one host per… | per MCP server (own utilityProcess) | **one** shared utilityProcess for *all* remote direct-MCP servers (`Jb` singleton, `@2120000`-ish) |

## 1. `nodeHost.js` — the local-stdio shim

Full control surface (all verified byte strings):

| offset | string / behavior |
|---|---|
| `@1` | `#!/usr/bin/env node` |
| `@223` | class `g extends Error` for self-exec refusal |
| `@1117` | `code="ERR_MCP_NODE_HOST_NOT_NODE"` |
| `@1268` | message: `The built-in Node.js runtime cannot start "<file>" as a Node.js subprocess (child_process.fork or process.execPath). Install Node.js and turn off "Use built-in Node.js for MCP" …` |
| `@2228` | sentinel path `<dirname(execPath)>/.built-in-node-refused` — the app is replaced by this sentinel so `spawn` of the app binary fails |
| `@2709` | `ChildProcess.prototype.spawn` monkey-patch: refuses to launch the app executable |
| `@4285` | posts `{type:"self-exec-blocked",api}` to parent |
| `@4393` | `process.parentPort.once("message", …)` — expects **`type:"init"` with `ports[0]`**, else `process.exit(1)` |
| `@4722` | `process.stdout.write = n` → forwards `{type:"stdout",content}` to the port |
| `@4960` | `process.stderr.write` → forwards `{type:"stderr",content}` |
| `@5120` | stdin is replaced by a fake `Readable`; `port.on("message")` with `{type:"stdin",data}` pushes into it |
| `@5712` | `import(pathToFileURL(resolve(w)).toString())` — starts the actual MCP server module |
| `@5800` | `process.on("SIGTERM"/"SIGINT")` → `exit(0)` |

Message protocol (shim ↔ main), all `S`:

```
main → shim : {type:"init"} [MessagePort]          (once)
             {type:"stdin", data:<string>}         (JSON-RPC line; shim appends "\n", @5150)
shim → main : {type:"stdout", content}             (JSON-RPC line, decoded UTF-8)
             {type:"stderr", content}
             {type:"fatal-error", kind, message, stack}
             {type:"self-exec-blocked", api}
```

Spawn path in the main process: `sit` constructor computes
`nodeHostPath = <resources>/app.asar/.vite/build/mcp-runtime/nodeHost.js` (`@1431944` / `@1432023`),
then `start()` calls `jrt(nodeHostPath, [serverEntryPoint, ...args], {env, proxyTargetHost,
serviceName, stdio:"pipe", allowLoadingUnsignedLibraries:!0, disclaim:!0})` (`@1432054`).
It then creates `new a.MessageChannelMain`, posts `{type:"init"}` with `port2`, and:
- buffers stdout **line-wise** (`bufferStdoutFrame` `@1439000`-ish), caps a pending line
  (`Qrt`), drops non-JSON-RPC ("stray") lines, tolerates 3 undecodable lines before signalling
  `signalStreamError("MCP child stdout flooded invalid data")`;
- `classifyParsedLine` (`@1439900`) = strict `np.safeParse` → else loose `jsonrpc:"2.0"`+id/method;
- `reportFatal` / `reportSelfExecBlocked` add Sentry tags `mcp.serverName`, `mcp.extensionId`;
- `spawnTimeoutMs` default `Zrt`, exit → `recordExit` with normalized reason
  (`clean-exit` / `abnormal-exit:<code>` / `killed:<signal>` / `spawn-timeout`).

Why it exists: the app ships Node-in-Electron ("Use built-in Node.js for MCP") and wants local
MCP servers written for real Node to run without a system Node install. `nodeHost.js` supplies
`process.argv`, `process.stdin/stdout/stderr`, `parentPort`, and ESM `import()`; it deliberately
**blocks** a server from re-exec'ing the Claude binary (self-exec guard).

Env passing: main builds `env: Am(Jrt(), this.env)` (`@1432060`) — base env for a spawned MCP
child, with the extension's `env` merged on top, plus `proxyTargetHost`.

## 2. `directMcpHost.js` — the remote MCP client host

Boot (`@608532`):

```js
process.parentPort.on("message", (e)=>{
  let t=e.ports[0];
  if(e.data?.type!=="addServer"||!t){ console.error("[directMcpHost] expected addServer with MessagePort"); return }
  t.start(); pE(e.data.config, t);
});
```

Config object sent by main (`index.chunk-lzaSYO3Q.js@2118400`-ish `addServer` builder):

```
{ name, url, transport, headers?, appVersion,
  toolCallTimeoutMs, versionNegotiation?{mode:"auto",probe:{timeoutMs}}, authRetry? }
```

Transport selection (`@612510`):

```js
let a=new URL(e.url),
    s = e.transport==="sse" ? new ex(a,o) : new ax(a,o);   // ex=SSEClientTransport, ax=StreamableHTTP
```

- default → **Streamable HTTP**
- `transport:"sse"` → **legacy SSE**
- `o = {fetch, requestInit:{headers}}` — custom fetch (net.fetch-backed, `uE=iE((e,t)=>f.net.fetch(e.toString(),t))` `@608400`) and headers.

Connect + tool discovery (`hE`, `@612108`):

```
connect() (timeout RT=10s or probe timeout)
 → listTools()      (timeout zT=60s)
 → returns {client, tools}
```

Failure text markers: `connect timeout after <ms>`, `tools discovery timeout after 60000ms`,
and the diagnostic `zero tools: server did not advertise the tools capability, so tools/list was never sent`.

OAuth / auth refresh in-host:

- `authRetry` → second `tE` deferred queue (`i`), used by `IT({baseFetch,headers,requestRefresh})`
  (`@608900`): on HTTP 401/403 it asks the main process to refresh
  (`postMessage({type:"authRejected",seq})`) then retries **once** with renewed headers.
- child→host frames accepted: `updateAuth` (`{bearer}` → `headers.Authorization="Bearer "+bearer`),
  `updateHeaders` (`{headers}` — Authorization stripped unless intended, `@604165`),
  `elicitationResult`, `authRejectedResult` (`@609101`).
- `VT(e)` (`@604700`) strips any `authorization` key from rotated header maps.

Elicitation (server→client):

```js
e.setRequestHandler("elicitation/create", e => r.request(n => t.postMessage({type:"elicitation",seq:n,params:e.params})))
e.setNotificationHandler("notifications/elicitation/complete", ...)
```
(`@609700`-ish). Host→child: `{type:"elicitation", seq, params}`; child→host:
`{type:"elicitationResult", seq, result}`.

Tool exposure back to the session: the host runs a local `McpServer` (`new NT({name:e.name,version:"1.0.0"},
{capabilities:{tools:{},resources:{},extensions?}})` `@610300`) whose handlers proxy the remote client:

```js
v.setRequestHandler(tools/list, async()=>({tools:p.map(e=>({name, description, inputSchema, _meta}))}))
v.setRequestHandler(tools/call, async t => {
   return await f.callTool({name:n, arguments:r??{}}, {timeout:toolCallTimeoutMs})
})
```
(`@610900`, `@611017`). This is a **local loopback**: the utilityProcess is both the MCP client
(to the remote server) and an MCP server (to the app's own SDK client over `gE` port transport,
`@612700`). Errors are converted to `{content:[{type:"text",text:"Tool call failed: …"}],isError:true}`;
HTTP 404 on the session is treated as `Mcp-Session-Id expired — closing for repark` (`@610100`);
3 terminal connection errors → close.

Wire protocol child↔host (`gE`, `@612700`):

```
host → child : {type:"mcp", message:<JSON-RPC>}         (send)
               {type:"updateAuth"|"updateHeaders"|...}
child → host : {type:"mcp", message}
               {type:"ready", tools}
               {type:"error", message}
               {type:"elicitation"|"elicitationResult"|"authRejected"|"authRejectedResult"}
```

Frames are dropped if the port is closed: `post to closed port dropped (<type>)` (`@608377`).

## 3. Which one wraps which server

| server kind | host used | evidence |
|---|---|---|
| Extension / `local.*` MCP with a JS entry point | `nodeHost.js` (`sit`) | `index.chunk-lzaSYO3Q.js@2104631` `Lb()`: `"Using built-in Node.js for MCP server"` → `new sit(n.entryPoint, n.extraArgs, {...t.env}, {...})` |
| Extension MCP with a native binary | plain spawn (`IWt`/`Gm` process-group), **not** nodeHost | same `Lb()` else-branch `new(u.processGroupLeader?IWt:Gm)({command:u.cmd,…})` |
| **Bundled office365** | `nodeHost.js` (`sit`), entry point `resources/office365-mcp/office365-mcp-stdio.mjs` | `@1463956` `zat()`: `new sit(s,[],t,{serverName:e.name,proxyTargetHost:"https://graph.microsoft.com",…})`; `s=vat()` = `join(app.getAppPath(),"resources","office365-mcp",lat)` with `lat="office365-mcp-stdio.mjs"` (`@1456096`) |
| **Bundled GitHub** | **neither** — plain SDK `StdioClientTransport` inside the main process | `index.chunk-CQr0Ee4m.js@815`: `S=new t.I1({command:x.cmd,args:x.args,env:t.X1(t.F1(),b),stderr:"pipe"})` |
| Remote HTTP/SSE direct-MCP (managed/org-plugin/1p) | `directMcpHost.js` | `@2117899` `spawnUtilityClient` → `addServer` → child builds `ex`/`ax` |

## 4. MCP-facing eipc methods

The two hosts themselves are **not** eipc services — they are internal transports. The eipc
surface that controls them is:

| service | method | params | relation to hosts |
|---|---|---|---|
| `MCP` | `isLocalDevMcpEnabled` | — | gates local dev MCP |
| `MCP` | `setMcpServerConfigs` | `configs` | writes the config the transports are built from |
| `MCP` | `getMcpServersConfig` | `forceReload` | lists configs |
| `MCP` | `getMcpServersConfigWithStatus` | — | connection status incl. parked/needs-auth |
| `MCP` | `revealConfig` / `revealLogs` / `revealServerLog(serverName)` | — | support actions |
| `Extensions` | `installDxt…` / `deleteExtension` | — | produce/remove the extension MCP entries |
| `PluginBridgeMcp` | `listServers` | — | lists plugin-provided MCP servers for the desktop host bridge |
| `Custom3pSetup` | `probeMcpServer(config)` / `authorizeAndProbeMcpServer(config)` | `config` | uses the same client path to probe |
| `Custom3pSetup` | `forgetMcpOAuth(serverName)` | | clears stored OAuth |

`MCP` service table is at `index.chunk-lzaSYO3Q.js@1593000`-ish (`ig=eo(ng,"MCP",rg,{methods:[…]})`);
its events are `mcpConfigChange(configs)` and `mcpStatusChanged(name,status,error)`.
(`PluginBridgeMcp` table at `@1972381`.)

## 5. Tool-call path end to end (remote direct MCP)

```
renderer session
  → directMcpSnapshot in session spawn (buildDirectMcpBridgeTools, index.chunk-DlE0R5Pd.js@5135)
      tool names are `mcp__<server>__<tool>` (xoa=/^mcp__(.+?)__(.+)$/, lza@5797100)
      each carries _meta {"anthropic/approvalHash","anthropic/serverId","anthropic/kind":"direct",
                          "anthropic/toolName","anthropic/readOnlyHint","anthropic/alwaysLoad":true}
  → handleCall(serverName, toolName, args)
      → activeConnectorPool() → t.f(pool, serverName)   (live client)
      → policy re-check: blocked / ask / ask-session → "requires per-call approval and is not
        available from a remote session"
      → t.r(client, server, transport, tool, args, …)
```
`index.chunk-DlE0R5Pd.js@2134..3900` (S).

## 6. Error paths summary

| layer | signal | visible text |
|---|---|---|
| nodeHost self-exec | `{type:"self-exec-blocked"}` | "MCP server tried to launch the app executable (…) ; refused" (`lza@1432500`) |
| nodeHost fatal | `{type:"fatal-error"}` | `MCP Node Host fatal (<kind>)` |
| stdio framing | — | "Invalid JSON-RPC message from child" / "MCP child stdout exceeded the message size limit" |
| spawn | exit | `UtilityProcess spawn timeout after <ms>` / `UtilityProcess exited during spawn with code: <n>` |
| remote connect | throw | `connect timeout after <ms>` / `tools discovery timeout after 60000ms` |
| remote auth | 401/403 | one retry after `authRejected` refresh, else `HTTP <n> from the MCP server: <body>` |
| remote session | 404 | `Mcp-Session-Id expired (HTTP 404) — closing for repark` |
| tool call | — | `{content:[{type:"text",text:"Tool call failed: <msg>"}],isError:true}` |
