# PACKAGE-INDEX

Scope: mechanical package index only. Original files are in `packages/`; entry paths below come from ZIP/TGZ directory listings or repository path names. No functional review was performed. Source maps were not inventoried.

## Zed v1.24.2

- `packages/zed/Zed-x86_64.exe` — official Windows x86_64 desktop release installer; contents not expanded.
- `packages/zed/zed-remote-server-windows-x86_64.zip` — ZIP entry: `remote_server.exe`.
- `packages/zed/zed-source-fb690677.zip` — pinned commit `fb69067729cb16a7f6135e2c1600c26a28c59659`; relevant entry paths include `README.md`, `Cargo.toml`, `crates/agent/Cargo.toml`, `crates/agent_ui/Cargo.toml`, `crates/agent_servers/Cargo.toml`, `crates/extension_host/Cargo.toml`, `crates/extensions_ui/Cargo.toml`, and `crates/cli/src/main.rs`.
- Product scope: Agent Panel and extension host are part of the host application; these are host-native surfaces, not separately installed plugins.

## OpenHands Agent Canvas v1.27.1

- `packages/openhands/OpenHands-Agent-Canvas-Setup-1.27.1.exe` — official Windows x86_64 release installer; contents not expanded.
- `packages/openhands/OpenHands-source-f07aebdf.zip` — pinned commit `f07aebdf5cdd71f4a05ebcf30f8bef5e4e3b70b9`; mechanical path listing identified root `package.json`, `src/index.ts`, `src/index.css`, `vite.config.ts`, and `src/components/` UI module paths. This source archive corresponds to the project release; no installer/source equivalence claim is made.

## Squad v0.7.6

- `packages/squad/squad-x86_64-pc-windows-msvc.zip` — official Windows x86_64 release ZIP entries: `squad.exe`, `README.md`, `LICENSE`.
- `packages/squad/squad-source-af6df2c9.zip` — pinned commit `af6df2c9662da33ebfc7d710dceae36c533ccc43`; key entries: `Cargo.toml`, `Cargo.lock`, `README.md`, `src/main.rs`.

## ccusage 20.0.36

- `packages/ccusage/ccusage-20.0.36.tgz` — npm registry package entries: `package/package.json`, `package/src/cli.js`, `package/config-schema.json`, `package/README.md`, `package/LICENSE`.
- `packages/ccusage/ccusage-source-f56bb3d2.zip` — pinned commit `f56bb3d281544b09bfd4128339d4a491c7c2e045`; key entries: root `package.json`, `apps/ccusage/package.json`, `packages/ccusage-win32-x64/package.json`, `rust/crates/ccusage/src/main.rs`, and provider adapter manifests under `rust/adapters/`.
- This is an independent third-party usage/token reporting tool distributed via npm, not a feature bundled by an agent host.

## Claude HUD v0.11.3

- `packages/claude-hud/claude-hud-source-5621429b.zip` — pinned commit `5621429b84ea2503185221244c43a06797bfd05e`; key entries: `.claude-plugin/plugin.json`, `package.json`, `README.md`, `src/index.ts`, `src/render/index.ts`, `dist/index.js`, `dist/render/index.js`.
- This is a third-party installable Claude Code plugin sourced from its upstream repository. It is not Anthropic-authored or host-native. No separate GitHub release binary asset was published, so the pinned source archive is the collected plugin package.
