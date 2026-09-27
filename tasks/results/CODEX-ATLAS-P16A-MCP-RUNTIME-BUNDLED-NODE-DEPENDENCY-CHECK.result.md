# CODEX-ATLAS-P16A Result

BASE_HEAD: `60d479ae6650249202d93fda4cc6507ba6f3650f`
SCOPE: Bundled Node runtime for MCP stdio, read-only runtime/dependency diagnostics API and Settings panel

## Delivered

- `core/atlas/tools/node_runtime.py` (new): resolves the Atlas-bundled Node runtime, treats it as required for packaged builds, and resolves stdio commands (`node`/`npm`/`npx`) against it without silently falling back to a system Node.
- `core/atlas/tools/mcp_client.py`: stdio commands are routed through the bundled runtime, per-server configuration and lifecycle state is tracked, and a failed server keeps an explicit blocking reason instead of degrading silently.
- `core/atlas/server.py`: added the read-only dependency-check API reporting runtime/MCP/Python/command status from the existing P15E `dependency_preflight()`, without mutating configuration.
- `frontend/scripts/package-node.mjs` and `frontend/node-runtime.json` (new): download the official Node 22.23.3 Windows archive, verify the pinned SHA-256 manifest, validate `node.exe`/`npm-cli.js`/`npx-cli.js`, and stage the runtime into the packaged resource tree.
- `frontend/package.json`, `frontend/src/main/electron.ts`: packaging and startup use the bundled runtime; packaged launches require it (`ATLAS_NODE_RUNTIME_REQUIRED=1`).
- `frontend/src/renderer/pages/DependencyCheckPanel.tsx` (with `DependencyCheckPanel.test.tsx`), `SettingsPage.tsx`, `App.module.css`: Settings card rendering the read-only diagnostics.
- `core/tests/test_mcp_client.py`, `core/tests/test_server.py`: added coverage for runtime resolution, manifest pinning, npx routing, packaged-mode refusal to fall back to system Node, lifecycle state, argument-leak protection and the read-only diagnostics API.
- `core/tests/test_mcp_runtime_live.py` (new): live tests that launch the real filesystem MCP through the bundled runtime and the packaged backend executable.

## Validation

- P15A–P15E + MCP + Agent + diagnostics regression (11 modules): **211 passed, 2 skipped**.
- Live MCP smoke (real `npx` → official filesystem MCP through bundled Node 22.23.3, tool discovery, agent file read, restart and second call): **1 passed**.
- Packaged backend smoke (`windows-release/win-unpacked`, isolated data directory, system Node removed from the child PATH): **1 passed** — health check and MCP connection over the packaged backend, asserting `node.source == "bundled"` and version `v22.23.3`.
- Frontend tests: **17 passed** (5 files).
- Frontend production build: **passed** (only the pre-existing >500 kB chunk-size warning).
- Ruff on changed Python files: **All checks passed**. `core/tests/test_server.py` still reports 14 pre-existing findings; the identical 14 findings reproduce on a clean `60d479a` worktree, so this task adds zero lint debt.
- `git diff --check`: **clean**.
- Packaging contents: `runtime/node/` carries `node.exe` plus `npm-cli.js` and `npx-cli.js` in a plain subdirectory — the electron-builder nested-`node_modules` filter that dropped them was fixed. No secrets, local config, databases, build output, logs, caches or temporary files are committed.

### Observed pre-existing flake (not introduced by this task)

Two tests in `core/tests/test_skill_acquisition.py` — `test_fallback_requires_fresh_warn_approval_and_records_provenance` and `test_concurrent_duplicate_install_keeps_existing_registry_and_directory` — intermittently fail on `installed.status_code == 200` receiving a server-side `403`. Measured **2 failures in 65 runs (~3%)** under Bash + `core/.venv`, while a 400-iteration in-process probe of the identical request flow passed 400/400 and the same files passed cleanly under the pwsh invocation. The 403 can only originate from the approval/hash gate inside `install_acquisition`, which P16A does not touch; no skill-acquisition file is modified by this task. Clean-HEAD control runs were 40/40 green, so the sample is not large enough to prove a difference. Recorded as a pre-existing low-frequency flake in the P15C area and deliberately left unfixed to keep this task's scope bounded.

## Delivery State

The implementation and this result are committed and pushed to `origin main`; the local HEAD equals `origin/main` and the worktree is clean.

## Verification note

The preceding executor session was interrupted (`turn_aborted`) after it had implemented the code but before it committed anything, and its last verification run had a pytest process stuck for ~56 minutes in the wrong interpreter environment. Every required check above was re-run from scratch on the current worktree rather than carried over from that session's claims.
