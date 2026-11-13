import { afterEach, describe, expect, it, vi } from 'vitest';
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
});
