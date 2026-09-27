# CODEX-ATLAS-P17A-CLEAN-FIRST-RUN-DAILY-USABILITY-ACCEPTANCE

## Status

Completed. `BASE_HEAD`: `d4b8241f952667e58b8da4180808064f49d53117`.

## Delivered

- Packaged first launch now uses the Electron preload bridge's dynamically assigned backend URL. The preload is emitted as CommonJS for Electron's sandboxed preload loader.
- A clean install starts without auto-launching example MCP servers; users can configure servers after first launch through Atlas.
- The desktop process requests authenticated graceful shutdown from its managed backend, with process-tree termination retained as a timeout fallback.
- Local Skill Discovery can apply/remove an available Skill for later chats. Each run sends selected Skill names; the server resolves canonical content through Skill Manager/Registry activation and enforces lifecycle/dependency checks before adding it to the Agent context.
- OpenAI streamed completion now ends when the stream reports a terminal `finish_reason`, including stop and tool-call completion.
- Added opt-in packaged Windows acceptance coverage for two independent clean user directories, including configuration, chat, restart persistence, bundled filesystem MCP Agent read, Skill activation/context, shutdown and process cleanup.

## Acceptance

`test_clean_packaged_daily_usability_twice`: **1 passed**. The test executed the full packaged flow twice using separate clean `APPDATA`, `LOCALAPPDATA`, Atlas data/config, dynamic ports and npm caches. System Node was removed from each packaged app's `PATH`.

Each run verified first-launch settings, provider/model setup without plaintext secret echo, streaming and terminal completion, conversation persistence across restart, another post-restart turn, bundled Node `v22.23.3`, filesystem MCP tool discovery and Agent `read_file`, Registry/Discovery Skill preflight and activation, Skill instructions reaching the model request, visible tool event, graceful close, and no remaining packaged backend or bundled Node/MCP processes.

## Regression and build verification

- `core/tests/test_server.py`: **54 passed**.
- P16A live bundled Node filesystem MCP discovery/read/restart smoke and P16B packaged backend Agent read-file E2E: **2 passed**.
- Agent and Skill regression selection (`test_agent.py`, `test_agent_capabilities.py`, dependency distribution, lifecycle, registry/API, discovery, skills): **161 passed**.
- Frontend tests: **18 passed** across 5 files.
- `npm run build`: passed. Vite reported the existing >500 kB chunk-size advisory.
- Packaged backend build and Electron Windows x64 NSIS/unpacked build: passed. The resulting `win-unpacked` app was exercised by the P17A acceptance test.
- Ruff on changed Python files: passed.
- `git diff --check`: clean.
- No test secrets, user database/settings, runtime logs, caches, or acceptance artifacts are included in the change.

## Build environment note

The direct Node.js archive endpoint timed out in this environment. To complete the package build, the pinned Node `22.23.3` Windows x64 npm distribution and npm `10.9.4` were staged from the npm registry into the package resources; their executable versions were checked. The packaged dependency-check, no-system-Node MCP tests, and both clean-user release runs passed against that bundle.

## Delivery

Implementation and this result are committed and pushed to `origin main`. Final local/remote HEAD equality and clean worktree are verified after push.
