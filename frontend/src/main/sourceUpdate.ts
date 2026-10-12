/**
 * Source-mode updates: Atlas runs straight from a git checkout (see scripts/atlas-update.mjs).
 * The main process checks the remote for new commits and, when the user agrees, hands the
 * update to the updater script and quits so it can pull, rebuild and relaunch.
 */
import { execFile, spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);

export type { SourceUpdateStatus } from '../shared/ipc.js';
import type { SourceUpdateStatus } from '../shared/ipc.js';

export function sourceRoot(appPath: string): string | null {
  const root = path.resolve(appPath, '..');
  return fs.existsSync(path.join(root, '.git')) && fs.existsSync(path.join(root, 'scripts', 'atlas-update.mjs'))
    ? root : null;
}

async function git(root: string, args: string[], timeout = 30_000): Promise<string> {
  const { stdout } = await run('git', ['-C', root, ...args], { timeout, windowsHide: true, encoding: 'utf8' });
  return args.includes('-z') ? stdout : stdout.trim();
}

export async function checkSourceUpdate(root: string | null): Promise<SourceUpdateStatus> {
  const empty = { available: false, behind: 0, commits: [] };
  if (!root) return { supported: false, ...empty };
  try {
    const branch = await git(root, ['rev-parse', '--abbrev-ref', 'HEAD']);
    // A verified Atlas 追新 result that could not be pushed waits in data/upstream (see
    // scripts/atlas-update.mjs); it counts as an update just like new commits on the remote.
    const pending = await pendingUpstreamCommit(root);
    let target = `origin/${branch}`;
    try {
      await git(root, ['fetch', '--quiet', 'origin', branch], 60_000);
    } catch (error) {
      if (!pending) throw error;
      target = pending;
    }
    if (pending && target !== pending) {
      const pendingAhead = Number(await git(root, ['rev-list', '--count', `${target}..${pending}`])) || 0;
      if (pendingAhead) target = pending;
    }
    const behind = Number(await git(root, ['rev-list', '--count', `HEAD..${target}`])) || 0;
    const log = behind
      ? await git(root, ['log', '--format=%h%x09%s', '-n', '20', `HEAD..${target}`])
      : '';
    const [modified, untracked, incoming] = await Promise.all([
      git(root, ['diff', '--name-only', '--no-renames', '-z', 'HEAD']),
      git(root, ['ls-files', '--others', '--exclude-standard', '-z']),
      git(root, ['diff', '--name-only', '--no-renames', '-z', `HEAD...${target}`]),
    ]);
    const incomingFiles = incoming.split('\0').filter(Boolean);
    const collisions = [...new Set([...modified.split('\0'), ...untracked.split('\0')])]
      .filter((file) => file && incomingFiles.some((next) =>
        next === file || next.startsWith(`${file}/`) || file.startsWith(`${next}/`)));
    return {
      supported: true,
      available: behind > 0,
      behind,
      branch,
      commits: log ? log.split('\n').map((line) => {
        const [hash, ...rest] = line.split('\t');
        return { hash, subject: rest.join('\t') };
      }) : [],
      ...(collisions.length ? { blocked: `更新会覆盖本地改动：${collisions.slice(0, 5).join('、')}。请先保存或提交这些文件。` } : {}),
    };
  } catch (error) {
    return { supported: true, ...empty, error: error instanceof Error ? error.message : String(error) };
  }
}

async function pendingUpstreamCommit(root: string): Promise<string | null> {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(root, 'data', 'upstream', 'pending-merge.json'), 'utf8'));
    const commit = typeof data?.commit === 'string' ? data.commit : '';
    if (!/^[0-9a-f]{40}$/.test(commit)) return null;
    try {
      await git(root, ['merge-base', '--is-ancestor', commit, 'HEAD']);
      return null; // already merged
    } catch {
      return commit;
    }
  } catch {
    return null;
  }
}

/** Start the detached updater; it waits for this process to exit, then pulls, rebuilds and relaunches. */
export function launchSourceUpdater(root: string): void {
  const child = spawn('node',
    [path.join(root, 'scripts', 'atlas-update.mjs'), '--wait-pid', String(process.pid), '--relaunch'], {
      cwd: root,
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
  child.unref();
}
