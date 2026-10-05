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
  return stdout.trim();
}

export async function checkSourceUpdate(root: string | null): Promise<SourceUpdateStatus> {
  const empty = { available: false, behind: 0, commits: [] };
  if (!root) return { supported: false, ...empty };
  try {
    const branch = await git(root, ['rev-parse', '--abbrev-ref', 'HEAD']);
    await git(root, ['fetch', '--quiet', 'origin', branch], 60_000);
    const behind = Number(await git(root, ['rev-list', '--count', `HEAD..origin/${branch}`])) || 0;
    const log = behind
      ? await git(root, ['log', '--format=%h%x09%s', '-n', '20', `HEAD..origin/${branch}`])
      : '';
    const dirty = await git(root, ['status', '--porcelain', '--untracked-files=no']);
    return {
      supported: true,
      available: behind > 0,
      behind,
      branch,
      commits: log ? log.split('\n').map((line) => {
        const [hash, ...rest] = line.split('\t');
        return { hash, subject: rest.join('\t') };
      }) : [],
      ...(dirty ? { blocked: '本地有未提交的改动，更新前请先提交或撤销。' } : {}),
    };
  } catch (error) {
    return { supported: true, ...empty, error: error instanceof Error ? error.message : String(error) };
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
