# Browser + Computer stack — source freeze 2026-10-03

Scope: Browser Use (Python), Stagehand (TypeScript), MCP browser servers, adjacent engines. All facts as of 2026-10-03.

## Browser Use

Repo: https://github.com/browser-use/browser-use (MIT; ~117k stars, 10.3k commits). Docs: https://docs.browser-use.com (llms.txt index available).

**Latest release: 0.13.10, 2026-09-04** (https://github.com/browser-use/browser-use/releases, https://pypi.org/project/browser-use/). No release in the 4 weeks since; tags confirmed via GitHub API (`0.13.10` is newest tag). Requires Python >=3.11,<4.0.

Release line (recent):
- **0.13.10** (2026-09-04) — "Browser Harness" upgraded to 0.1.13, all deps exact-pinned; migrated to MCP Python SDK 2.1.1; unknown MCP tool calls now error instead of silently succeeding; pypdf 6.16.2 security bump.
- **0.13.9** (2026-09-04) — `bu-2-0` restored as `ChatBrowserUse` default; CDP hardening: cookies cleared via Storage domain, WebSocket-drop fix during reconnection, early detection of browser process exit in `_wait_for_cdp_url`, session handlers restored after event-bus reset; new OrcaRouter LLM provider; clickable elements expose image context, live pre-filled input values shown to agent.
- **0.13.8** (2026-08-16) — default model `bu-2-0-mini-preview`; first-party OpenClaw skill support; MCP read-only tools get `readOnlyHint` annotations; DOM leak fixes (occluded text no longer sent to LLM).
- **0.13.7** (2026-07-27) — updated CLI; nested cross-origin iframe extraction fixes; unique selector indices across CDP sessions; React controlled-input clear fix; `file://` start URLs.
- **0.13.3** (2026-07-02) — introduced **CLI 3.0** with skills support for coding agents.

**CLI** (https://docs.browser-use.com/open-source/browser-use-cli.md): install `uv tool install browser-use` (or `uvx browser-use`); commands `browser-use --doctor`, `auth login`, `auth status`, `skill show`, `skill install`, `telemetry status`. `browser-use skill install` installs a skill (discoverable via skills.sh) so coding agents (Claude Code, Codex, Cursor) can drive the CLI. Three browser modes: (1) attach local Chrome/Chromium via CDP keeping existing tabs/cookies/extensions/logins; (2) Browser Use cloud browsers (named daemons via `start_remote_daemon("name")` / `stop_remote_daemon("name")`, select with `BU_NAME`); (3) any CDP-reachable browser via env vars `BU_CDP_URL` / `BU_CDP_WS`.

**Workflow / memory / skills:**
- **Demonstration → reusable workflow lives in the Cloud, not the OSS lib**: "rerunnable scripts" (https://docs.browser-use.com/cloud/agent/scripts.md). A Cloud run saves a script into a workspace (`client.workspaces.create(...)` → `client.runs.create({task, workspaceId})` → `client.runs.wait_for_completion(run.id)` → `client.workspaces.files(workspace.id, {prefix:"scripts/"})`, SDK path `browser_use_sdk.v4` / `browser-use-sdk/v4`). Later runs re-execute the saved script against the live site; **self-healing** = on failure/malformed output the agent re-inspects the page and repairs the saved script before returning. Reruns are live-fetch (fingerprinted via `fetched_at` / `source_sha256`), not cache-based. Legacy "Skills" API (create/refine/execute/rollback + marketplace) still exists under `/cloud/api-v2/skills/` but docs mark it retired.
- **Memory**: persistent filesystem/memory are Cloud features (sessions continue conversation via `session_id`; workspaces persist files across runs via `workspace_id`). OSS lib has no built-in long-term memory.
- **Skills (OSS)**: `browser-use skill install` ecosystem — skills are for coding agents calling the CLI; release 0.13.8 added OpenClaw skill support.

**Browser profiles**: `Browser.from_system_chrome()` auto-detects Chrome + profile cross-platform (launches Chrome in debug mode; close Chrome first). Storage state: `browser.export_storage_state('auth.json')`, load via `Browser(storage_state='auth.json')` (Playwright-format JSON, auto-saves periodically). Cloud: `cloud_profile_id` on `Browser(use_cloud=True)`; profile-sync guide at https://docs.browser-use.com/cloud/guides/profile-sync.md (syncs cookies, not IndexedDB/extensions).

**CDP attach**: `Browser(cdp_url='http://remote-server:9222')` — accepts CDP URL from any provider (incl. Browserbase); combinable with `ProxySettings`. CLI env vars `BU_CDP_URL`/`BU_CDP_WS` for attach-to-existing-Chrome.

**Multi-tab / dialogs / upload / download**: built-in tools (https://docs.browser-use.com/open-source/customize/tools/available.md) include `switch` (switch tabs), `close` (close tabs), `upload_file`, `navigate`, `go_back`, `scroll`, `find_text`, `extract`, `click`, `input`, `evaluate`, `screenshot`, `dropdown_options`, `select_dropdown`, `send_keys`, `wait`, `done`. No dedicated dialog tool documented (dialogs handled at harness level; `send_keys` Escape available). Downloads: Cloud API has `list-browser-session-downloads`; OSS side is via file tools (`write_file`/`read_file`/`replace_file`) + `Tools()` decorator for custom actions (`@tools.action`).

**Last ~6 weeks highlights**: releases 0.13.8–0.13.10 (Aug 16 / Sep 4) = CDP reconnect hardening, MCP SDK 2.1.1, Browser Harness 0.1.13, OpenClaw skill; blog: Stripe Link CLI in-agent payments (Sep 3), x402/USDC crypto payments with Coinbase (Aug 6), long-horizon RL environments (Aug 26). Default agent model family is `bu-2-0` / `bu-2-0-mini-preview` via `ChatBrowserUse`.

## Stagehand

Repo: https://github.com/browserbase/stagehand. Docs: https://docs.stagehand.dev (v2/v3/v4 versioned).

**Latest release: @browserbasehq/stagehand 4.1.0, published 2026-09-09 on npm** (verified via npm registry; 4.0.3 also published 2026-09-09). Note the GitHub "Latest" release tag still points at the v3 line, `@browserbasehq/stagehand@3.7.3` (2026-08-28, MCP SDK 1.30, cross-frame XPath fix); v4 ships via npm while 4.2.0 is in continuous alpha (latest `4.2.0-alpha-*` builds 2026-10-01/02 — active daily development).

**v4** (https://docs.stagehand.dev/v4): runs on CDP directly — **no Playwright/Puppeteer dependency**; SDKs for TypeScript, Python, and **Go** (new). Primitives: `act`, `extract` (schema-validated), `observe`; Playwright-style page methods (`goto`, `click`, `type`, `locator`, `fill`, `keyPress`); `stagehand.browser.context.activePage()`; `metrics()` for per-method token/inference timing.

**Caching (server-side, "Browserbase Cache")** — https://docs.stagehand.dev/v4/best-practices/caching.md:
- Caches eligible `act()`/`observe()`/`extract()` calls; hits return with **zero LLM inference/tokens**. On by default when running on Browserbase (no effect on local browsers).
- Cache key = instruction + page content + options (model config excluded, so model swaps don't invalidate). URL is in the key (query-param sort normalization added in 3.6.0).
- Enable/tune: `Stagehand.create({ cache: false })` or `{ cache: { threshold: 2 } }`; per-call `{ cache: false }`. Inspect via `metadata.cache.status` ∈ `"HIT"|"MISS"|"DISABLED"` (+ `missReason`, tokens saved). Calls using `locator`/`ignoreLocators` are never cached.

**Replay / deterministic workflows**: passing an `Action` from `observe()` into `act()` replays deterministically — no inference, no snapshot, no cache. The fuller pattern (v3 docs, still the mental model): `new Stagehand({ env: "BROWSERBASE", cacheDir: "cache/workflow" })` auto-caches an agent run; first run pays exploration cost, later identical runs replay from cache ("10-100x faster, zero tokens"); `stagehand.history` API for analyzing/filtering what ran (https://docs.stagehand.dev/v3/best-practices/deterministic-agent.md).

**Self-healing**:
- `new Stagehand({ selfHeal: true })` — when a replayed/recorded selector no longer resolves, Stagehand re-infers the action and retries once (referenced in act + deterministic-agent docs).
- **Agent fallbacks** (https://docs.stagehand.dev/v3/best-practices/agent-fallbacks.md): try `stagehand.act("...")` in a `try`; on error, invoke `agent.execute({ instruction, maxSteps: 10 })` (agent configured with `model: "anthropic/claude-sonnet-4-6"`, optional `systemPrompt`) to find the new path; re-throw if fallback also fails.

**Other v3/v4 notes**: v3.7.x line fixed CUA coordinate normalization to actual viewport, released `useTouch`, added `openaiEndpointFormat` (Chat Completions). Separate **browse** CLI (v0.9.6, Aug 3) and **server-v3** MCP server (v3.7.6, Aug 28 — iframe XPath coordinate fix).

## MCP browser servers

**Playwright MCP** (https://github.com/microsoft/playwright-mcp): latest **v0.0.83, 2026-09-28**. Very active (releases every 1-2 weeks). Recently added: `browser_start_recording`/`stop_recording` tools that return generated Playwright code from user actions (v0.0.80, Sep 1 — effectively in-browser test/workflow recording), WebMCP page tools exposed as real MCP tools (`webmcp_<tool>`, v0.0.81/82), 60fps styleable video recording (v0.0.82), `browser_emulate_media`, `--idle-timeout` auto-close for headless, `browser_find` accessibility-tree search, dialog reporting during page load instead of timing out, download-crash and Docker orphan-process fixes (v0.0.83). Accessibility-snapshot-based (not vision), tab-capable, codegen for python/java/csharp.

**chrome-devtools MCP** (https://github.com/ChromeDevTools/chrome-devtools-mcp): latest **v1.10.1, 2026-09-23** (52.9k stars). Very active. Focus has shifted toward deep debugging/perf: heap snapshot query/compare/dominators tools, `get_css_style` + CSS formatter, config file support, MCP SDK v2 migration, chunked trace parser for large recordings (v1.10.0), "Agent Plugins 1.0" package + cookie-debugging skill + configurable filesystem roots (v1.9.0), PWA automation tools + multi-file upload (v1.8.0), Lighthouse integration. Ships its own skills folder; connects to a running Chrome instance.

## Others

- **Camoufox** (https://github.com/daijro/camoufox) — alive and active. Firefox-fork anti-detect browser; latest GitHub browser build `v152.0.4-beta.30` (2026-09-01); Python launcher `camoufox` 0.5.6 stable (2026-09-06) with 0.5.7b1–b4 pre-releases (2026-09-30) on PyPI (https://pypi.org/project/camoufox/). Still carries "under development, may not be production-stable" warning; cannot fully spoof Chromium/JSSpec fingerprints.
- **Lightpanda** (https://github.com/lightpanda-io/browser) — alive and very active (~35.8k stars); **hit 1.0.0 on 2026-10-02**. Zig-built headless browser with v8 JS, CDP + WebDriver BiDi, MCP server, nightly rolling builds; no native Windows (WSL2/Docker only), glibc-linked Linux binaries.

## Notes for Atlas X2

1. **Browser Use (Python) remains the strongest OSS agent loop**: pin `browser-use==0.13.10` (2026-09-04). CDP attach is one-liner `Browser(cdp_url=...)` or attach-to-user-Chrome via `Browser.from_system_chrome()` / CLI `BU_CDP_URL`. Multi-tab via `switch`/`close` tools; `upload_file` built in; downloads easiest through Cloud or custom `@tools.action`.
2. **"Record once, replay, self-heal" does NOT exist as a local API in browser-use** — that capability is Cloud-only (workspace scripts with agent-repair-on-failure). If Atlas wants local demonstration→replay, it must build it (e.g., capture agent action history → deterministic replay with LLM re-plan on failure), or use the Cloud scripts API (`browser_use_sdk.v4`: `workspaces.create` / `runs.create` / `workspaces.files`).
3. **Stagehand v4 (4.1.0) is the one with first-class caching/replay/self-heal**: `Stagehand.create({ cache: {threshold}, selfHeal: true })`, `observe()`→`act()` deterministic replay, `metadata.cache.status` observability, agent fallback via `agent.execute()`. Caveats: cache/self-heal are server-side Browserbase features (no local effect); v4 is CDP-native (dropped Playwright), TS/Python/Go. GitHub releases lag npm — track npm `dist-tags.latest`.
4. **Playwright MCP is the recording source**: `browser_start_recording`/`stop_recording` → generated Playwright code is a plausible Atlas "teach by demonstration" input; chrome-devtools MCP is now mostly a perf/heap/CSS debugging sidecar — opt-in, not core.
5. Anti-detect/stealth: Camoufox usable but beta-grade and Firefox-only; Lightpanda just reached 1.0 but lacks Windows-native — neither ready to be Atlas's default engine; keep Playwright-managed Chromium default + Camoufox opt-in.
6. Watch: Stagehand 4.2.0 (alpha daily, since 2026-09-18); browser-use has been quiet for 4 weeks after 0.13.10 (next release likely significant); Playwright MCP video recording at 60fps is useful for Atlas run traces.
