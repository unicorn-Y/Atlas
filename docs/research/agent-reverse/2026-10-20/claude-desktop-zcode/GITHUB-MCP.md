# GITHUB-MCP.md — `github-mcp-server.exe`

Location: `extract\app\resources\app.asar.unpacked\resources\github-mcp\github-mcp-server.exe`
(20 566 352 bytes; unpacked because a PE cannot run from inside an asar).

## Identity (S, byte offsets)

| item | value | offset |
|---|---|---|
| magic | `MZ`, PE at 0x80, `PE\0\0`, machine `0x8664` (x86-64) | 0, 128 |
| Go build info magic | `\xff Go buildinf:` | 19 643 392 |
| Go toolchain | `go1.25.12` | buildinfo `@+32`; also 13 112 464 |
| module path | `github.com/github/github-mcp-server/cmd/github-mcp-server` | buildinfo `@+60` |
| **module version** | **`v1.6.0`** | buildinfo `@+163` |
| VCS | `vcs=git`, `vcs.revision=7629b6e7337e1fc4b11a0ca5fdea4af4edd21f6e`, `vcs.time=2026-07-15T11:01:54Z`, `vcs.modified=false` | 13 272 400 area |
| build flags | `-buildmode=exe -compiler=gc -trimpath=true CGO_ENABLED=0 GOARCH=amd64 GOOS=windows GOAMD64=v1` | 13 272 469+ |
| notable deps | `github.com/aymerick/douceur v0.2.0`, `fsnotify v1.9.0`, `spf13/cobra v1.10.2`, `spf13/pflag v1.0.10`, `spf13/viper v1.21.0`, `subosito/gotenv v1.6.0`, `yosida95/uritemplate/v3 v3.0.2`, `go.yaml.in/yaml/v3 v3.0.4`, `golang.org/x/net v0.55.0`, `x/oauth2 v0.35.0`, `x/sync v0.20.0`, `x/sys v0.45.0`, `x/text v0.37.0`, `x/time v0.15.0` | 13 271 500-13 272 600 |

## Subcommand / CLI surface

- `list-scopes --toolsets=repos,issues,pull_requests|all --output=json|summary` (`@12027646`-`@12027899`)
- `--toolsets` (`@11763640`, `@11846437`, `@11904043`), `--output`
- OAuth: `--oauth-client-id`, `--oauth-callback-port`, `authentication required: set
  GITHUB_PERSONAL_ACCESS_TOKEN, or pass --oauth-client-id to log in via OAuth` (`@11950152`)
- README table embedded: `| \`default\` | Default toolset | https://api.githubcopilot.com/mcp/ | …`
  (`@12008548`) — i.e. the same binary is also the hosted remote-MCP server.

## How the desktop launches it

`index.chunk-CQr0Ee4m.js` (3 411 B) — `connectGithubBuiltinMcp` (`@3335`):

```js
let l="github-mcp-server.exe", u="CLAUDE_DESKTOP_GITHUB_MCP_BINARY";
function d(){ return app.isPackaged
   ? join(process.resourcesPath,"app.asar.unpacked","resources","github-mcp",l)
   : process.env[u] || join(app.getAppPath(),"resources","github-mcp",l) }         // path helper; name/flag literals at @814 / @841
function f(e,t){ let n={GITHUB_PERSONAL_ACCESS_TOKEN:t};
   if(e.host!==undefined) n.GITHUB_HOST=e.host;
   if(e.toolsets!==undefined) n.GITHUB_TOOLSETS=e.toolsets;
   if(e.readOnly===true) n.GITHUB_READ_ONLY="1";
   return n }                                                                       // env builder; GITHUB_PERSONAL_ACCESS_TOKEN @1098, GITHUB_HOST @1157, GITHUB_TOOLSETS @1201, GITHUB_READ_ONLY @1249
…
let x=t.H0({cmd:g, args:["stdio"]});                     // command resolution
let S=new t.I1({command:x.cmd,args:x.args,env:t.X1(t.F1(),b),stderr:"pipe"});  // SDK StdioClientTransport
let C=new t.$1({name:t.Z1,version:app.getVersion()},{capabilities:{}});
await C.connect(S,{signal:w.signal,timeout:p});          // p = 60000 ms
({tools:E}=await C.listTools(…))
```

- **Default env: `GITHUB_PERSONAL_ACCESS_TOKEN` required.** If no token is cached,
  `new t.JY(e.name)` with `code="EAUTHREQUIRED"` is thrown and replaced by
  `makeGithubNeedsAuthShell(...)` (needs-auth shell UI).
- Optional `GITHUB_HOST`, `GITHUB_TOOLSETS`, `GITHUB_READ_ONLY=1`.
- Token is persisted encrypted (`readGithubBuiltinToken` / `writeGithubBuiltinToken` /
  `clearGithubBuiltinToken`, `index.chunk-DCgdwyFw.js`), validated server-side
  (`validateGithubToken`), and revoked on 401 (`onToolCallError` → `revoked:true`).
- Spawn failure texts: `[github-mcp] the bundled GitHub server is not included in this build
  (expected at <path>)` / `binary is missing at <path> — run with a populated
  resources/github-mcp/manifest.json, or set CLAUDE_DESKTOP_GITHUB_MCP_BINARY=<path>`.
  (No `manifest.json` exists on this machine — only the .exe.)

## Tool inventory (S: 137 name literals confirmed in the binary)

Original strings are the Go tool registry; the binary also carries per-tool Cobra metadata
(title/description fragments) which is why some literals appear glued to neighbors
(e.g. `"List issueslist_issues"`).

Confirmed tool names (offsets in the .exe; full list in `MCP-TOOLS.tsv`):

**context / me** — `get_me` (9246501), `get_teams` (11661707), `get_team_members` (11688801)

**repos / files** — `create_or_update_file` (11714377), `search_repositories` (11703509),
`create_repository` (11693767), `get_file_contents` (11693784), `fork_repository` (11685002),
`create_branch` (11677337), `list_branches` (11677311), `list_commits` (11673444),
`get_commit` (9195780), `get_tag` (11652809), `list_tags` (11661959), `list_releases` (11677363),
`get_latest_release` (11698384), `get_release` (11698402), `get_release_by_tag` (11698402),
`push_files` (11665674), `delete_file` (11669654), `get_repository_tree` (11703205),
`search_code` (11669720), `get_repository` (11703205),
`list_starred_repositories` (11737422), `star_repository` (11685047),
`unstar_repository` (11693835), `get_files` (11661896), `get_file_blame` (11680970),
`list_repository_collaborators` (11763393), `get_commits` (11669599), `search_commits` (11681040),
`commit_comment` (9517781), `get_comment` (11673264)

**issues** — `create_issue` (11673348), `list_issues` (11669533), `get_issue` (not a literal; provided via `issue_read`),
`update_issue` (11693631), `add_issue_comment` (11693614), `search_issues` (11677181),
`list_issue_types` (11688945), `issue_read` (11665434), `issue_write` (11669511),
`sub_issue_write` (11684807), `add_sub_issue` (11677233), `remove_sub_issue` (11689041),
`reprioritize_sub_issue` (11719953), `assign_copilot_to_issue` (11725243),
`list_issue_fields` (11693546), `get_issue_field` ≡ `get_project_field` (11693410),
`create_issue_field`/`update_issue_field` ≡ field-write group (11703015-11703053),
`delete_issue_field`, `set_issue_fields` (11689073), `get_issue_field_values`,
`add_issue_field_values`, `delete_issue_field_values`, `create_iteration_field` (11719997),
`add_issue_reaction` (11698168), `add_issue_comment_reaction` (11743401), `get_issue_comments`,
`update_issue_type` (11693682), `update_issue_assignees` (11719865), `update_issue_milestone` (11719887),
`update_issue_labels` (11703300), `update_issue_title` (11698096), `update_issue_state` (11698150),
`update_issue_suggestions` (11732276)

**pull requests** — `create_pull_request` (11703376), `list_pull_requests` (11698294),
`merge_pull_request` (11698330), `get_pull_request*` via `pull_request_read` (11693699),
`update_pull_request` (11703395), `update_pull_request_branch` (11743609),
`create_pull_request_review` (11743687), `create_pending_pull_request_review` ≡ `pull_request_review_write` (11737172),
`add_comment_to_pending_review` (11763190), `submit_pending_pull_request_review` (11797515),
`delete_pending_pull_request_review` (11797583), `add_reply_to_pull_request_comment` (11790806),
`request_copilot_review` (11719623), `pull_request_review_comment` (11749469),
`update_pull_request_title` (11737197), `update_pull_request_body` (11731892),
`update_pull_request_state` (11737247), `update_pull_request_draft_state` (11777408),
`request_pull_request_reviewers` (11770355), `add_pull_request_review_comment` (11777532),
`resolve_review_thread` (11714335), `unresolve_review_thread` (11725795), `get_review_comments` (11703357),
`search_pull_requests` (11708896)

**actions / workflows** — `list_workflow_runs` (11697898), `list_workflow_jobs` (11697916),
`get_workflow_run` (11688673), `get_workflow_job` (11688689), `get_workflow_run_logs` (11713894),
`get_workflow_run_usage` (11719469), `get_workflow_job_logs` (11713915),
`get_workflow_run_logs_url` (11736847), `download_workflow_run_artifact` (11769665),
`list_workflow_run_artifacts` (11749415), `run_workflow` (9744413),
`rerun_workflow_run` (11697934), `rerun_failed_jobs` (11693393), `cancel_workflow_run` (11702996),
`delete_workflow_run_logs` (11731532), `get_job_logs` (11673204), `list_workflows` (11680648)

**security** — `get_code_scanning_alert` (11725174), `list_code_scanning_alerts` (11736897),
`get_secret_scanning_alert` (11737522), `list_secret_scanning_alerts` (11750306),
`get_dependabot_alert` (11708616), `list_dependabot_alerts` (11719667),
`get_global_security_advisory` (11756886), `list_global_security_advisories` (11777842),
`list_repository_security_advisories` (11803811), `get_code_quality_finding` (11731604)

**notifications** — `list_notifications` (11698222), `get_notification_details` (11731796),
`dismiss_notification` (11708796), `mark_all_notifications_read` (11749901),
`manage_notification_subscription` (11783729), `manage_repository_notification_subscription` (11846046)

**orgs / users** — `search_orgs` (11669731), `list_org_repositories`, `list_org_members`,
`search_users` (11673504)

**discussions** — `get_discussion` (11680718), `list_discussions` (11688849),
`get_discussion_comments` (11725335), `list_discussion_categories` (11743089),
`discussion_comment_write` (11731676)

**gists** — `list_gists` (11665384), `get_gist` (11657760), `create_gist` (11669390),
`update_gist` (11669412)

**labels** — `get_label` (11661833), `list_label` (11665534), `create_label`, `update_label`,
`delete_label`, `label_write` (11669566)

**projects** — `get_project` (11669236), `list_project_fields` (11703015), `get_project_field` (11693410),
`list_project_items` (11697952), `add_project_item` (11688721), `update_project_item` (11703034),
`delete_project_item` (11703053), `get_project_status_update` (11737097),
`create_project_status_update` (11756326)

**UI variants** — `issue_read_ui`, `issue_write_ui` (11681096), `pr_write_ui` (11669819)

**Counts (S): 137 unique name literals confirmed present in the binary.**
Cross-check: the app's own builtin GitHub tool-policy map (`index.chunk-lzaSYO3Q.js@fOe`,
`@~600800`) names 39 GitHub tools as `"ask"` — all of them appear in the binary
(e.g. `create_or_update_file`, `delete_file`, `push_files`, `merge_pull_request`,
`create_and_submit_pull_request_review`, `run_workflow`, `rerun_failed_jobs`,
`cancel_workflow_run`, `delete_workflow_run_logs`, `dismiss_notification`, `add_project_item`, …),
which independently confirms the naming scheme.

## Gating

Same builtin rule as office365: `Bat()` requires `source==="admin"`; then case `"github"`:
```js
const {readGithubBuiltinToken, writeGithubBuiltinToken, clearGithubBuiltinToken,
       validateGithubToken, makeGithubNeedsAuthShell} = require("./index.chunk-DCgdwyFw.js")
let d = await readGithubBuiltinToken(dir, e);
if (d!==undefined && await validateGithubToken(e,d)==="invalid") { drop }
if (sessionStale()) throw Error("[github-mcp] connect superseded by sign-out");
await connectGithubBuiltinMcp(e, dir, d, n, r)   // n = timeout, r = opts
```
Its `e.clientId`, `e.host`, `e.toolsets`, `e.readOnly` come from the managed config schema
`iOe` (`@597208`): `clientId` required (≤36 chars `[A-Za-z0-9._-]`), `host` must be
https non-loopback, `scope` (lowercase scope tokens), `toolsets`, `readOnly`.

## Verdict on "wired in"

| stage | reached | evidence |
|---|---|---|
| packaged | yes | `.exe` at `app.asar.unpacked\resources\github-mcp\` |
| registered | yes | `index.chunk-lzaSYO3Q.js@1469369` builds the `case "github"` spawner; `index.chunk-CQr0Ee4m.js` is a real, shipped code chunk |
| delegated | yes (code path) | SDK `StdioClientTransport` with `args:["stdio"]` |
| invoked | **NO on this machine (U)** | requires (a) a managed `managedMcpServers` entry with `server:"github"` + `clientId`, or the 1p pool gate; (b) a cached GitHub token. `%APPDATA%\Claude\claude_desktop_config.json` contains only `preferences` (no `mcpServers`), and there is no `connectors/` dir → no builtin entry exists, so the binary is never launched. Also note GitHub is **not** in the 1p allow-list: `managedMicrosoft365Configs()` filters with `zvn(e)` = `e.server==="microsoft365"` only (`@2877169`), so the 1p consumer connector pool can never spawn it. In a **3p** deployment the pool input is `yC()? Evn(cOe(K().mcp?.managedServers)) : this.creds?.mcpServers ?? []` (`@2870520`) — `Evn()` strips every builtin entry — so GitHub would only appear if the deployment's bootstrap credential bundle (`creds.mcpServers`) supplied it, and `Bat()` would then accept it as `source:"admin"`. |
