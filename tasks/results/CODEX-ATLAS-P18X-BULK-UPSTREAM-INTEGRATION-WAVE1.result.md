# CODEX-ATLAS-P18X-BULK-UPSTREAM-INTEGRATION-WAVE1 — Result

Date: 2026-09-28
Base branch: `main`
Base HEAD: `fc49ae70f47c60ca172c951304e382fc8c03cca5`
Outcome: **DEGRADED — integration surface and packaged registry are implemented; several current-machine smokes are blocked or partial.**

## Delivered

- Added one normalized `CapabilityBus`, exposed at `GET /api/integrations`, with enable/disable support at `PATCH /api/integrations/{capability_id}/enabled` and an API-backed Integration panel in Settings.
- Added the shared `AgentBackend` session contract, an ACP process adapter, a generic external-process adapter, a Pi JSON-RPC adapter, and backend/session/prompt/cancel/resume API routes.
- Registered P18A FULL_ACCESS, CUA tools/calls, pywinauto window discovery, Browser Use, ast-grep, Aider Repo Map, and DBOS status with Atlas Native Agent capabilities.
- Added pinned upstream MCP server examples for Playwright, Chrome DevTools, and Serena. Updated the packaged backend build to collect P18X Python runtime packages and their metadata. The desktop process passes the locked npm integration versions to the packaged backend registry.
- Kept P18A local execution, P18B native computer use, P15 Skills, P7F MCP, and P17 packaging code paths in place.

## Version, source, license, and adapter log

| Integration | Version | Upstream / license | Install or detection | Atlas adapter |
|---|---|---|---|---|
| Cua Driver | 0.28.2 | `trycua/cua` · Apache-2.0 | `pip install` in `core/.venv` | `core/atlas/capabilities/computer/cua_backend.py` |
| pywinauto | 0.6.9 | `pywinauto/pywinauto` · BSD-3-Clause | `pip install` in `core/.venv` | `core/atlas/capabilities/computer/uia_backend.py` |
| Browser Use | 0.13.10 | `browser-use/browser-use` · MIT | `pip install` in `core/.venv` | `core/atlas/capabilities/browser/browser_use.py` |
| Playwright MCP | 0.0.45 | `microsoft/playwright-mcp` · Apache-2.0 | pinned frontend npm dependency; pinned `npx` example | Atlas `MCPClient` |
| Chrome DevTools MCP | 1.9.0 | `ChromeDevTools/chrome-devtools-mcp` · Apache-2.0 | pinned frontend npm dependency; pinned `npx` example | Atlas `MCPClient` |
| Serena | 1.7.0 | `oraios/serena` · MIT | detected installed CLI; MCP example uses `serena start-mcp-server` | Atlas `MCPClient` |
| ast-grep | 0.45.3 | `ast-grep/ast-grep` · MIT | pinned frontend npm dependency | `core/atlas/capabilities/coding/ast_grep.py` |
| Aider Repo Map | 0.86.2 | `Aider-AI/aider` · Apache-2.0 | `uv tool install aider-chat==0.86.2` | `core/atlas/capabilities/coding/repo_map.py` |
| DBOS | 3.0.0 | `dbos-inc/dbos-transact-py` · MIT | `pip install` in `core/.venv` | `core/atlas/capabilities/durable/dbos_backend.py` |
| ACP Python SDK | 0.12.1 | `agentclientprotocol/python-sdk` · Apache-2.0 | `pip install` in `core/.venv` | `core/atlas/runtime/backends.py` |
| Codex CLI | 0.155.0-alpha.16.4 | `openai/codex` · Apache-2.0 | detected local CLI | `core/atlas/agents/backends/codex.py` via ACP package 1.13.1 |
| Claude Agent SDK | 0.2.157 | `anthropics/claude-agent-sdk-python` · MIT | `pip install` in `core/.venv` | `core/atlas/agents/backends/claude.py`; Claude ACP package 0.81.2 |
| Hermes Agent | 0.21.4, upstream `ec21bd76`, local `e335a697` (+4 carried commits) | `NousResearch/hermes-agent` · MIT | detected local CLI | `core/atlas/agents/backends/hermes.py` |
| Pi | 0.73.1 | `badlogic/pi-mono` · MIT | pinned frontend npm dependency | `core/atlas/agents/backends/pi.py`, `core/atlas/runtime/external_process.py` |
| ZCode | version probe failed | `zcode-ai/zcode` · proprietary CLI | detected local CLI; `--version` exits 1 | `core/atlas/agents/backends/zcode.py` |

The Codex and Claude ACP npm package pins are `@agentclientprotocol/codex-acp@1.13.1` and `@agentclientprotocol/claude-agent-acp@0.81.2` (Apache-2.0). The frontend dependency lock contains the exact npm versions above.

## Integration matrix

| Component | Install | Discover | Start | Basic call | Cross-call | Packaged | Error / remaining work |
|---|---|---|---|---|---|---|---|
| Atlas Native + P18A FULL_ACCESS | Ready | Ready | Ready | Existing local runtime exercised by regression suite and temp-file smoke | P18A file read/write with ast-grep rewrite | Registry loaded | External backends do not yet receive the full P18A tool set through a shared MCP bridge |
| Cua Driver | Ready | Ready | Driver connected; 56 tools discovered | Desktop state and Notepad window observation worked; marker text appeared in the isolated tab, but the saved file did not read back the marker | Not counted as a passing chain | Packaged record ready | **Partial**: current CUA type/save path did not pass Notepad file verification; isolated tab was closed and temp file removed |
| pywinauto | Ready | Ready | UIA enumerated 23 visible windows | Passed | Used to inspect isolated Notepad state | Packaged record ready | None for enumeration smoke |
| Browser Use | Ready | Ready | Headless session started against a local HTTP page | Page text inspection passed | Complementary browser chain below | Packaged record ready | This smoke covered open/inspect; Browser Use fill/click is not implemented in this adapter |
| Playwright MCP | Ready | Ready; 21 tools | Server connected | Local page navigated; input set, button clicked, DOM result read back | Separate deterministic local-page chain passed | Packaged registry ready; server starts from pinned `npx` config | No in-app server auto-start smoke; test was isolated through `MCPClient` |
| Chrome DevTools MCP | Ready | Ready; 29 tools | Headless server connected | Opened local page and found `p18x-console` in console output | Same deterministic local-page fixture | Packaged registry ready; pinned config tested without unsupported `--no-update-checks` | None for page/console smoke |
| Serena | Ready | Ready; 22 MCP tools | Started against temp project | `find_symbol` found `calculate_total` in `sample.py` | Symbol inspection was performed on the same temp fixture used for coding checks | Packaged registry identifies external CLI | No semantic edit smoke; example uses current `claude-code` context name |
| ast-grep | Ready | Ready | Windows binary resolved from pinned npm package | AST search and rewrite both passed on a temporary Python fixture | P18A write → ast-grep rewrite → P18A readback passed | Packaged registry ready | Search requires a matching AST pattern; an initial non-matching pattern was corrected |
| Aider Repo Map | Ready | Ready | CLI ran on a temporary fixture repo | Repo map returned successfully | Map consumed as the coding context for the temporary fixture chain | External CLI remains outside installer | Initial console encoding failure was fixed by forcing UTF-8 in the adapter. Direct Aider smoke generated `.aider` cache/history artifacts in the workspace; cleanup was rejected by tool policy and they remain untracked |
| DBOS | Package ready | Ready; version known | **Blocked**: Docker CLI exists but Docker Linux engine pipe is absent; no `DBOS_SYSTEM_DATABASE_URL` | Status API reports misconfigured | No durable checkpoint/resume chain | Packaged record loaded as misconfigured | No isolated PostgreSQL service could be started, so A/B crash-resume smoke was not run |
| ACP host | SDK and wrappers installed | Ready | Generic process lifecycle exercised with a local echo child; no authenticated Codex/Claude ACP session | Normalized streaming/cancel contract covered by tests | Pi uses the same process/event layer | Registry ready | Codex and Claude ACP upstream handshakes/prompts not completed due local authentication/CLI blockers |
| Codex | CLI and ACP wrapper installed | Version detected | **Blocked**: `codex login status` reports not logged in | No prompt/edit call | None | Packaged record is misconfigured | Login required |
| Claude Agent SDK | SDK and Claude ACP wrapper installed | Ready | SDK attempt failed with `CLIConnectionError` | No response received | None | Packaged registry ready | Claude CLI auth status exited 1; local CLI handshake remains blocked |
| Hermes Agent | CLI detected | Version detected | Adapter process protocol not smoke-tested | No prompt response claimed | None | External CLI record ready | Generic stdin adapter may not match every Hermes CLI protocol; verify in the concentrated integration-debug wave |
| Pi | Package installed | Ready | RPC process started in a temporary cwd | Real no-tools, single-turn prompt streamed and returned `P18X_PI_SMOKE_OK` | Temp-repo session; no files changed | Packaged registry ready and uses bundled `npx` fallback when app resources do not contain `node_modules` | Pi is flagged by the current npm audit; see risks below |
| ZCode | CLI command detected | Version unknown | Start not attempted because version probe exits 1 | No prompt call | None | Packaged record reports failed, rather than missing | Resolve CLI version/protocol in next debug wave |

Packaged smoke: rebuilt the backend with the P18X PyInstaller collections, launched it with an isolated data root and disabled MCP auto-start, and queried `GET /api/integrations` and `GET /api/agent/capabilities`. The packaged registry returned 17 records (14 ready, 3 degraded); CUA tool call registration was present. The three reported degraded records were DBOS (no DB URL), Codex (not authenticated), and ZCode (version probe failure).

## Verification

- `ruff check` on changed Python modules: passed.
- `pytest core/tests/test_p18x_integrations.py core/tests/test_local_execution.py core/tests/test_computer_use.py core/tests/test_mcp_client.py -q --basetemp <unique temp> -p no:cacheprovider`: **42 passed**.
- `npm run build --prefix frontend`: passed; Vite reports the existing >500 kB chunk-size warning.
- `npm test --prefix frontend`: **5 files, 18 tests passed**.
- `pip check`: passed after dependency installation.
- `git diff --check`: passed (Git reports only LF→CRLF working-copy notices).
- `npm audit --omit=dev`: **2 high** findings: direct `@mariozechner/pi-coding-agent` and transitive `extract-zip`. npm proposes `0.49.3` as a semver-major downgrade from the selected `0.73.1`; no automatic audit fix was applied.

## Workspace / push status

The unrelated pre-existing untracked report `Atlas竞品对比报告_2026-09-28.docx` was preserved. Temporary PyInstaller/package-test directories, the isolated packaged DB/config, one earlier pytest basetemp, and Aider cache/history files also remain untracked: explicit `Remove-Item -Recurse` cleanup attempts were rejected by the command policy. No such files are included in the commit. The required source/result commit and `origin/main` HEAD equality are recorded in the final handoff after push.
