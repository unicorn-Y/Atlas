import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';
import type { SourceUpdateStatus } from '../shared/ipc.js';

const run = promisify(execFile);
export type UpdateSource = { remote: string; branch: string };

export function validateUpdateSource(value: unknown): UpdateSource {
  if (!value || typeof value !== 'object') throw new Error('更新来源格式无效。');
  const { remote, branch } = value as UpdateSource;
  if (typeof remote !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(remote)
    || typeof branch !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_./-]{0,199}$/.test(branch)
    || branch.includes('..') || branch.includes('//') || branch.endsWith('/') || branch.endsWith('.lock')) {
    throw new Error('请选择仓库已有的 remote 名称和有效分支名。');
  }
  return { remote, branch };
}

async function git(root: string, args: string[]): Promise<string> {
  const { stdout } = await run('git', ['-C', root, ...args], { shell: false, windowsHide: true, timeout: 60_000, maxBuffer: 1024 * 1024 });
  return stdout.trim();
}

export async function defaultUpdateSource(root: string): Promise<UpdateSource> {
  return validateUpdateSource({ remote: 'origin', branch: await git(root, ['rev-parse', '--abbrev-ref', 'HEAD']) });
}

async function resolveTarget(root: string, source: UpdateSource): Promise<string> {
  validateUpdateSource(source);
  await git(root, ['check-ref-format', `refs/heads/${source.branch}`]);
  // Only configured repository remotes, never renderer-provided URLs or local paths.
  await git(root, ['remote', 'get-url', source.remote]);
  const ref = `refs/atlas-update/${source.remote}/${source.branch}`;
  await git(root, ['fetch', '--no-tags', source.remote, `+refs/heads/${source.branch}:${ref}`]);
  return git(root, ['rev-parse', '--verify', `${ref}^{commit}`]);
}

export async function checkConfiguredUpdate(root: string | null, source: UpdateSource): Promise<SourceUpdateStatus> {
  const empty = { supported: Boolean(root), available: false, behind: 0, commits: [], branch: `${source.remote}/${source.branch}` };
  if (!root) return { ...empty, blocked: '此安装不是源码模式，没有可用的签名发布 feed。' };
  try {
    const target = await resolveTarget(root, source);
    const behind = Number(await git(root, ['rev-list', '--count', `HEAD..${target}`]));
    let blocked: string | undefined;
    if (await git(root, ['status', '--porcelain'])) blocked = '工作区有未提交或未跟踪文件，不能更新。';
    else {
      try { await git(root, ['merge-base', '--is-ancestor', 'HEAD', target]); }
      catch { blocked = '所选源不能快进当前分支；需要手动处理分支关系。'; }
    }
    const log = behind ? await git(root, ['log', '--format=%h%x09%s', '-n', '20', `HEAD..${target}`]) : '';
    return { ...empty, behind, available: behind > 0, blocked, commits: log ? log.split('\n').map((line) => { const [hash, ...rest] = line.split('\t'); return { hash, subject: rest.join('\t') }; }) : [] };
  } catch {
    return { ...empty, error: '无法检查所选更新来源；请核对 remote、分支、凭据及网络。' };
  }
}

export async function applyConfiguredUpdate(root: string, source: UpdateSource): Promise<void> {
  const target = await resolveTarget(root, source);
  if (await git(root, ['status', '--porcelain'])) throw new Error('工作区存在改动，已拒绝更新。');
  await git(root, ['merge-base', '--is-ancestor', 'HEAD', target]);
  const head = await git(root, ['rev-parse', 'HEAD']);
  // Merge only after Electron and its managed backend stop. Recheck state so an
  // edit or another update during shutdown cannot be overwritten.
  const runner = `
    const { execFileSync, spawn } = require('node:child_process');
    const fs = require('node:fs');
    const path = require('node:path');
    const [root, target, pid, head] = process.argv.slice(1);
    const git = (...args) => execFileSync('git', ['-C', root, ...args], { shell: false, windowsHide: true, encoding: 'utf8' }).trim();
    (async () => {
      const deadline = Date.now() + 120000;
      while (true) {
        try { process.kill(Number(pid), 0); } catch { break; }
        if (Date.now() > deadline) process.exit(1);
        await new Promise(resolve => setTimeout(resolve, 300));
      }
      let result;
      try {
        if (git('status', '--porcelain') || git('rev-parse', 'HEAD') !== head) throw new Error('Checkout changed during shutdown');
        git('merge-base', '--is-ancestor', 'HEAD', target);
        git('merge', '--ff-only', target);
        result = { ok: true, head: target, source: ${JSON.stringify(`${source.remote}/${source.branch}`)} };
      } catch { result = { ok: false, error: '更新状态发生变化，已保留当前检出。' }; }
      fs.mkdirSync(path.join(root, 'data'), { recursive: true });
      fs.writeFileSync(path.join(root, 'data', 'update-status.json'), JSON.stringify({ ...result, at: new Date().toISOString() }));
      const child = spawn('node', [path.join(root, 'scripts', 'atlas-update.mjs'), '--launch-only'], { cwd: root, shell: false, detached: true, stdio: 'ignore', windowsHide: true });
      child.once('error', () => process.exit(1));
      child.once('spawn', () => child.unref());
    })().catch(() => process.exit(1));
  `;
  await new Promise<void>((resolve, reject) => {
    const child = spawn('node', ['-e', runner, root, target, String(process.pid), head], {
      cwd: root, shell: false, detached: true, stdio: 'ignore', windowsHide: true,
    });
    child.once('error', reject);
    child.once('spawn', () => { child.unref(); resolve(); });
  });
}
