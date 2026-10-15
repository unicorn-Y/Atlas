import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { transformSync } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = path.join(root, 'src/preload/index.cts');
const preloadPath = path.join(root, 'dist-electron/preload/index.cjs');
const tsSource = fs.readFileSync(sourcePath, 'utf8');
const port = String(20_000 + Math.floor(Math.random() * 40_000));

function execute(source, filename) {
  const exposed = new Map();
  const sent = [];
  const electron = {
    contextBridge: { exposeInMainWorld: (name, api) => exposed.set(name, api) },
    ipcRenderer: {
      send: (...args) => sent.push(args),
      invoke: async () => undefined,
      on: () => undefined,
      removeListener: () => undefined,
    },
  };
  const module = { exports: {} };
  const sandbox = {
    exports: module.exports,
    module,
    process: { platform: 'win32', env: { ATLAS_PORT: port } },
    require(specifier) {
      assert.equal(specifier, 'electron', `sandboxed preload attempted require(${specifier})`);
      return electron;
    },
  };
  new vm.Script(source, { filename }).runInNewContext(sandbox);
  return { api: exposed.get('atlasDesktop'), sent };
}

// Reproduce the old tsc-only output: it keeps a local shared-module require,
// which the sandbox's deliberately restricted require rejects.
const legacyOutput = transformSync(tsSource, { loader: 'ts', target: 'es2022', format: 'cjs' }).code;
assert.throws(
  () => execute(legacyOutput, 'preload-before-bundle.cjs'),
  /sandboxed preload attempted require\(\.\.\/shared\/ipc\.js\)/,
);

const bundledOutput = fs.readFileSync(preloadPath, 'utf8');
const { api, sent } = execute(bundledOutput, preloadPath);
assert.ok(api, 'preload must expose window.atlasDesktop');
assert.equal(api.apiBaseUrl, `http://127.0.0.1:${port}`);
assert.equal(api.platform, 'win32');
api.minimize();
assert.deepEqual(sent, [['window:minimize']]);
console.log(`PASS: legacy local require rejected; bundled preload exposes random backend port ${port}`);
