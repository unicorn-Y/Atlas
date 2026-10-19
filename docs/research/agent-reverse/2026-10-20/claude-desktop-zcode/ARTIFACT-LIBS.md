# ARTIFACT-LIBS.md — chart.js / mermaid / gridjs in Cowork artifacts

## 1. What is packaged

`_asar\resources\artifact-libs\` (4 files, 3.8 MB):

| file | size | upstream |
|---|---|---|
| `npm_chart.js@4.5.0_dist_chart.umd.js` | 208 337 | Chart.js 4.5.0 UMD |
| `npm_gridjs@5.0.2_dist_gridjs.umd.js` | 60 552 | Grid.js 5.0.2 UMD |
| `npm_gridjs@5.0.2_dist_theme_mermaid.min.css` | 7 762 | Grid.js "mermaid" theme CSS |
| `npm_mermaid@11.17.2_dist_mermaid.min.js` | 3 572 661 | Mermaid 11.17.2 |

Filenames encode the npm spec: `npm_<pkg>@<ver>_<path with / → _>`.

## 2. How they are injected — the `https` protocol override

`index.chunk-lzaSYO3Q.js@5795288` — the allow-list of URLs the artifact session may load:

```js
var goa=[
 {url:"https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js",
  sri:"sha384-iU8HYtnGQ8Cy4zl7gbNMOhsDTTKX02BTXptVP/vqAWIaTfM7isw76iyZCsjL2eVi",
  hint:"Chart.js v4 (UMD, global `Chart`); set `responsive: true, maintainAspectRatio: false` …"},
 {url:"https://cdn.jsdelivr.net/npm/gridjs@5.0.2/dist/gridjs.umd.js",
  sri:"sha384-/XXDzxe4FsGiAe50i/u9pY/Vy/uX654MHB1xoc1BJNnH1WXHhqHga9g3q5tF4gj7", …},
 {url:"https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js",
  sri:"sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2", …}],
 _oa=[{url:"https://cdn.jsdelivr.net/npm/gridjs@5.0.2/dist/theme/mermaid.min.css",
       sri:"sha384-jZvDSsmGB9oGGT/4l9bHXGoAv1OxvG/cFmSo0dZaSqmBgvQTKDBFAMftlXTmMbNW", …}],
 voa=new Map([...goa.map(e=>[e.url,"text/javascript; charset=utf-8"]),
              ..._oa.map(e=>[e.url,"text/css; charset=utf-8"])]);
```

A **local https handler** intercepts those exact URLs and serves the packaged file
(`@5796537`, function `yoa`; URL→file map built at `@5796407`):

```js
async function yoa(e){
  let t=voa.get(e);                         // exact-URL allowlist
  if(t===void 0) return Response.error();
  let r=await a.net.fetch(pathToFileURL(join(app.getAppPath(),
        "resources","artifact-libs",
        new URL(e).pathname.slice(1).replaceAll("/","_")      // /npm/chart.js@4.5.0/dist/… → npm_chart.js@4.5.0_dist_…
      )).href);
  return new Response(r.body,{headers:{"Content-Type":t,"Access-Control-Allow-Origin":"*"}});
}
```

So: **no CDN traffic occurs.** `https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js`
is rewritten to `resources/artifact-libs/npm_chart.js@4.5.0_dist_chart.umd.js`. The `sri` hashes
are declared for the same bytes (they are informational here — the file is local, so SRI is not
re-validated by the handler; it exists so the model/devtools see the upstream integrity value).

Registered per artifact session (`Roa()`, `@5800125`):

```js
let e=_4();                                     // session partition `persist:cowork-artifact<ns>`
e.setPermissionRequestHandler((_e,_t,n)=>n(!1)); // deny all permissions
e.setPermissionCheckHandler(()=>!1);
e.webRequest.onBeforeRequest((d,c)=>{
  c({cancel: !d.url.startsWith("cowork-artifact://") && !voa.has(d.url)})   // @5800360 onBeforeRequest, @5800459 protocol.handle("https")
});
e.protocol.handle("https", e=>yoa(e.url));      // local substitution
e.protocol.handle("cowork-artifact", …);        // serves index.html + project files
```

`voa` is the allowlist for `onBeforeRequest`; anything else is cancelled at the network layer —
the CSP alone is not the only gate.

## 3. CSP applied to artifact documents

`@5803032` (inside the `cowork-artifact://` handler, before returning `index.html`):

```
default-src 'self';
script-src  'self' 'unsafe-inline' <every goa url, space-joined>;
style-src   'self' 'unsafe-inline' <every _oa url>;
img-src     'self' data:;
font-src    'self' data:;
connect-src 'none';
object-src  'none';
frame-src   'none';
form-action 'none';
base-uri    'self'
```
plus `Cache-Control: no-store`, `X-DNS-Prefetch-Control: off`.

Consequences: **no fetch/XHR/WebSocket at all** (`connect-src 'none'`), exactly 3 script origins
and 1 CSS origin (all locally served), no frames, no objects, no forms.

The artifact iframe that hosts this document is itself under a separate CSP
(`@824562`, endpoint table entry `"artifact-sandbox"`): `frame-src` = the artifact iframe host
(default `www.claudeusercontent.com`) with firewall allowances for
`cdnjs.cloudflare.com`, `fonts.googleapis.com`, `cdn.jsdelivr.net`.

## 4. Where the model is told about these libs

The artifact authoring prompt (`index.chunk-BYMGAPtw.js@33952`) states the enforced allowlist:

> **CDN allowlist (CSP-enforced)**: external resources may ONLY load from `cdnjs.cloudflare.com`,
> `esm.sh`, `cdn.jsdelivr.net`, `unpkg.com`, `fonts.googleapis.com`, `fonts.gstatic.com`.
> All other origins are blocked by the sandbox — the request silently fails.

and gives per-library usage hints that match `goa`/`_oa` `hint` strings:
- Chart.js → global `Chart`, `responsive:true, maintainAspectRatio:false`, init only when visible
- Grid.js → global `gridjs`, pair with the theme stylesheet
- Mermaid → global `mermaid`, `mermaid.initialize({startOnLoad:true,securityLevel:"strict"})`,
  diagrams in `<pre class="mermaid">…</pre>`

Note the prompt's allowlist is *wider* than the `https` handler (`esm.sh`, `unpkg.com`,
fonts hosts are not in `voa`). Those hosts are reachable only if the artifact's own CSP permits
them — but the CSP built at `@5802953` is generated **only from `goa`/`_oa`**, so in the
`cowork-artifact` document those extra hosts are refused by `script-src`/`style-src` and by
`onBeforeRequest`. The two lists disagree; the enforced one is `voa`.

## 5. Watch-case (scheduled task) artifacts

Separate CSP `Foa` (`@5799530`; applied in the watcher branch of `Roa()`):

```
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
font-src 'self' data:; connect-src 'none'; object-src 'none'; frame-src 'none';
form-action 'none'; base-uri 'self'
```
— stricter: no `'unsafe-inline'`, no lib URLs. Used for the `__watcher_shell.js` / `watching.js`
injection path.

## 6. Stage reached

| item | packaged | registered | delegated | invoked |
|---|---|---|---|---|
| 3 artifact libs + 1 CSS | yes (4 files) | yes (`voa` map, https handler) | served into the artifact session | **U** — requires rendering an artifact that references those exact URLs; not observable in this static extract |
