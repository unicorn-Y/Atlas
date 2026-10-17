import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const updaterSource = path.join(path.dirname(fileURLToPath(import.meta.url)), 'atlas-update.mjs');
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();

function fixture(t, { update = true } = {}) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-updater-test-'));
  t.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
  const repo = path.join(tmp, 'active');
  const remote = path.join(tmp, 'remote.git');
  fs.mkdirSync(repo, { recursive: true });
  git(repo, 'init', '-b', 'main');
  git(repo, 'config', 'user.name', 'Updater Test');
  git(repo, 'config', 'user.email', 'updater-test@example.invalid');
  const mkdirFile = (rel, content = 'old') => {
    const file = path.join(repo, rel);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, content);
  };
  mkdirFile('scripts/atlas-update.mjs', fs.readFileSync(updaterSource, 'utf8'));
  mkdirFile('core/.venv/Scripts/python.exe', 'stub');
  mkdirFile('node_modules/electron/dist/electron.exe', 'stub');
  mkdirFile('frontend/dist/index.html', 'old-dist');
  mkdirFile('frontend/dist-electron/main/electron.js', 'old-main');
  mkdirFile('frontend/dist-electron/preload/index.cjs', 'old-preload');
  mkdirFile('data/build-stamp.json', JSON.stringify({ commit: 'placeholder' }));
  mkdirFile('frontend/touch.txt', 'old');
  git(repo, 'add', '.');
  git(repo, 'commit', '-m', 'initial');
  let original = git(repo, 'rev-parse', 'HEAD');
  fs.writeFileSync(path.join(repo, 'data/build-stamp.json'), JSON.stringify({ commit: original }));
  git(repo, 'add', 'data/build-stamp.json');
  git(repo, 'commit', '--amend', '--no-edit');
  original = git(repo, 'rev-parse', 'HEAD');
  fs.mkdirSync(remote, { recursive: true });
  execFileSync('git', ['init', '--bare', remote], { stdio: 'ignore' });
  git(repo, 'remote', 'add', 'origin', remote);
  git(repo, 'push', '-u', 'origin', 'main');
  if (update) {
    fs.writeFileSync(path.join(repo, 'frontend/touch.txt'), 'new');
    git(repo, 'add', '.');
    git(repo, 'commit', '-m', 'update');
    git(repo, 'push', 'origin', 'main');
    git(repo, 'reset', '--hard', original);
  }
  const bin = path.join(tmp, 'bin');
  fs.mkdirSync(bin);
  const fakeNpm = path.join(bin, 'npm.cmd');
  fs.writeFileSync(fakeNpm, '@echo off\r\nnode "%~dp0fake-npm.mjs" %*\r\nexit /b %ERRORLEVEL%\r\n');
  fs.writeFileSync(path.join(bin, 'fake-npm.mjs'), `
    import fs from 'node:fs'; import path from 'node:path';
    if (process.env.FAIL_ACTIVE_BUILD === '1' && process.cwd() === process.env.ATLAS_FIXTURE_ROOT) process.exit(42);
    if (process.argv.includes('build')) {
      const root = process.cwd();
      fs.mkdirSync(path.join(root, 'dist'), {recursive:true});
      fs.mkdirSync(path.join(root, 'dist-electron/main'), {recursive:true});
      fs.mkdirSync(path.join(root, 'dist-electron/preload'), {recursive:true});
      fs.writeFileSync(path.join(root, 'dist/index.html'), 'new-dist');
      fs.writeFileSync(path.join(root, 'dist-electron/main/electron.js'), 'new-main');
      fs.writeFileSync(path.join(root, 'dist-electron/preload/index.cjs'), 'new-preload');
    }
  `);
  return { tmp, repo, original, env: { ...process.env, PATH: `${bin};${process.env.PATH}`, ATLAS_FIXTURE_ROOT: repo } };
}

function runUpdate(f, extra = {}) {
  return spawnSync(process.execPath, [path.join(f.repo, 'scripts/atlas-update.mjs')], {
    cwd: f.repo, encoding: 'utf8', env: { ...f.env, ...extra }, timeout: 60_000,
  });
}

function readMarker(repo, rel) { return fs.readFileSync(path.join(repo, rel), 'utf8'); }

test('failed second bundle backup preserves the original second bundle and rolls back first bundle', (t) => {
  const f = fixture(t);
  const preload = path.join(f.tmp, 'fail-rename.cjs');
  fs.writeFileSync(preload, `
    const fs = require('node:fs'); const rename = fs.renameSync;
    fs.renameSync = function(from, to, ...args) {
      if (String(from).endsWith('\\\\frontend\\\\dist-electron') && String(to).endsWith('\\\\backups\\\\dist-electron')) throw new Error('injected second backup rename failure');
      return rename.call(this, from, to, ...args);
    };
  `);
  const result = runUpdate(f, { NODE_OPTIONS: `--require=${preload}` });
  assert.notEqual(result.status, 0);
  assert.equal(git(f.repo, 'rev-parse', 'HEAD'), f.original);
  assert.equal(readMarker(f.repo, 'frontend/dist/index.html'), 'old-dist');
  assert.equal(readMarker(f.repo, 'frontend/dist-electron/main/electron.js'), 'old-main');
});

test('active rebuild failure restores source, bundles, and build stamp', (t) => {
  const f = fixture(t);
  const oldStamp = readMarker(f.repo, 'data/build-stamp.json');
  const preload = path.join(f.tmp, 'fail-active-rebuild.cjs');
  fs.writeFileSync(preload, `
    const fs = require('node:fs'); const rename = fs.renameSync;
    fs.renameSync = function(from, to, ...args) {
      const result = rename.call(this, from, to, ...args);
      if (String(to).endsWith('\\\\data\\\\build-stamp.json')) {
        fs.unlinkSync(require('node:path').join(process.env.ATLAS_FIXTURE_ROOT, 'frontend', 'dist', 'index.html'));
      }
      return result;
    };
  `);
  const result = runUpdate(f, { FAIL_ACTIVE_BUILD: '1', NODE_OPTIONS: `--require=${preload}` });
  assert.notEqual(result.status, 0);
  assert.equal(git(f.repo, 'rev-parse', 'HEAD'), f.original);
  assert.equal(readMarker(f.repo, 'frontend/dist/index.html'), 'old-dist');
  assert.equal(readMarker(f.repo, 'frontend/dist-electron/main/electron.js'), 'old-main');
  assert.equal(readMarker(f.repo, 'data/build-stamp.json'), oldStamp);
});

test('no-op update returns before creating an update stage or candidate worktree', (t) => {
  const f = fixture(t, { update: false });
  const result = runUpdate(f);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(git(f.repo, 'rev-parse', 'HEAD'), f.original);
  assert.equal(git(f.repo, 'worktree', 'list').split('\n').length, 1);
  assert.equal(fs.readdirSync(f.tmp).some((name) => name.startsWith('.atlas-update-stage-')), false);
});
