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

// Atlas 追新 (core/atlas/upstream) leaves a verified commit in data/upstream/pending-merge.json
// when it could not push it; merge it here so a restart picks it up.
const pendingFile = path.join(root, 'data', 'upstream', 'pending-merge.json');
const readPending = () => { try { return JSON.parse(fs.readFileSync(pendingFile, 'utf8')); } catch { return null; } };

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
    // Keep the full local CDP control surface, but do not expose it to arbitrary origins or interfaces.
    electronArgs.push('--remote-debugging-address=127.0.0.1', `--remote-debugging-port=${debugPort}`);
  }
  electronArgs.push(path.join(root, 'frontend'));
  const child = spawn(electron, electronArgs, {
    cwd: root, detached: true, stdio: 'ignore', windowsHide: false,
    env: { ...process.env, ATLAS_PYTHON: python, VITE_DEV_SERVER_URL: '' },
  });
  child.unref();
  log(`launched Atlas (pid ${child.pid}) debug-port=${debugPort}`);
}

function runAt(workRoot, command, commandArgs, options = {}) {
  return execFileSync(command, commandArgs, {
    cwd: workRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    shell: isWin && command.endsWith('.cmd'), maxBuffer: 64 * 1024 * 1024, ...options,
  }).trim();
}

function replaceDirectory(source, target, backup, state) {
  state.hadTarget = fs.existsSync(target);
  if (state.hadTarget) {
    fs.renameSync(target, backup);
    state.backedUp = true;
  }
  state.activationStarted = true;
  fs.renameSync(source, target);
  state.activated = true;
}

function stagedUpdate() {
  const before = sh('git', ['rev-parse', 'HEAD']);
  if (sh('git', ['status', '--porcelain', '--untracked-files=no'])) {
    throw new Error('Update cancelled: tracked local changes must be committed or stashed first.');
  }
  const branch = sh('git', ['rev-parse', '--abbrev-ref', 'HEAD']);
  // Fetch into the active repository first. An up-to-date checkout needs no candidate
  // worktree, dependency setup, or build at all.
  try { sh('git', ['fetch', '--quiet', 'origin', branch]); }
  catch (error) {
    if (!readPending()) throw new Error(`fetch failed: ${String(error?.stderr || error?.message || error).trim()}`);
    log(`fetch skipped; applying verified pending commit instead: ${String(error?.message || error).split('\n')[0]}`);
  }
  const pendingBeforeStage = readPending();
  let targetHead = before;
  try {
    const remoteHead = sh('git', ['rev-parse', `origin/${branch}`]);
    runAt(root, 'git', ['merge-base', '--is-ancestor', before, remoteHead]);
    targetHead = remoteHead;
  } catch {
    // A diverged/nonexistent remote remains a hard failure in the candidate fast-forward.
  }
  if (pendingBeforeStage?.commit) {
    try { runAt(root, 'git', ['merge-base', '--is-ancestor', targetHead, pendingBeforeStage.commit]); targetHead = pendingBeforeStage.commit; }
    catch {
      try { runAt(root, 'git', ['merge-base', '--is-ancestor', pendingBeforeStage.commit, targetHead]); }
      catch { /* candidate merge below reports incompatible pending history */ }
    }
  }
  if (targetHead === before) return { pulled: false, reason: 'already up to date', before, after: before, changed: [] };
  const stage = path.join(path.dirname(root), `.atlas-update-stage-${process.pid}`);
  const candidate = path.join(stage, 'candidate');
  const backups = path.join(stage, 'backups');
  if (fs.existsSync(stage)) throw new Error(`Update staging path already exists: ${stage}`);
  fs.mkdirSync(stage, { recursive: true });
  let worktreeAdded = false;
  const changed = [];
  let committed = false;
  let safeToRemoveStage = false;
  const directoryStates = Object.fromEntries(['dist', 'dist-electron'].map((name) => [name, {
    target: path.join(root, 'frontend', name), backup: path.join(backups, name), hadTarget: false, backedUp: false, activationStarted: false, activated: false,
  }]));
  const resourceStates = {
    coreVenv: { target: path.join(root, 'core', '.venv'), backup: path.join(backups, 'core-venv'), hadTarget: false, backedUp: false, activationStarted: false, activated: false },
    nodeModules: { target: path.join(root, 'node_modules'), backup: path.join(backups, 'node_modules'), hadTarget: false, backedUp: false, activationStarted: false, activated: false },
    stamp: { target: stampFile, backup: path.join(backups, 'build-stamp.json'), hadTarget: false, backedUp: false, activationStarted: false, activated: false },
  };
  try {
    runAt(root, 'git', ['worktree', 'add', '--detach', candidate, before]);
    worktreeAdded = true;
    fs.mkdirSync(backups, { recursive: true });
    try {
      runAt(candidate, 'git', ['merge', '--ff-only', targetHead]);
    } catch (error) {
      if (!readPending()) throw new Error(`fetch/fast-forward failed: ${String(error?.stderr || error?.message || error).trim()}`);
      log(`fetch/fast-forward skipped; applying verified pending commit instead: ${String(error?.message || error).split('\n')[0]}`);
    }
    const pending = readPending();
    if (pending?.commit) {
      try { runAt(candidate, 'git', ['merge-base', '--is-ancestor', pending.commit, 'HEAD']); }
      catch { runAt(candidate, 'git', ['merge', '--ff-only', pending.commit]); }
    }
    const candidateHead = runAt(candidate, 'git', ['rev-parse', 'HEAD']);
    changed.push(...runAt(candidate, 'git', ['diff', '--name-only', before, candidateHead]).split('\n').filter(Boolean));

    const stagePython = path.join(candidate, 'core', '.venv', isWin ? 'Scripts/python.exe' : 'bin/python');
    if (!fs.existsSync(stagePython)) runAt(candidate, isWin ? 'py' : 'python', isWin
      ? ['-3.14', '-m', 'venv', path.join(candidate, 'core', '.venv')]
      : ['-m', 'venv', path.join(candidate, 'core', '.venv')]);
    const candidateStamp = path.join(candidate, 'data', 'build-stamp.json');
    if (!fs.existsSync(path.dirname(candidateStamp))) fs.mkdirSync(path.dirname(candidateStamp), { recursive: true });
    runAt(candidate, process.execPath, [path.join(candidate, 'scripts', 'atlas-update.mjs'), '--launch-only', '--no-launch']);
    const candidateBuildStamp = path.join(candidate, 'data', 'build-stamp.json');
    const candidateMissing = requiredBuildFiles.map((file) => path.join(candidate, path.relative(root, file)))
      .filter((file) => !fs.existsSync(file));
    if (candidateMissing.length) throw new Error(`Candidate build incomplete; missing: ${candidateMissing.map((file) => path.relative(candidate, file)).join(', ')}`);

    runAt(root, 'git', ['merge', '--ff-only', candidateHead]);
    committed = true;
    for (const [name, state] of Object.entries(directoryStates)) {
      replaceDirectory(path.join(candidate, 'frontend', name), state.target, state.backup, state);
    }

    const pythonChanged = changed.includes('core/pyproject.toml') || changed.includes('core/requirements.lock')
      || !fs.existsSync(python);
    if (pythonChanged) {
      const envBackup = path.join(backups, 'core-venv');
      const envPath = path.join(root, 'core', '.venv');
      const state = resourceStates.coreVenv;
      state.hadTarget = fs.existsSync(envPath);
      if (state.hadTarget) { fs.renameSync(envPath, envBackup); state.backedUp = true; }
      state.activationStarted = true;
      runAt(root, isWin ? 'py' : 'python', isWin
          ? ['-3.14', '-m', 'venv', envPath]
          : ['-m', 'venv', envPath]);
      state.activated = true;
      const activePython = path.join(envPath, isWin ? 'Scripts/python.exe' : 'bin/python');
      runAt(root, activePython, ['-m', 'pip', 'install', '-q', '--no-cache-dir', '-e', 'core']);
      runAt(root, activePython, ['-m', 'pip', 'install', '-q', '--disable-pip-version-check', '--no-cache-dir', '-r', 'core/requirements.lock']);
    }
    const activeElectron = path.join(root, 'node_modules', 'electron', 'dist', isWin ? 'electron.exe' : 'electron');
    const npmChanged = changed.some((file) => ['package.json', 'package-lock.json', 'frontend/package.json'].includes(file))
      || !fs.existsSync(activeElectron);
    if (npmChanged) {
      const modulesPath = path.join(root, 'node_modules');
      const modulesBackup = path.join(backups, 'node_modules');
      const state = resourceStates.nodeModules;
      state.hadTarget = fs.existsSync(modulesPath);
      if (state.hadTarget) { fs.renameSync(modulesPath, modulesBackup); state.backedUp = true; }
      state.activationStarted = true;
      runAt(root, npm, ['ci', '--no-audit', '--no-fund']);
      state.activated = true;
    }
    const newStamp = path.join(root, 'data', 'build-stamp.json.new');
    const stampState = resourceStates.stamp;
    stampState.hadTarget = fs.existsSync(stampFile);
    if (stampState.hadTarget) { fs.renameSync(stampFile, stampState.backup); stampState.backedUp = true; }
    stampState.activationStarted = true;
    fs.copyFileSync(candidateBuildStamp, newStamp);
    fs.renameSync(newStamp, stampFile);
    stampState.activated = true;
    // Run the active checkout's required rebuild/validation before discarding rollback data.
    const steps = rebuild();
    fs.rmSync(backups, { recursive: true, force: true });
    safeToRemoveStage = true;
    return { pulled: before !== candidateHead, before, after: candidateHead, changed, steps };
  } catch (error) {
    if (committed) {
      for (const state of Object.values(directoryStates)) {
        if ((state.backedUp || state.activationStarted) && fs.existsSync(state.target)) fs.rmSync(state.target, { recursive: true, force: true });
        if (state.backedUp && fs.existsSync(state.backup)) fs.renameSync(state.backup, state.target);
      }
      for (const state of Object.values(resourceStates)) {
        if ((state.backedUp || state.activationStarted) && fs.existsSync(state.target)) fs.rmSync(state.target, { recursive: true, force: true });
        if (state.backedUp && fs.existsSync(state.backup)) fs.renameSync(state.backup, state.target);
      }
      try { fs.rmSync(path.join(root, 'data', 'build-stamp.json.new'), { force: true }); } catch { /* best effort */ }
      runAt(root, 'git', ['reset', '--hard', before]);
      safeToRemoveStage = true;
    } else {
      safeToRemoveStage = true;
    }
    throw error;
  } finally {
    if (worktreeAdded) {
      try { runAt(root, 'git', ['worktree', 'remove', '--force', candidate]); } catch { /* retain error result; stale worktree can be repaired */ }
    }
    if (safeToRemoveStage) {
      try { fs.rmSync(stage, { recursive: true, force: true }); } catch { /* best-effort temporary cleanup */ }
    } else {
      log(`rollback incomplete; retained recovery files at ${stage}`);
    }
  }
}

// The desktop may skip rebuilding only when the stamp and every required bundle agree.
const completeBuild = () => missingBuildFiles().length === 0;
if (flag('--launch-only') && !flag('--no-launch') && readStamp() === sh('git', ['rev-parse', 'HEAD']) && completeBuild()) {
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
  if (flag('--no-launch')) {
    rebuild();
  } else if (flag('--launch-only')) {
    rebuild();
  } else {
    const result = stagedUpdate();
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
// Candidate-update failures leave the active checkout, dependencies and build untouched,
// so --relaunch can reopen that previous version. A direct launch-only rebuild failure
// may have changed the active source and must remain stopped.
if (!flag('--no-launch') && ((process.exitCode !== 1 && (flag('--relaunch') || flag('--launch-only')))
  || (process.exitCode === 1 && flag('--relaunch')))) launch();
