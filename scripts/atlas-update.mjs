#!/usr/bin/env node
// Source-mode updater and launcher for a personal Atlas checkout.
//
//   node scripts/atlas-update.mjs                  pull + rebuild what changed
//   node scripts/atlas-update.mjs --relaunch       ...then start Atlas
//   node scripts/atlas-update.mjs --launch-only    build if never built, then start Atlas
//   --wait-pid <pid>   wait for that process (the running Atlas) to exit first
//
// Never touches uncommitted work: with tracked local changes it refuses to pull and only
// (re)starts Atlas. Dependencies are reinstalled only when their manifests changed; the
// frontend is rebuilt when anything under frontend/ changed or no build exists.
// Log: data/logs/update.log   Status: data/update-status.json
import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const option = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };

const logDir = path.join(root, 'data', 'logs');
fs.mkdirSync(logDir, { recursive: true });
const logFile = path.join(logDir, 'update.log');
const log = (line) => fs.appendFileSync(logFile, `${new Date().toISOString()} ${line}\n`, 'utf8');
const status = (value) => fs.writeFileSync(path.join(root, 'data', 'update-status.json'),
  JSON.stringify({ ...value, at: new Date().toISOString() }, null, 2), 'utf8');

const isWin = process.platform === 'win32';
const python = path.join(root, 'core', '.venv', isWin ? 'Scripts/python.exe' : 'bin/python');
const npm = isWin ? 'npm.cmd' : 'npm';

function sh(command, commandArgs, options = {}) {
  log(`$ ${command} ${commandArgs.join(' ')}`);
  const output = execFileSync(command, commandArgs, {
    cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    shell: isWin && command.endsWith('.cmd'), maxBuffer: 64 * 1024 * 1024, ...options,
  });
  if (output.trim()) log(output.trim().split('\n').slice(-15).join('\n'));
  return output.trim();
}

async function waitForExit(pid, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { process.kill(pid, 0); } catch { return; }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  log(`pid ${pid} still alive after ${timeoutMs / 1000}s; continuing`);
}

function changedFiles(before, after) {
  return before === after ? [] : sh('git', ['diff', '--name-only', before, after]).split('\n').filter(Boolean);
}

function pull() {
  const branch = sh('git', ['rev-parse', '--abbrev-ref', 'HEAD']);
  if (sh('git', ['status', '--porcelain', '--untracked-files=no'])) {
    return { pulled: false, reason: '本地有未提交的改动，已跳过更新。', changed: [] };
  }
  const before = sh('git', ['rev-parse', 'HEAD']);
  try {
    sh('git', ['fetch', '--quiet', 'origin', branch]);
    sh('git', ['merge', '--ff-only', `origin/${branch}`]);
  } catch (error) {
    // Offline or a local-only branch: an upstream-tracking result can still be merged below.
    if (!readPending()) throw error;
    log(`fetch/ff from origin skipped: ${String(error?.message || error).split('\n')[0]}`);
  }
  mergePending();
  const after = sh('git', ['rev-parse', 'HEAD']);
  return { pulled: before !== after, before, after, changed: changedFiles(before, after) };
}

// Atlas 追新 (core/atlas/upstream) leaves a verified commit in data/upstream/pending-merge.json
// when it could not push it; merge it here so a restart picks it up.
const pendingFile = path.join(root, 'data', 'upstream', 'pending-merge.json');
const readPending = () => { try { return JSON.parse(fs.readFileSync(pendingFile, 'utf8')); } catch { return null; } };

function mergePending() {
  const pending = readPending();
  if (!pending?.commit) return;
  try {
    sh('git', ['merge-base', '--is-ancestor', pending.commit, 'HEAD']);
    return; // already in
  } catch { /* not merged yet */ }
  try {
    sh('git', ['merge', '--ff-only', pending.commit]);
  } catch {
    try {
      sh('git', ['merge', '--no-edit', '-m', 'merge: Atlas 追新结果', pending.commit]);
    } catch (error) {
      try { sh('git', ['merge', '--abort']); } catch { /* nothing to abort */ }
      throw new Error(`追新结果和本地改动冲突，没有合并：${pending.commit.slice(0, 8)}`);
    }
  }
}

// What the last successful rebuild was built from; changes are measured against it, so a
// first switch to source mode, a failed build or a manual pull are all caught up.
const stampFile = path.join(root, 'data', 'build-stamp.json');
const readStamp = () => { try { return JSON.parse(fs.readFileSync(stampFile, 'utf8')).commit; } catch { return null; } };

function rebuild() {
  const head = sh('git', ['rev-parse', 'HEAD']);
  const stamp = readStamp();
  let changed = null; // null = unknown baseline: rebuild everything that has a build step
  if (stamp) {
    try { changed = changedFiles(stamp, head); } catch { changed = null; }
  }
  const touched = (prefix) => changed === null || changed.some((file) => file === prefix || file.startsWith(prefix));
  const steps = [];
  sh(python, ['core/scripts/setup_hermes.py']); // no-op when already at the pin
  if (touched('core/pyproject.toml') || !fs.existsSync(python)) {
    sh(python, ['-m', 'pip', 'install', '-q', '--no-cache-dir', '-e', 'core']);
    steps.push('python');
  }
  // Exact third-party versions verified by Atlas 追新; keeps both machines identical.
  if (changed !== null && touched('core/requirements.lock') && fs.existsSync(path.join(root, 'core', 'requirements.lock'))) {
    sh(python, ['-m', 'pip', 'install', '-q', '--disable-pip-version-check', '--no-cache-dir', '-r', 'core/requirements.lock']);
    steps.push('python-lock');
  }
  // Check the binary, not the package folder: a blocked install script once left
  // node_modules/electron without dist/electron.exe and Atlas could not start.
  const electronExe = path.join(root, 'node_modules', 'electron', 'dist', isWin ? 'electron.exe' : 'electron');
  if ((changed !== null && (touched('package-lock.json') || touched('package.json') || touched('frontend/package.json')))
      || !fs.existsSync(electronExe)) {
    sh(npm, ['ci', '--no-audit', '--no-fund']);
    steps.push('npm');
  }
  if (!fs.existsSync(electronExe)) {
    // GitHub downloads fail on some networks; the npmmirror copy is the usual fallback.
    sh('node', [path.join(root, 'node_modules', 'electron', 'install.js')], {
      env: { ...process.env, ELECTRON_MIRROR: process.env.ELECTRON_MIRROR || 'https://npmmirror.com/mirrors/electron/' },
    });
    steps.push('electron');
  }
  const built = fs.existsSync(path.join(root, 'frontend', 'dist', 'index.html'))
    && fs.existsSync(path.join(root, 'frontend', 'dist-electron', 'preload', 'index.cjs'));
  if (!built || touched('frontend/') || touched('backend-adapter/')) {
    sh(npm, ['--prefix', 'frontend', 'run', 'build']);
    steps.push('frontend');
  }
  // Machine-local follow-ups of an upstream update: MCP versions in config/atlas.toml, MemOS rebuild.
  const memos = changed !== null && touched('vendor/memos-local-plugin/');
  try {
    sh(python, ['-m', 'atlas.upstream', 'post-merge', ...(memos ? ['--memos'] : [])], { cwd: path.join(root, 'core') });
    if (memos) steps.push('memos');
  } catch (error) {
    log(`post-merge failed: ${String(error?.stderr || error?.message || error).trim().split('\n').slice(-5).join(' | ')}`);
  }
  fs.writeFileSync(stampFile, JSON.stringify({ commit: head, at: new Date().toISOString(), steps }, null, 2), 'utf8');
  return steps;
}

function launch() {
  const electron = path.join(root, 'node_modules', 'electron', 'dist', isWin ? 'electron.exe' : 'electron');
  const child = spawn(electron, [path.join(root, 'frontend')], {
    cwd: root, detached: true, stdio: 'ignore', windowsHide: false,
    env: { ...process.env, ATLAS_PYTHON: python, VITE_DEV_SERVER_URL: '' },
  });
  child.unref();
  log(`launched Atlas (pid ${child.pid})`);
}

// One updater at a time: a double-clicked shortcut once started two, and the second launched
// Atlas while the first was still swapping the Hermes checkout under it (ImportError at run time).
const lockFile = path.join(root, 'data', 'update.lock');
function acquireLock() {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      fs.writeFileSync(lockFile, String(process.pid), { flag: 'wx' });
      return true;
    } catch { /* held, or stale */ }
    const holder = Number((() => { try { return fs.readFileSync(lockFile, 'utf8'); } catch { return ''; } })());
    if (holder && holder !== process.pid) {
      try { process.kill(holder, 0); return false; } catch { /* holder is gone */ }
    }
    try { fs.unlinkSync(lockFile); } catch { /* raced with another cleanup */ }
  }
  return false;
}
if (!acquireLock()) {
  log('another updater is running; it starts Atlas when done');
  process.exit(0);
}
process.on('exit', () => {
  try { if (fs.readFileSync(lockFile, 'utf8') === String(process.pid)) fs.unlinkSync(lockFile); } catch { /* gone */ }
});

const waitPid = Number(option('--wait-pid'));
try {
  if (waitPid) await waitForExit(waitPid);
  if (flag('--launch-only')) {
    rebuild();
  } else {
    const result = pull();
    log(result.pulled ? `pulled ${result.before?.slice(0, 7)}..${result.after?.slice(0, 7)} (${result.changed.length} files)`
      : (result.reason ?? 'already up to date'));
    const steps = rebuild();
    status({ ok: true, pulled: result.pulled, reason: result.reason, steps, head: sh('git', ['rev-parse', '--short', 'HEAD']) });
  }
} catch (error) {
  const detail = String(error?.stderr || error?.message || error).trim().split('\n').slice(-20).join('\n');
  log(`FAILED: ${detail}`);
  status({ ok: false, error: detail });
  process.exitCode = 1;
}
// Relaunch even after a failed update: the previous build is still in place.
if (flag('--relaunch') || flag('--launch-only')) launch();
