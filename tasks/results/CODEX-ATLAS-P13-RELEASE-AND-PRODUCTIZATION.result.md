# CODEX-ATLAS-P13-RELEASE-AND-PRODUCTIZATION Result

STATUS: COMPLETED_WITH_LIMITATIONS

## Delivery

- BASE_HEAD: `871e20c35893f7f2f2e06935f71466129079d679`
- IMPLEMENTATION_COMMIT: `287c538` (`feat(release): package Atlas backend for desktop (P13)`)
- The Windows source launcher now prepares a project-local Python environment and starts the Electron desktop workflow. First launch without a configured API key opens Settings with a setup prompt.
- The Windows NSIS build now bundles a PyInstaller backend runtime, so installed Atlas no longer needs system Python or a separate Python dependency install. The package build prepares the isolated build environment automatically.
- The example server binds to loopback. Filesystem MCP arguments expand `~`, with the example scoped to the current user's Documents folder.
- Electron is pinned to `44.4.5`; its install command is explicit in dev, start, and Windows packaging scripts.
- README documents source setup, installer build, first-run model configuration, data paths, and MCP prerequisites. Generated backend build artifacts and the local Python environment are ignored.

## Validation

- `npm test` (`frontend`): 8 passed.
- `npm run test:adapter` (`frontend`): 8 passed.
- `npm run build` (`frontend`): passed; Vite reports a 538.02 kB minified bundle advisory.
- Focused backend tests (`test_mcp_client.py` and `test_config.py`, excluding the known Windows path case): 21 passed, 1 deselected.
- Full `tests/test_config.py` on Windows: 6 passed, 1 known baseline failure in `TestAtlasConfigFromData.test_db_path_absolute` because POSIX `/absolute/...` is drive-root-relative on Windows.
- `npm --prefix frontend run dist:win`: passed. NSIS installer: 202,952,096 bytes; SHA-256 `BB0572D49073B92F3C47194808E8B552386089AE406CE1FF9EF956136CFBCB08`.
- The packaged `atlas_backend.exe` started with isolated config/data and returned `status=ok` on `127.0.0.1:18769`; the process was stopped and the temporary listener closed. The existing service on port 8765 was not changed.
- Packaged resource scan found no `atlas.toml`, `.env`, or `user-settings.json`; the bundled example has no non-empty API key.
- `npm audit`: 0 vulnerabilities (0 high, 0 critical).
- `git diff --check`: passed.
- Targeted Ruff reported two existing findings outside this change: `core/atlas/config.py:28` E501 and `core/atlas/tools/mcp_client.py:326` UP041.

## Limitations

- The installed app still needs the user to enter an API base URL and key before model requests can succeed.
- The default filesystem MCP server uses `npx`; Node.js and network access are needed for that tool. The installer bundles Atlas and its Python backend, not Node.js or third-party MCP server packages.
- This validation built the installer and started the bundled backend in isolation. A full Electron window startup was not attempted because port 8765 was already owned by an existing Python service; that service was left untouched.
- Code signing remains disabled in the existing Electron Builder configuration.

## Review Handoff

The result artifact is committed separately. `tasks/CURRENT.md` remains in its READY state for the normal review flow to advance it.
