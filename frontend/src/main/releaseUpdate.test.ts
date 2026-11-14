import { afterEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { checkReleaseUpdate } from './releaseUpdate.js';

afterEach(() => vi.unstubAllGlobals());

describe('release update policy', () => {
  it('forces a supported release when the current version is below its declared minimum', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ tag_name: 'v2.4.0', body: 'Notes\nMinimum-Atlas-Version: 2.3.0', assets: [] }),
    }));

    await expect(checkReleaseUpdate('https://api.github.com/repos/atlas/atlas/releases/latest', '2.1.0', 'unused-test-userdata'))
      .resolves.toEqual(expect.objectContaining({ supported: true, current: '2.1.0', latest: 'v2.4.0', minimumVersion: '2.3.0', mandatory: true, available: true }));
  });

  it('does not force a current version that meets the declared minimum', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ tag_name: 'v2.4.0', body: 'Minimum-Atlas-Version: 2.3.0', assets: [] }),
    }));

    await expect(checkReleaseUpdate('https://api.github.com/repos/atlas/atlas/releases/latest', '2.3.0', 'unused-test-userdata'))
      .resolves.toEqual(expect.objectContaining({ mandatory: false, available: true }));
  });

  it('does not let skipped versions or reminder delays suppress mandatory updates', async () => {
    const userData = mkdtempSync(path.join(tmpdir(), 'atlas-release-policy-'));
    try {
      writeFileSync(path.join(userData, 'release-update-prefs.json'), JSON.stringify({ skipped: '2.4.0', remindAfter: Date.now() + 86_400_000 }));
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        status: 200, ok: true,
        json: async () => ({ tag_name: '2.4.0', body: 'Minimum-Atlas-Version: 2.3.0', assets: [{ name: 'Atlas-Setup.exe' }] }),
      }));
      await expect(checkReleaseUpdate('https://updates.example/release', '2.1.0', userData))
        .resolves.toMatchObject({ mandatory: true, available: true, skipped: true, assetName: 'Atlas-Setup.exe' });
    } finally { rmSync(userData, { recursive: true, force: true }); }
  });

  it('rejects a minimum version that the published release cannot satisfy', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200, ok: true,
      json: async () => ({ tag_name: '2.4.0', body: 'Minimum-Atlas-Version: 3.0.0' }),
    }));
    await expect(checkReleaseUpdate('https://updates.example/release', '2.1.0', 'unused-test-userdata'))
      .resolves.toMatchObject({ available: false, error: 'Release 的最低支持版本高于当前发布版本。' });
  });
});
