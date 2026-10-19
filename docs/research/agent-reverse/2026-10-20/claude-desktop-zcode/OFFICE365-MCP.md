# OFFICE365-MCP.md — what ships in `resources/office365-mcp/`

Three files, 8.6 MB total:

| file | size | role |
|---|---|---|
| `office365-mcp-stdio.mjs` | 7 288 531 | the **whole bundled MCP server**, single-file ESM bundle (Microsoft 365 / Graph connector) |
| `pdf.worker.mjs` | 1 089 813 | pdf.js worker used by the extractor |
| `pdfExtractorProcess.mjs` | 425 295 | separate child process for PDF + Office (docx/xlsx/pptx) text extraction |

## 1. Is `office365-mcp-stdio.mjs` a bundled MCP server? — YES (S)

- Runs as a **stdio** MCP server, not HTTP. At startup (`@7269300` area):
  ```js
  process.env.MCP_TRANSPORT="stdio";
  _7e("MCP_AUTH_MODE","local");
  … const {StdioServerTransport} = await import(…);
  let S = await createMcpServerInstance({graphClientFactory:s, grantedScopesSource:u}, …);
  let x = new StdioServerTransport; await S.connect(x);
  ```
  Verified strings: `"StdioServerTransport"` @734406/734765/7271376, `process.env.MCP_TRANSPORT="stdio"` @7269250-ish.
- Self-identifies as (`@323873`):
  ```js
  J={mcpServerName:"mcp-microsoft-graph", mcpServerVersion:"1.6.0", …}
  ```
  So: package `mcp-microsoft-graph` v**1.6.0**.
- It also *contains* an HTTP transport path (`zns()` @7171096,
  `"MCP_AUTH_MODE=local is not supported on the HTTP transport; local mode is stdio-only."`),
  but the desktop app always starts it in stdio mode via `nodeHost.js`.
- Server capabilities declared: `{capabilities:{resources:{listChanged:!0},tools:{listChanged:!0}}}`
  (`createMcpServerInstance` @7171838).

### How the desktop spawns it
`index.chunk-lzaSYO3Q.js@1463956` `zat()`:

```js
let s = vat();                     // = join(app.getAppPath(),"resources","office365-mcp","office365-mcp-stdio.mjs")
                                   //   var lat="office365-mcp-stdio.mjs" @1456092
await fs.promises.access(s)        // else: "[office365-mcp] bundle is missing at <path>"
let l = new sit(s, [], env, {      // sit = nodeHost transport
  serverName: e.name, isRegistry: !1,
  proxyTargetHost: `https://${js[azureCloud??"global"].graph}`,   // graph.microsoft.com | graph.microsoft.us | dod-graph.microsoft.us
  quietStderr: !0, stderrStream: c,
  spawnTimeoutMs: fat,             // 60 s win32 / 30 s else  (@1456096)
  onChildMessage, onForked, onExited });
u.connect(l); u.listTools()
```

### Gate: only for `source === "admin"` and `server === "microsoft365"`
`Bat()` `@1463500`-ish:

```js
if(e.source!=="admin") throw Error(`built-in servers are not permitted for source "${e.source}"`);
switch(e.server){ case "websearch": …; case "microsoft365": …; case "github": …;
                  default: throw Error(`no spawner for builtin server "${e.server}"`) }
```

`source:"admin"` is stamped by `mergePluginConfigs()` `@2211640` for entries that came from
`managedMcpServers` (`origin:"managed-config"`) or org plugin settings (`origin:"org-plugin"`).
There is **no UI path** that creates a builtin entry from user input without going through the
managed-config schema (`Ns` zod union, `iOe` = builtin variants incl. `server:"microsoft365"`,
`server:"github"`, `server:"websearch"` — `@594300`-`@598300`).

### Reachability summary (see MCP-TOOLS.md notes)
- **1p (Claude Desktop consumer) build**: `armDirectMcpPool()` `@2877406` only accepts
  `managedMcpServers` entries where `zvn(e)` = `e.server==="microsoft365"` (`@2877169`), and only
  when the GrowthBook gate `"4074604942"` is on (in packaged builds), or unconditionally in dev (`!bl()`).
  → Office365 builtin is reachable **only** if an admin-managed config lists it *and* the gate is on.
- **3p (enterprise) build**: `connectorPoolInputs()` `@2870520`+ passes
  `yC()? Evn(cOe(K().mcp?.managedServers)) : this.creds?.mcpServers ?? []` into `EXt`, and
  builtin spawn happens in `wXt.connectMcp()`/`reconcileDirectMcpPool` (`@2213000`+).
  So managed server configs (from MDM/GPO/plist) are the source.

### Tool declarations (S) — 60 tool-ish literals, 36 real tools + 10 resource handlers

Real **tools** registered by `getReadTools`/`getWriteTools`/`getTeamsWriteTools` arrays
(`@7172376`, `@5283995`, `@5284360`):

read (13): `sharepoint_search`, `sharepoint_folder_search`, `outlook_email_search`,
`outlook_calendar_search`, `find_meeting_availability`, `outlook_find_available_time`,
`chat_message_search`, `teams_list_chats`, `get_me`, `search_people`, `teams_list_teams`,
`teams_list_channels`, `teams_list_channel_messages`
+ `read_resource` (registered separately, `@6311148`)
+ `get_granted_scopes` (conditional: `t.grantedScopesSource && (g==="local" || J.mcpGrantedScopesToolEnabled)`, `@7175506`)
+ 4 Teams write (`yVa()` `@5284360`): `teams_send_chat_message`, `teams_send_channel_message`,
  `teams_reply_channel_message`, `teams_create_chat`
+ 31 Outlook/SharePoint write (`VVa()` `@5283995`, verified: 31 `new <Cls>(t)` in the array): `outlook_send_mail`, `outlook_set_vacation`,
  `outlook_forward_mail`, `outlook_create_filter`, `outlook_trash_thread`, `outlook_create_label`,
  `outlook_update_label`, `outlook_batch_delete_messages`, `outlook_delete_label`,
  `outlook_untrash_thread`, `outlook_create_draft`, `outlook_create_reply_draft`,
  `outlook_create_reply_all_draft`, `outlook_update_draft`, `outlook_delete_draft`,
  `outlook_send_draft`, `outlook_create_event`, `outlook_update_event`, `outlook_delete_event`,
  `outlook_modify_labels`, `outlook_delete_filter`, `outlook_modify_thread_labels`,
  `outlook_batch_modify_labels`, `outlook_respond_to_event`, `sharepoint_upload_file`,
  `sharepoint_update_file`, `sharepoint_create_folder`, `sharepoint_rename_item`,
  `sharepoint_move_item`, `sharepoint_copy_item`, `sharepoint_delete_item`

= **13 read + read_resource + get_granted_scopes + 4 Teams write + 31 Outlook/SharePoint write = 50 tools** when all gates open (read-only default: 15 tools + 0 writes).

**Resource handlers** (10) — registered as `requiredResources`, surfaced through `read_resource`
(`@7172376` array `i=[new HR(t),new $R(t),new _R(t),new GR(t),new XR(t),new WR(t),new YR(t),new ER(t),new zR(t),new JR(t)]`):

`onedrive_file` (HR), `onedrive_drive` ($R), `sharepoint_site` (_R), `sharepoint_site_page` (GR),
`outlook_email_message` (XR), `outlook_folder` (WR), `outlook_calendar_event` (YR),
`meeting_transcript` (ER), `chat_message` (zR), `channel_message` (JR).
URI prefixes: `teams:///teams/`, `teams:///chats/`, etc. (`@6310683`).

Write tools are refused unless `MCP_WRITE_TOOLS_ENABLED` and the granted scopes cover the write
scope plus its companion read scope (`isRegistrableUnderGrant`, `@7173500`).

Full machine-readable table: `MCP-TOOLS.tsv` (60 office365 rows = 50 tools + 10 resources).

## 2. `pdfExtractorProcess.mjs` — what it does

A standalone worker/child that extracts text from **PDF and Office** documents. Not an MCP server.

- Bootstraps polyfills for `DOMMatrix`, `ImageData`, `Path2D` (`@1`-`@900`) because pdf.js
  expects browser globals.
- Uses `worker_threads.parentPort` if present, else `process.send` (`Wr = cn ?? process`, `Vt()`).
- Message in (`Wr.on("message", …)` at tail):
  ```js
  {type:"parse", buffer|bufferBase64, options:{kind?, maxPages, maxTextLength, startPage, endPage, timeoutMs?, workerDir?, maxOldSpaceSizeMb?, maxYoungSpaceSizeMb?}}
  ```
- Message out:
  ```js
  {type:"log", level, message}
  {type:"result", data:<text>, docType:"docx"|"xlsx"|"pptx", partsTotal, partsProcessed, truncated, malformed, sharedStringMisses, extractionMs}
  {type:"result", data, totalPages, pagesProcessed, truncated, firstPageTruncated, extractionMs}   // PDF
  {type:"error", error}
  ```
- PDF path `Xr()`: `pdfjs` getDocument({data, disableFontFace:true, disableRange:true,
  disableStream:true, isEvalSupported:false}) → page-by-page `getTextContent()` joined with spaces;
  page range `startPage..min(endPage, start+maxPages-1)`; truncates at `maxTextLength`
  (default `{maxPages:100,maxTextLength:2e5}`).
- Office path `$n()`: rejects OLE/CFB (`"OLE compound file (IRM/label-protected or legacy binary Office format)"`),
  requires zip (`"not a zip-based Office file"`), detects `word/document.xml` → docx,
  `xl/workbook.xml` → xlsx, `ppt/presentation.xml` → pptx; then dedicated parsers:
  `Hr` (docx), `zr`/`Gr` (xlsx incl. sharedStrings w/ blank detection and `=== Sheet: <name> ===`
  markers), `Vr` (pptx `--- Slide N ---`). Caps: `Dr` sheets, `kr` slides, `$r`=1e6 strings.
  Output markers are chosen so an LLM can read the flattened text.
- Spawned by the MCP server itself, not by the app: `lSr()` / `oSr()` at `@6245480`:
  ```js
  let workerDir = e.workerDir ?? rSr;                 // rSr = dirname of pdfExtractorProcess
  let S = existsSync(pdfExtractorProcess.mjs) ? <that> : <pdfExtractorProcess.js> : <dist fallback>
  if (worker_threads available) new kGo(S,{resourceLimits:{maxOldGenerationSizeMb, maxYoungSpaceSizeMb/2}, stdout:true, stderr:true})
  else fork(S,[],{execArgv:["--max-old-space-size="+…, "--max-semi-space-size="+…], silent:true})
  ```
  So it is a **Worker when possible, forked child otherwise**, 100 MB max input
  (`"<PDF|Office> file size <n> exceeds maximum 104857600 bytes"`).
- `pdf.worker.mjs` is the pdf.js worker that `Xr()` relies on.

## 3. MSAL usage — tenant, scopes, env contract

The app process (`index.chunk-lzaSYO3Q.js`) owns sign-in; the MCP server consumes tokens through
a **local-auth plugin** installed when `MCP_AUTH_MODE=local`.

### Env the app sets for the child (`bat()`, `@1456928`)

```js
{
  MCP_AUTH_PUBLIC_CLIENT_ID: e.clientId,
  MCP_AUTH_TENANT_ID:        e.tenantId,
  MCP_LOCAL_AUTH_CACHE:      <userData>/connectors/…/msal-cache.json,
  MCP_LOCAL_AUTH_CACHE_PATH: <same>,
  MCP_LOCAL_AUTH_NO_INTERACTIVE: "1",
  MCP_LOCAL_AUTH_CACHE_HOST: "1",                 // when safeStorage available
  MCP_PARENT_WINDOW_HANDLE:  "<hwnd>",            // WAM broker parent window
  // broker mode (this.authentication.microsoftAuthBroker):
  //   "disabled" → MCP_LOCAL_AUTH_BROKER_DISABLE="1"
  //   "required" → MCP_LOCAL_AUTH_BROKER_MODE="required"
  //   otherwise  → MCP_LOCAL_AUTH_BROKER_HOST="1"
  MCP_LOCAL_AUTH_CAE_DISABLE: "1",                // continuousAccessEvaluation==="disabled"
  MCP_SENSITIVITY_LABELS: '<json {version:1,labels:[{label_id,effect}]}>',
  MCP_AZURE_CLOUD: "usgov"|"usgov-dod",           // only for gov clouds
  MCP_GRANTED_DELEGATED_SCOPES: "<space-joined scopes>"
}
```

### Authority (`Sat()`, `@1457900`)

```js
function Sat(e){ return `https://${js[e.azureCloud??"global"].authority}/${e.tenantId}` }
```
with (`@587879`):
```js
js = { global:        {authority:"login.microsoftonline.com", graph:"graph.microsoft.com"},
       "us-gov-high": {authority:"login.microsoftonline.us",  graph:"graph.microsoft.us"},
       "us-gov-dod":  {authority:"login.microsoftonline.us",  graph:"dod-graph.microsoft.us"} }
```
`tenantId` may be a GUID or the aliases `"common" | "organizations" | "consumers"`
(`GEe` `@569919`); aliases are rejected when `sensitivityLabels` is set or when
`authFlow:"broker"` is chosen (`@594299`, `@574443`).

### Scopes

Default when the config sets none (`WDe`, `@589301`):
```js
["User.Read","offline_access","Mail.Read","Calendars.Read","Calendars.Read.Shared",
 "Files.Read.All","Sites.Read.All","Chat.Read","Mail.Read.Shared","OnlineMeetings.Read"]
```
Full catalog `zDe` (`@587900`+), classified `always|read|write|admin`:
always `User.Read`, `offline_access`; read `Mail.Read`, `Mail.Read.Shared`, `Calendars.Read`,
`Calendars.Read.Shared`, `Files.Read.All`, `Sites.Read.All`, `Chat.Read`, `OnlineMeetings.Read`,
`MailboxSettings.Read`, `People.Read`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`;
admin `ChannelMessage.Read.All`, `OnlineMeetingTranscript.Read.All`;
write `Mail.Send`, `Mail.ReadWrite`, `Calendars.ReadWrite`, `Files.ReadWrite.All`,
`Sites.ReadWrite.All`, `ChatMessage.Send`, `ChannelMessage.Send`, `Chat.Create`,
`MailboxSettings.ReadWrite`.

`wat()` (`@1458049`) builds the MSAL scope list: `[...customScopes, ...alwaysScopes]`, each
non-reserved name prefixed with `https://<graphHost>/`; reserved (`openid`,`profile`,`email`,
`offline_access`) kept bare (`Cat` set).

### Token caches on disk (app side)

| file | contents |
|---|---|
| `<connectorHome>/msal-cache.enc` | `safeStorage`-encrypted MSAL cache, prefixed `msal-cache-v1:<accountHash>:` (`pat`, `mat` @1456096) |
| `<connectorHome>/msal-cache.json` | legacy plaintext cache; read once then encrypted and deleted (`Mat()` `@1459565` "plaintext msal cache sunset") |
| `<connectorHome>/broker-session-accounts.enc` | broker account list, `session-accounts-v1:<hash>:` |
| `~/.mcp-office365/msal-cache.json` | legacy location wiped by `yat()` `@1456699` |

### Broker (WAM) — `msal-broker-worker`
`eh` (`@1456096`) = safeStorage `available/encrypt/decrypt`. The app loads
`@azure/msal-node`'s NativeBrokerPlugin **inside** `msalBrokerWorker.js`
(`loadHelperBrokerPlugin` in `index.chunk-BXLZazwD.js`; the loader is invoked from `index.chunk-lzaSYO3Q.js@1443851` `Ym()`), methods
`probe | getAccountById | getAllAccounts | acquireTokenSilent | acquireTokenInteractive | signOut`.
Redirect URI for the broker: `msalAppxWebRedirect(e) = \`ms-appx-web://Microsoft.AAD.BrokerPlugin/${e}\``
(`yit()`, `@1444724`).

### In-server MSAL
The MCP bundle contains its own MSAL (`@azure/msal-node` + `LocalAuthPlugin`) and talks to the
host through `msal-cache-*` frames (`MCP_LOCAL_AUTH_CACHE_HOST`) and `msal-sign-in-request` /
`msal-sign-in-result` frames relayed by `Lat()` (`@1461300`-ish). `MCP_AUTH_MODE` accepts
`obo|local` (default `obo` in the server, but the desktop forces `local`);
`MCP_AUTH_CLIENT_CHECK_MODE` default `enforce`.

## 4. Stage reached

| item | packaged | registered | delegated | invoked |
|---|---|---|---|---|
| office365 stdio MCP server | yes (7.28 MB) | yes (`Bat()` case `"microsoft365"`) | yes (`nodeHost.js` fork, `sit`) | **U / conditional**: only when a managed config lists `{server:"microsoft365", tenantId, clientId}` and (1p) GrowthBook `4074604942` is on, or (3p) `source:"admin"`. No config on this machine (`%APPDATA%\Claude\config.json` has only updater keys; `claude_desktop_config.json` has only `preferences`). |
| pdfExtractorProcess | yes | only inside the office365 bundle (`lSr`/`oSr`) | worker/fork from the MCP server | **U** (needs a tool call that reads a PDF/Office file) |
| msal-broker-worker | yes | yes (`index.chunk-BXLZazwD.js@1231`) | utilityProcess fork | **U** (needs a signed-in M365 account) |
