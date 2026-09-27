# CODEX-ATLAS-P17B-REPRODUCIBLE-WINDOWS-RELEASE-AND-INSTALLER-ACCEPTANCE

## Status

PASS. The reproducible release and actual NSIS install lifecycle acceptance gates passed.

- `BASE_HEAD`: `e2af9dee563b07fd2a5a2c361925f63bced1077b`
- `IMPLEMENTATION_COMMIT`: `3938673c7085d7e073536d61705c2acac215d3ae`
- `RESULT_COMMIT`: recorded in repository history after this result is committed.

## Changes

- `frontend/scripts/package-node.mjs` accepts `ATLAS_NODE_ARCHIVE` as an optional cache input. It reads the archive before clearing its work directory, clears stale Node staging before verification, validates the canonical `frontend/node-runtime.json` SHA-256 for both direct and cached inputs, and reports the selected source and actual hash. A mismatch fails before staging.
- `frontend/scripts/clean-release-output.mjs` removes release outputs, backend output, and Node staging before each release build.
- `frontend/package.json` makes `dist:win` run the complete clean build and NSIS packaging sequence, followed by release manifest generation.
- `frontend/scripts/write-release-manifest.mjs` writes a sidecar `release-manifest.json` with app/Git/Electron/backend/Node identities, canonical archive hash, installer SHA-256, unpacked executable SHA-256, and a non-secret build environment summary.
- `core/tests/test_release_build_scripts.py` verifies a wrong local cache archive fails hard and stale Node staging is cleared.
- `core/tests/test_release_acceptance.py` adds opt-in NSIS installation, daily-use, uninstall, user-data retention, reinstall, relaunch, and final test-install cleanup acceptance.
- `README.md` documents the clean Windows build, optional verified archive cache input, and manifest output.

## Release build evidence

Two independent `npm run dist:win` builds started with clean `dist`, backend, Node staging, and `windows-release` directories. Each rebuilt the Python backend with PyInstaller, frontend, bundled Node, `win-unpacked`, and the NSIS installer.

| Evidence | Clean build 1 | Clean build 2 |
| --- | --- | --- |
| Installer | `Atlas-0.1.0-Setup.exe` | `Atlas-0.1.0-Setup.exe` |
| Installer size | 229,780,310 bytes | 229,779,396 bytes |
| Installer SHA-256 | `f65160a0eb69c8b103dff40bbe6d60d661415ed3b987788f74f7f8863dfcc767` | `daa4c511a10dde5bcb85cccd6d688945b8d612b566b9aa5f3b105fbe1b0840f4` |
| App / backend | `0.1.0` / `0.1.0` | `0.1.0` / `0.1.0` |
| Electron | `44.4.5` | `44.4.5` |
| Bundled Node | `22.23.3` | `22.23.3` |
| Canonical Node archive SHA-256 | `2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71` | same |

The second build's `frontend/windows-release/release-manifest.json` installer hash was independently compared with the produced installer and matched. Both manifests identify source commit `3938673c7085d7e073536d61705c2acac215d3ae`. The installer hashes differ between clean runs; these builds establish a repeatable verified process, not byte-for-byte deterministic NSIS output.

Both direct official Node archive acquisition and the optional local cache path were exercised. Each reported the canonical hash above. The mismatch regression passed and confirmed no stale runtime staging remained after failure.

## Installer lifecycle acceptance

`ATLAS_P17B_RUN_INSTALLER_ACCEPTANCE=1` enabled `test_nsis_install_uninstall_reinstall_acceptance`: **1 passed**.

The test installed the generated NSIS executable into a short isolated directory to stay within Windows path limits. It then launched installed Atlas with system Node removed from its child `PATH`, used isolated `APPDATA`, `LOCALAPPDATA`, Atlas data, and npm cache, and verified:

- packaged Atlas and backend launched and backend health became ready;
- provider/API key and `gpt-4o-mini` model were configured through Settings, with no key echo in the read API;
- streaming chat completed and history persisted across an in-place restart;
- bundled Node `v22.23.3` was selected while system Node was unavailable;
- filesystem MCP was discovered and the real Agent path read the test marker through `read_file`, with the tool event visible in the renderer;
- graceful shutdown returned successfully and left no new managed backend or Node/MCP process;
- the first NSIS uninstall removed the isolated program files and preserved the isolated user data snapshot;
- reinstall succeeded; the installed app launched again and exposed the prior provider/model configuration and conversation history;
- a final uninstall removed the temporary reinstall directory.

The installed resource scan found no `atlas.toml`, `.env`, `user-settings.json`, database, or log files, and the installed static config/runtime manifests contained no development-checkout path.

## Required regression and quality checks

- P17A clean packaged daily-usability acceptance: **1 passed**, exercising two independent clean user roots. `ATLAS_P17A_RESOURCES_DIR` was supplied because the existing test's default resource path resolves under `core/`.
- Full `core/tests/test_server.py`: **54 passed**.
- Release script mismatch/stale staging regression: **1 passed**.
- Frontend tests: **18 passed**.
- Frontend production build: **passed** (existing Vite chunk-size advisory).
- Ruff on changed Python files: **passed**.
- `git diff --check`: **passed**.
- Build artifact/secret scan and installed-resource scan: **passed**.
- Final local/remote HEAD equality and clean status: recorded after push.

## Notes

- PyInstaller emitted its existing optional LiteLLM UI submodule warning (`backoff` not installed); both backend builds and installers completed successfully.
- The release manifest is a sidecar beside the installer so it can include the finished installer hash without a circular self-hash.
