#!/usr/bin/env node
// Source-mode updater and launcher for a personal Atlas checkout.
//
//   node scripts/atlas-update.mjs                  pull + rebuild what changed
//   node scripts/atlas-update.mjs --relaunch       ...then start Atlas
//   node scripts/atlas-update.mjs --launch-only    start Atlas, then check for updates in background
//   --wait-pid <pid>   wait for that process (the running Atlas) to exit first
//
// Local changes no longer block a fast-forward: files the update doesn't touch are left
// alone, and ones it does touch are auto-stashed, pulled, then restored (kept in the stash
// if they now conflict). Dependencies are reinstalled only when their manifests changed; the
// frontend is rebuilt when anything under frontend/ changed or no build exists.
// Log: data/logs/update.log   Status: data/update-status.json
import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
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

// Pop an auto-stash, keeping the pulled tree if the local change now conflicts
// (e.g. upstream also touched that file): the update still lands and the local
// change is preserved in `git stash list` for the user to reconcile.
function restoreAutoStash() {
  try {
    sh('git', ['stash', 'pop', '--quiet']);
  } catch {
    // Conflicted pop leaves unmerged paths; the tree was clean (just pulled)
    // before the pop, so hard-resetting to HEAD drops only the half-applied
    // conflict and keeps the pulled version. The stash is retained on conflict,
    // so the local change survives in `git stash list` for the user.
    try { sh('git', ['reset', '--hard', 'HEAD']); } catch { /* best effort */ }
    log('auto-stash pop conflicted; local changes kept in `git stash list` (stash@{0})');
  }
}

function pull() {
  const branch = sh('git', ['rev-parse', '--abbrev-ref', 'HEAD']);
  // A fast-forward only rewrites files that changed between before/after, so a
  // dirty tree no longer blocks the update outright (the Hermes engine rewrites
  // engine/config.yaml on every launch, which used to make updates silently
  // skip). Only stash when the incoming change actually collides with a locally
  // modified file.
  const dirty = Boolean(sh('git', ['status', '--porcelain', '--untracked-files=no']));
  const before = sh('git', ['rev-parse', 'HEAD']);
  let stashed = false;
  try {
    sh('git', ['fetch', '--quiet', 'origin', branch]);
    try {
      sh('git', ['merge', '--ff-only', `origin/${branch}`]);
    } catch (ffError) {
      // A genuine non-fast-forward can't be auto-resolved; only retry when the
      // blocker is local changes to an incoming file, which stashing clears.
      if (!dirty) throw ffError;
      sh('git', ['stash', 'push', '--quiet', '--message', 'atlas-update auto-stash']);
      stashed = true;
      sh('git', ['merge', '--ff-only', `origin/${branch}`]);
    }
  } catch (error) {
    // Offline or a local-only branch: an upstream-tracking result can still be merged below.
    if (!readPending()) { if (stashed) restoreAutoStash(); throw error; }
    log(`fetch/ff from origin skipped: ${String(error?.message || error).split('\n')[0]}`);
  }
  mergePending();
  if (stashed) restoreAutoStash();
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
const requiredBuildFiles = [
  path.join(root, 'frontend', 'dist', 'index.html'),
  path.join(root, 'frontend', 'dist-electron', 'main', 'electron.js'),
  path.join(root, 'frontend', 'dist-electron', 'preload', 'index.cjs'),
];
const missingBuildFiles = () => requiredBuildFiles.filter((file) => !fs.existsSync(file));

function rebuild() {
  const head = sh('git', ['rev-parse', 'HEAD']);
  const stamp = readStamp();
  let changed = null; // null = unknown baseline: rebuild everything that has a build step
  if (stamp) {
    try { changed = changedFiles(stamp, head); } catch { changed = null; }
  }
  const touched = (prefix) => changed === null || changed.some((file) => file === prefix || file.startsWith(prefix));
  const steps = [];
  const missingPython = !fs.existsSync(python);
  if (touched('core/pyproject.toml') || missingPython) {
    sh(python, ['-m', 'pip', 'install', '-q', '--no-cache-dir', '-e', 'core']);
    steps.push('python');
  }
  // Exact third-party versions verified by Atlas 追新; keeps both machines identical.
  const requirementsLock = path.join(root, 'core', 'requirements.lock');
  if ((missingPython || changed === null || touched('core/requirements.lock')) && fs.existsSync(requirementsLock)) {
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
  const built = missingBuildFiles().length === 0;
  if (!built || touched('frontend/') || touched('backend-adapter/')) {
    const backup = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-build-'));
    const outputs = ['dist', 'dist-electron'];
    for (const output of outputs) {
      const source = path.join(root, 'frontend', output);
      if (fs.existsSync(source)) fs.cpSync(source, path.join(backup, output), { recursive: true });
    }
    try {
      sh(npm, ['--prefix', 'frontend', 'run', 'build']);
      const missing = missingBuildFiles();
      if (missing.length) throw new Error(`Build incomplete; missing: ${missing.map((file) => path.relative(root, file)).join(', ')}`);
    } catch (error) {
      for (const output of outputs) {
        const target = path.join(root, 'frontend', output);
        fs.rmSync(target, { recursive: true, force: true });
        const saved = path.join(backup, output);
        if (fs.existsSync(saved)) fs.cpSync(saved, target, { recursive: true });
      }
      throw error;
    } finally {
      fs.rmSync(backup, { recursive: true, force: true });
    }
    steps.push('frontend');
  }
  const missing = missingBuildFiles();
  if (missing.length) throw new Error(`Build incomplete; missing: ${missing.map((file) => path.relative(root, file)).join(', ')}`);
  fs.writeFileSync(stampFile, JSON.stringify({ commit: head, at: new Date().toISOString(), steps }, null, 2), 'utf8');
  return steps;
}

function postMerge() {
  // Machine-local follow-up of an upstream update: MCP versions in config/atlas.toml.
  try {
    sh(python, ['-m', 'atlas.upstream', 'post-merge'], { cwd: path.join(root, 'core') });
  } catch (error) {
    log(`post-merge failed: ${String(error?.stderr || error?.message || error).trim().split('\n').slice(-5).join(' | ')}`);
  }
}

function launch() {
  const electron = path.join(root, 'node_modules', 'electron', 'dist', isWin ? 'electron.exe' : 'electron');
  // Always expose a CDP endpoint so the app can be inspected/driven remotely.
  // Override the port with ATLAS_DEBUG_PORT, or set it to 0 to disable.
  const debugPort = process.env.ATLAS_DEBUG_PORT || '9335';
  const electronArgs = [];
  if (debugPort && debugPort !== '0') {
    electronArgs.push(`--remote-debugging-port=${debugPort}`, '--remote-allow-origins=*');
  }
  electronArgs.push(path.join(root, 'frontend'));
  const child = spawn(electron, electronArgs, {
    cwd: root, detached: true, stdio: 'ignore', windowsHide: false,
    env: { ...process.env, ATLAS_PYTHON: python, VITE_DEV_SERVER_URL: '' },
  });
  child.unref();
  log(`launched Atlas (pid ${child.pid}) debug-port=${debugPort}`);
}

// The desktop may skip rebuilding only when the stamp and every required bundle agree.
const completeBuild = () => missingBuildFiles().length === 0;
if (flag('--launch-only') && readStamp() === sh('git', ['rev-parse', 'HEAD']) && completeBuild()) {
  launch();
  process.exit(0);
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
    if (result.pulled) postMerge();
    status({ ok: true, pulled: result.pulled, reason: result.reason, steps, head: sh('git', ['rev-parse', '--short', 'HEAD']) });
  }
} catch (error) {
  const detail = String(error?.stderr || error?.message || error).trim().split('\n').slice(-20).join('\n');
  console.error(`Atlas update failed:\n${detail}`);
  log(`FAILED: ${detail}`);
  status({ ok: false, error: detail });
  process.exitCode = 1;
}
// A failed update can leave source or dependencies newer than the last successful build.
// Do not launch that mixed state; retain the exact failure in update-status.json/log.
if (process.exitCode !== 1 && (flag('--relaunch') || flag('--launch-only'))) launch();
