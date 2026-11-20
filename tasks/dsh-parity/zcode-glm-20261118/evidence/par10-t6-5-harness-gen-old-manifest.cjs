// T6-5 harness: build a new-schema runtime manifest for the real 0.1.0 release
// bytes using this worktree's production afterPack hook (upgraded-install fixture).
const fs = require('node:fs');
const path = require('node:path');

const hook = require('D:/Atlas/.worktrees/zcode-par10-win-release-repro/frontend/scripts/after-pack-release-manifest.cjs');
const root = process.argv[2];
const appVersion = process.argv[3];
const electronVersion = process.argv[4];
const nodeRuntime = JSON.parse(fs.readFileSync(
  path.join(root, 'resources', 'atlas', 'runtime', 'node', 'node-runtime.json'), 'utf8'));
const manifest = hook.buildRuntimeManifest({
  appOutDir: root,
  productFilename: 'Atlas',
  appVersion,
  electronVersion,
  nodeRuntime,
  backendVersion: '0.1.0',
  gitCommit: '6c49b7f62a371c406211bb7ebd99598d38e25c7b',
  timeUtc: '2026-10-05T18:42:24.653Z',
  platform: 'win32',
  architecture: 'x64',
  nodeVersion: 'v24.18.1',
});
const destination = path.join(root, 'resources', 'atlas', 'release-manifest.json');
fs.mkdirSync(path.dirname(destination), { recursive: true });
fs.writeFileSync(destination, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
console.log(`wrote ${destination}`);