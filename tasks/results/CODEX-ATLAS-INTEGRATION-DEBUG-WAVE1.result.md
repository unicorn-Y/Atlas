# CODEX-ATLAS-INTEGRATION-DEBUG-WAVE1 Result

## Outcome

Implemented the shared Atlas integration paths and repaired the false-ready and Windows command-launch issues within this wave. The code changes, regression checks, packaged MCP/API checks, and available real-call smokes completed. Components blocked by machine authentication/configuration are reported as degraded below.

## Fixed blockers

- ACP permissions now select the broadest protocol-provided allow choice (prefer `allow_always`) under Atlas FULL_ACCESS; the callback has independent regression coverage.
- Added one shared Atlas MCP bridge for P18A local execution, P18B Computer Use, and coding tools. ACP sessions receive the bridge descriptor. Packaged `--atlas-mcp-bridge` runs over stdio without logging to protocol stdout.
- Fixed Windows `.cmd` launch/version detection for ACP/npm/npx commands, including ZCode version detection. ACP startup failures clean up the manager.
- Hermes now uses its installed `hermes acp` protocol rather than a guessed line protocol.
- ZCode uses the installed CLI's actual one-shot prompt flags and reports missing provider configuration as misconfigured.
- CUA structured JSON element handles are preserved through the backend response path.
- Added Browser Use's upstream Agent task path (`browser_task`) while retaining BrowserSession behavior.
- Integration status now separates installed, available, configured/authenticated, connected, and smoke-verified; version detection alone does not mark an agent ready.
- Frozen ast-grep resolution now honors `ATLAS_ROOT` and bundled package roots.
- Added focused regressions for ACP options, bridge tools, Windows command shims, structured CUA results, API readiness, Browser Use, and packaged-path resolution.

## Real-call evidence and final integration matrix

| Component | Discover | Start | Real call | Atlas bridge | Packaged | Result |
|---|---|---|---|---|---|---|
| Codex | CLI `0.155.0-alpha.16.4` | CLI available | `codex login status` reports unauthenticated | Shared bridge available | Registry/API verified | DEGRADED: local auth absent; configured=false, misconfigured |
| Claude | `claude-agent-sdk==0.2.157`; ACP wrapper `@agentclientprotocol/claude-agent-acp@0.81.2` | npx version path fixed; ACP initialization timed out before session | No prompt reached | Shared ACP bridge configured | Registry/API verified | DEGRADED: startup timeout; no evidence of a real prompt; no auth value printed |
| Hermes | Installed CLI | `hermes acp` session started | Real prompt completed and called Atlas `local_file`; `atlas_local_tool_round_trip=true` | PASS | Registry/API and packaged bridge verified | PASS |
| Pi | `@mariozechner/pi-coding-agent@0.73.1` | RPC mode | One-shot prompt returned `ATLAS_PI_WAVE1_OK` | Shared bridge path retained | Registry/API verified | PASS |
| ZCode | Installed CLI version `0.16.9` | Isolated real prompt attempted | CLI failed because `D:\zcode\resources\glm\zcode-builtin.json` and fallback `D:\config\provider\zcode-builtin.json` are absent | Shared bridge path configured | Registry/API verified | DEGRADED: provider setup missing; configured=false. Existing user workflow was preserved |
| CUA | CuaDriver selected; native P18B and pywinauto fallback remain | Reused existing Notepad process | Launched/observed, typed a unique marker, saved, and read back exact contents using P18A `local_file` | PASS | Packaged CUA tools listed | PARTIAL: workflow/readback passed; closing only the test tab could not be confirmed. Existing Notepad process and user tabs were preserved |
| Browser Use | Pinned upstream package available | Deterministic local BrowserSession opened | Agent task returned HTTP 403 `token_rejected`; fill/click effect not achieved | N/A | Registry/API verified | DEGRADED: model credential rejected; BrowserSession adapter retained |
| Playwright MCP | Installed/registered | Not individually connected | Not run | MCP bridge does not replace MCP service credentials | Registry/API verified | Registered; connection/smoke unverified |
| DevTools MCP | Installed/registered | Not individually connected | Not run | MCP bridge does not replace MCP service credentials | Registry/API verified | Registered; connection/smoke unverified |
| Serena | Installed/registered | Not individually connected | Not run | Shared tools include coding capabilities | Registry/API verified | Registered; connection/smoke unverified |
| ast-grep | Bundled executable discovered | Packaged tool process started | Packaged MCP `coding_ast_grep --version` exited 0 (`0.45.3`) | PASS | PASS | PASS |
| Repo Map | Registered coding tool | Packaged tool process started | Packaged MCP `coding_repo_map` exited 0 with nonempty output | PASS | PASS | PASS |
| DBOS | `3.0.0` installed | Not started | No durable-task smoke | N/A | Registry/API verified | DEGRADED: `DBOS_SYSTEM_DATABASE_URL` absent and no local PostgreSQL service/listener available |

Packaged verification before generated-artifact cleanup: backend package built; isolated `/api/integrations` returned HTTP 200 with 17 entries and all required status fields; packaged MCP bridge listed 12 tools; `local_file` exact round-trip, ast-grep, and Repo Map calls passed. Test-launched backend processes were cleaned up. Generated package/build/test/Aider artifacts were removed afterward.

The CUA test file was removed from disk. The test tab may still be open in the user's pre-existing Notepad process; closing that tab was not verified, so the whole process and user tabs were left untouched.

## Validation

- Focused regression command: `python -m pytest tests/test_p18x_integrations.py tests/test_local_execution.py tests/test_computer_use.py tests/test_mcp_client.py tests/test_mcp_runtime_live.py tests/test_server.py -q -p no:cacheprovider --basetemp=.pytest-temp-wave1` — **106 passed, 2 skipped**.
- Ruff on every changed Python source/test file — **passed**.
- Repository-wide Ruff — **not clean due to 53 pre-existing findings in untouched files** (E501 21, UP017 18, F401 8, I001 3, UP042 2, UP035 1).
- `pip check` — **No broken requirements found**.
- `git diff --check` — **passed**.
- Packaged backend/API/MCP checks — **passed as detailed above**.
- Frontend was not changed; no frontend test/build was required by the taskbook.

## Dependencies and audit

- Dependency changes: **none**.
- Current Pi package and registry latest are both `0.73.1`; no upgrade/downgrade was made.
- `npm audit` reports **2 high findings**: Pi Agent predictable temporary extension path and `extract-zip` symlink traversal. npm's suggested fix is a SemVer-major downgrade to Pi `0.49.3`; it was not applied because it would downgrade functionality and was not a safe compatible upgrade.

## Delivery

Implementation commit: `6b10807` (`fix(atlas): integrate external agent capabilities`).
The result artifact is committed separately after this implementation commit. Push and remote HEAD verification are performed after both commits; final delivery reports the verified remote SHA.
