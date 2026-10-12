import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ dirty: '', incoming: '', untracked: '' }));
vi.mock('node:child_process', () => ({
  spawn: vi.fn(),
  execFile: vi.fn((_command, args, _options, callback) => {
    const command = args.slice(2);
    let stdout = '';
    if (command[0] === 'rev-parse') stdout = 'memory-v1\n';
    if (command[0] === 'rev-list') stdout = '2\n';
    if (command[0] === 'log') stdout = 'abc123\tUpdate dependencies\n';
    if (command[0] === 'status') stdout = state.dirty ? ' M engine/config.yaml\n' : '';
    if (command[0] === 'diff') stdout = command.some((arg: string) => arg.includes('...')) ? state.incoming : state.dirty;
    if (command[0] === 'ls-files') stdout = state.untracked;
    callback(null, stdout, '');
  }),
}));
vi.mock('node:util', async (importOriginal) => ({
  ...await importOriginal<typeof import('node:util')>(),
  promisify: (fn: (...args: any[]) => void) => (...args: any[]) => new Promise((resolve, reject) => {
    fn(...args, (error: Error | null, stdout: string, stderr: string) => {
      if (error) reject(error);
      else resolve({ stdout, stderr });
    });
  }),
}));

import { checkSourceUpdate } from './sourceUpdate.js';

describe('source update local changes', () => {
  beforeEach(() => {
    state.dirty = '';
    state.incoming = 'frontend/package.json\0';
    state.untracked = '';
  });

  it('allows an unrelated local configuration change', async () => {
    state.dirty = 'engine/config.yaml\0';
    const update = await checkSourceUpdate('/atlas-test-no-pending');
    expect(update.available).toBe(true);
    expect(update.blocked).toBeUndefined();
  });

  it('blocks an incoming file with local modifications', async () => {
    state.dirty = 'frontend/package.json\0';
    const update = await checkSourceUpdate('/atlas-test-no-pending');
    expect(update.blocked).toContain('frontend/package.json');
  });

  it('blocks an untracked file that the update would overwrite', async () => {
    state.untracked = 'frontend/package.json\0';
    expect((await checkSourceUpdate('/atlas-test-no-pending')).blocked).toContain('frontend/package.json');
  });

  it('preserves spaces in file names when comparing collisions', async () => {
    state.dirty = ' file with spaces.txt\0';
    state.incoming = ' file with spaces.txt\0';
    expect((await checkSourceUpdate('/atlas-test-no-pending')).blocked).toContain(' file with spaces.txt');
  });

  it('blocks a file/directory collision', async () => {
    state.untracked = 'frontend\0';
    expect((await checkSourceUpdate('/atlas-test-no-pending')).blocked).toContain('frontend');
  });
});
